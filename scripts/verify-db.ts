/**
 * Verification harness — Phase 2 proof of correctness.
 *
 *     npm run verify:db
 *
 * This script is the reason the data layer is built on the `SqlExecutor` interface instead of
 * `expo-sqlite` directly: it runs the **real** migrations, the **real** repositories and the
 * **real** sync engine against a **real** SQLite engine (`node:sqlite`, SQLite 3.51), in Node,
 * with no simulator, no emulator and no backend.
 *
 * What it asserts:
 *   • migrations apply from empty, are idempotent, and set `user_version`;
 *   • a full two-page-plus sync lands every row, and a second sync is a no-op (cursor works);
 *   • tombstones delete rows and the ON DELETE CASCADE cleans up children;
 *   • `foreign_keys = ON` is actually enforced;
 *   • a transient failure is retried and the pass still succeeds;
 *   • the offline departure board is correct — including the past-midnight GTFS case that a naive
 *     implementation gets wrong;
 *   • nearby-stop ranking, favourites, alarms + re-arm cooldown, and settings all round-trip.
 */

import { DatabaseSync, type StatementSync } from 'node:sqlite';

import {
  migrateDatabase,
  seedSyncState,
  applyPragmas,
  LATEST_SCHEMA_VERSION,
} from '../src/db/migrations';
import { buildUpsertPlan, rowToBindValues } from '../src/db/sql';
import type {
  SqlBindParams,
  SqlExecutor,
  SqlPreparedStatement,
  SqlRunResult,
} from '../src/db/types';
import { announceSection, check, finish, run } from './lib/harness';

// ---------------------------------------------------------------------------------------------
// node:sqlite → SqlExecutor adapter
// ---------------------------------------------------------------------------------------------

/**
 * `node:sqlite` is synchronous and rejects booleans; this adapter normalises both.
 * It also implements `prepareAsync`, which exercises the engine's prepared-statement fast path —
 * the same path expo-sqlite uses on device.
 */
function createNodeExecutor(database: DatabaseSync): SqlExecutor {
  const asArray = (params?: SqlBindParams): unknown[] => {
    if (params === undefined) return [];
    if (Array.isArray(params)) return params as unknown[];
    throw new Error('node:sqlite adapter only supports positional bind parameters in this harness');
  };

  return {
    async execAsync(source: string): Promise<void> {
      database.exec(source);
    },

    async runAsync(source: string, params?: SqlBindParams): Promise<SqlRunResult> {
      const statement = database.prepare(source);
      const before = totalChanges(database);
      const result = statement.run(...(asArray(params) as never[]));
      return {
        changes: Number(result.changes ?? totalChanges(database) - before),
        lastInsertRowId: Number(result.lastInsertRowid ?? 0),
      };
    },

    async getAllAsync<T>(source: string, params?: SqlBindParams): Promise<T[]> {
      const statement = database.prepare(source);
      return statement.all(...(asArray(params) as never[])) as T[];
    },

    async getFirstAsync<T>(source: string, params?: SqlBindParams): Promise<T | null> {
      const statement = database.prepare(source);
      const row = statement.get(...(asArray(params) as never[]));
      return (row as T | undefined) ?? null;
    },

    async prepareAsync(source: string): Promise<SqlPreparedStatement> {
      const statement: StatementSync = database.prepare(source);
      return {
        async executeAsync(params: SqlBindParams): Promise<void> {
          statement.run(...(asArray(params) as never[]));
        },
        async finalizeAsync(): Promise<void> {
          // node:sqlite frees statements with the handle; nothing to do.
        },
      };
    },
  };
}

function totalChanges(database: DatabaseSync): number {
  const row = database.prepare('SELECT total_changes() AS total').get() as { total: number };
  return Number(row.total);
}

// ---------------------------------------------------------------------------------------------
// Scenario
// ---------------------------------------------------------------------------------------------

async function main(): Promise<void> {
  const database = new DatabaseSync(':memory:');
  const db = createNodeExecutor(database);

  // Test fixtures are imported lazily so the harness reports import failures as check failures
  // rather than crashing before the first assertion.
  const { findNearbyStops, searchStops, setFavoriteStop, listFavoriteStops } =
    await import('../src/data/stops');
  const { getActiveServiceIds, getCalendarCoverage } = await import('../src/data/service');
  const { getDepartureBoard } = await import('../src/data/departures');
  const { syncGtfs } = await import('../src/sync/engine');
  const { buildMockFeed, createMockTransport } = await import('../src/sync/mockTransport');
  const { getTableCounts, listRecentSyncLogs, readSyncCursor, purgeGtfsData } =
    await import('../src/data/syncState');
  const { createStopAlarm, claimAlarmTrigger, listStopAlarms, countEnabledAlarms } =
    await import('../src/data/alarms');
  const { setSetting, getSetting, getThemeMode, setThemeMode } =
    await import('../src/data/settings');
  const { serviceDayCandidates, parseGtfsTime, formatServiceClock, toServiceDate } =
    await import('../src/utils/gtfsTime');

  // -------------------------------------------------------------------------------------------
  announceSection('1. Migrations');

  await applyPragmas(db, { preferWal: false });
  const first = await migrateDatabase(db);
  check('no prior schema version', first.fromVersion === 0, `fromVersion=${first.fromVersion}`);
  check(
    'all migrations applied',
    first.toVersion === LATEST_SCHEMA_VERSION && first.applied.length === LATEST_SCHEMA_VERSION,
    `toVersion=${first.toVersion}, applied=${first.applied.map((entry) => entry.version).join(',')}`,
  );
  check('no checksum drift on a fresh database', first.checksumMismatches.length === 0);

  const second = await migrateDatabase(db);
  check(
    'migrations are idempotent',
    second.applied.length === 0,
    `applied=${second.applied.length}`,
  );

  const userVersion = await db.getFirstAsync<{ user_version: number }>('PRAGMA user_version;');
  check(
    'user_version matches LATEST_SCHEMA_VERSION',
    userVersion?.user_version === LATEST_SCHEMA_VERSION,
    `user_version=${userVersion?.user_version}`,
  );

  const foreignKeys = await db.getFirstAsync<{ foreign_keys: number }>('PRAGMA foreign_keys;');
  check('foreign keys are enforced', foreignKeys?.foreign_keys === 1);

  await seedSyncState(db);
  const seeded = await db.getAllAsync<{ entity: string }>('SELECT entity FROM sync_state;');
  check('sync_state has a cursor row per entity', seeded.length === 6, `rows=${seeded.length}`);

  const tables = await db.getAllAsync<{ name: string }>(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name;",
  );
  const tableNames = tables.map((row) => row.name);
  for (const required of ['routes', 'stops', 'trips', 'stop_times', 'calendar', 'calendar_dates']) {
    check(`table "${required}" exists`, tableNames.includes(required));
  }

  const stopTimeColumns = await db.getAllAsync<{ name: string }>('PRAGMA table_info(stop_times);');
  const stopTimeColumnNames = stopTimeColumns.map((column) => column.name);
  check(
    'stop_times has the derived departure_seconds column',
    stopTimeColumnNames.includes('departure_seconds'),
  );
  check(
    'stop_times keeps the raw GTFS departure_time text',
    stopTimeColumnNames.includes('departure_time'),
  );

  // -------------------------------------------------------------------------------------------
  announceSection('2. Full sync (multi-page) + cursor idempotence');

  const feed = buildMockFeed({ gridSize: 4, headwayMinutes: 15, today: new Date() });
  const transport = createMockTransport({ feed });
  const pageSize = 250;

  const syncResult = await syncGtfs(db, transport, { pageSize, recordRun: true });
  check('first sync succeeded', syncResult.status === 'success', `status=${syncResult.status}`);
  check('wrote every entity', syncResult.entities.length === 6);
  check(
    'fetched more than one page per large entity',
    (syncResult.entities.find((entry) => entry.entity === 'stop_times')?.pages ?? 0) > 1,
    `stop_times pages=${
      syncResult.entities.find((entry) => entry.entity === 'stop_times')?.pages ?? 0
    }`,
  );

  const counts = await getTableCounts(db);
  check(
    'routes/stops/trips/calendar landed',
    counts.routes === feed.routes.length &&
      counts.stops === feed.stops.length - 1 && // one stop arrives tombstoned
      counts.trips === feed.trips.length &&
      counts.calendar === feed.calendar.length,
    JSON.stringify(counts),
  );
  check(
    'stop_times landed in full',
    counts.stop_times === feed.stopTimes.length,
    `expected=${feed.stopTimes.length} actual=${counts.stop_times}`,
  );

  const cursorAfterFirst = await readSyncCursor(db, 'stop_times');
  check('cursor advanced to the feed head', cursorAfterFirst > 0, `cursor=${cursorAfterFirst}`);

  const secondSync = await syncGtfs(db, transport, { pageSize, recordRun: true });
  check(
    'second sync is a no-op (cursor is respected)',
    secondSync.rowsWritten === 0 && secondSync.rowsDeleted === 0,
    `written=${secondSync.rowsWritten} deleted=${secondSync.rowsDeleted}`,
  );

  const fullResync = await syncGtfs(db, transport, {
    pageSize,
    fullResync: true,
    recordRun: false,
  });
  const countsAfterResync = await getTableCounts(db);
  check(
    'full resync upserts without duplicating rows',
    countsAfterResync.stop_times === counts.stop_times && countsAfterResync.stops === counts.stops,
    JSON.stringify(countsAfterResync),
  );
  check('full resync re-read every page', fullResync.rowsWritten === countsAfterResync.total);

  // -------------------------------------------------------------------------------------------
  announceSection('3. Tombstones, cascades, and constraints');

  const deletedStop = feed.stops.find(
    (stop) => stop.deleted_at !== undefined && stop.deleted_at !== null,
  );
  check('the mock feed contains a tombstoned stop', deletedStop !== undefined);
  const deletedStopRow = await db.getFirstAsync<{ stop_id: string }>(
    'SELECT stop_id FROM stops WHERE stop_id = ?;',
    [deletedStop?.stop_id ?? ''],
  );
  check('tombstoned stop was deleted locally', deletedStopRow === null);

  const orphanStopTimes = await db.getFirstAsync<{ count: number }>(
    'SELECT COUNT(*) AS count FROM stop_times WHERE stop_id = ?;',
    [deletedStop?.stop_id ?? ''],
  );
  check('its stop_times were removed with it', orphanStopTimes?.count === 0);

  const fkViolations = await db.getAllAsync<Record<string, unknown>>('PRAGMA foreign_key_check;');
  check(
    'no foreign-key violations after sync',
    fkViolations.length === 0,
    `rows=${fkViolations.length}`,
  );

  const integrity = await db.getFirstAsync<{ integrity_check: string }>('PRAGMA integrity_check;');
  check(
    'integrity_check is ok',
    integrity?.integrity_check === 'ok',
    String(integrity?.integrity_check),
  );

  let fkEnforced = false;
  try {
    await db.runAsync(
      `INSERT INTO trips (trip_id, route_id, service_id, updated_at, sync_version)
       VALUES ('ORPHAN', 'DOES-NOT-EXIST', 'SVC', 0, 0);`,
    );
  } catch {
    fkEnforced = true;
  }
  check('inserting a trip with an unknown route is rejected', fkEnforced);

  // -------------------------------------------------------------------------------------------
  announceSection('4. Retry / backoff path');

  const retryFeed = buildMockFeed({ gridSize: 3, headwayMinutes: 30, today: new Date() });
  const flakyTransport = createMockTransport({ feed: retryFeed, failFirstAttempts: 3 });
  const retryResult = await syncGtfs(db, flakyTransport, {
    pageSize: 200,
    maxRetries: 4,
    entities: ['routes'],
    recordRun: false,
  });
  check(
    'a transport failing 3 times still succeeds within the retry budget',
    retryResult.status === 'success',
  );
  check(
    'retries were actually spent',
    flakyTransport.requestCount >= 4,
    `requests=${flakyTransport.requestCount}`,
  );

  const authResult = await syncGtfs(
    db,
    {
      source: 'rejecting',
      async fetchPage() {
        const { SyncError } = await import('../src/utils/errors');
        throw new SyncError('Invalid API key', { code: 'SYNC_UNAUTHORIZED', retryable: false });
      },
    },
    { entities: ['routes'], maxRetries: 5, recordRun: false },
  );
  check(
    'a permanent failure is not retried and is reported per entity',
    authResult.status === 'failed' && authResult.entities[0]?.error?.code === 'SYNC_UNAUTHORIZED',
    JSON.stringify(authResult.entities[0]?.error),
  );

  // -------------------------------------------------------------------------------------------
  announceSection('5. Offline departure board');

  const primaryStop = feed.stops.find(
    (stop) => stop.deleted_at === undefined || stop.deleted_at === null,
  );
  const stopId = primaryStop?.stop_id ?? 'MOCK-S001';

  const nearby = await findNearbyStops(
    db,
    { latitude: primaryStop?.stop_lat ?? 0, longitude: primaryStop?.stop_lon ?? 0 },
    { radiusMeters: 800, limit: 5 },
  );
  check('nearby lookup returns stops', nearby.length > 0, `found=${nearby.length}`);
  check(
    'results are sorted by distance ascending',
    nearby.every(
      (stop, index) =>
        index === 0 || stop.distanceMeters >= (nearby[index - 1]?.distanceMeters ?? 0),
    ),
  );
  check(
    'every result is inside the radius',
    nearby.every((stop) => stop.distanceMeters <= 800),
  );
  check(
    'the closest stop is the queried stop itself (distance ~0)',
    nearby[0]?.stopId === stopId,
    `closest=${nearby[0]?.stopId} expected=${stopId}`,
  );
  check('distances carry walking estimates', (nearby[0]?.walkingMinutes ?? 0) >= 0);

  // Midday on a weekday: the weekday service must be active and produce departures.
  const weekday = feed.calendar[0];
  check('mock feed exposes a weekday service', weekday !== undefined);

  const midday = new Date();
  midday.setDate(midday.getDate() + 1); // tomorrow, so the mock's "today" independence is irrelevant
  midday.setHours(12, 0, 0, 0);
  const middayServiceDate = toServiceDate(midday);
  const activeAtMidday = await getActiveServiceIds(db, middayServiceDate);
  check(
    'service ids resolve for a midday weekday (or null when the feed has no calendar)',
    activeAtMidday === null || activeAtMidday.length > 0,
    JSON.stringify(activeAtMidday),
  );

  const board = await getDepartureBoard(db, stopId, { now: midday, horizonMinutes: 120, limit: 6 });
  check(
    'departure board returns rows for a midday weekday',
    board.departures.length > 0,
    `rows=${board.departures.length}`,
  );
  check(
    'departures are ordered by time to arrival',
    board.departures.every(
      (departure, index) =>
        index === 0 || departure.minutesAway >= (board.departures[index - 1]?.minutesAway ?? 0),
    ),
  );
  check(
    'every departure is within the horizon',
    board.departures.every((departure) => departure.minutesAway <= 120),
  );
  check(
    'countdown labels are pre-formatted',
    board.departures.every((departure) => departure.countdownLabel.length > 0),
  );
  check(
    'routes carry their badge colour',
    board.departures.some((departure) => departure.route.color !== null),
  );

  // The GTFS past-midnight case: at 00:20, yesterday's 24:xx trips are still running.
  const afterMidnight = new Date(midday);
  afterMidnight.setHours(0, 20, 0, 0);
  const lateBoard = await getDepartureBoard(db, stopId, {
    now: afterMidnight,
    horizonMinutes: 90,
    limit: 6,
  });
  const candidates = serviceDayCandidates(afterMidnight);
  check(
    'service-day candidates include yesterday after midnight',
    candidates.length === 2 && candidates[1]?.dayOffset === -1,
    JSON.stringify(candidates.map((candidate) => candidate.serviceDate)),
  );
  check(
    'past-midnight board includes a 24h+ GTFS time',
    lateBoard.departures.some((departure) => departure.departureSeconds >= 86_400),
    `seconds=${lateBoard.departures.map((departure) => departure.departureSeconds).join(',')}`,
  );
  check(
    'the 24h+ departure is labelled with its day offset',
    lateBoard.departures
      .filter((departure) => departure.departureSeconds >= 86_400)
      .every((departure) => departure.departureClock.includes('+1')),
  );

  check('parseGtfsTime handles 25:10:00', parseGtfsTime('25:10:00') === 90_600);
  check('parseGtfsTime rejects garbage', parseGtfsTime('not-a-time') === null);
  check(
    'formatServiceClock folds 25:10 back to 01:10 (+1)',
    formatServiceClock(90_600) === '01:10 (+1)',
  );

  // -------------------------------------------------------------------------------------------
  announceSection('6. Search, favourites, alarms, settings');

  const searchResults = await searchStops(db, 'Pine', { limit: 5 });
  check(
    'name search matches the generated stops',
    searchResults.length > 0,
    `found=${searchResults.length}`,
  );

  const wildcardSearch = await searchStops(db, '%', { limit: 50 });
  check(
    'LIKE wildcards in user input are escaped',
    wildcardSearch.length === 0,
    `a bare % matched ${wildcardSearch.length} rows`,
  );

  await setFavoriteStop(db, stopId, true, 'Home stop');
  const favorites = await listFavoriteStops(db);
  check('favourite round-trips with its nickname', favorites[0]?.nickname === 'Home stop');
  await setFavoriteStop(db, stopId, false);
  check('favourite removal works', (await listFavoriteStops(db)).length === 0);

  const alarm = await createStopAlarm(db, { stopId, radiusMeters: 350, leadTimeMinutes: 4 });
  check(
    'alarm is created with a stable geofence identifier',
    alarm.geofence_identifier.startsWith('tp-stop-'),
  );
  check(
    'alarm defaults are persisted',
    alarm.radius_meters === 350 && alarm.lead_time_minutes === 4,
  );
  check('enabled alarms are counted', (await countEnabledAlarms(db)) === 1);
  check(
    'enabled alarms are listed for arming',
    (await listStopAlarms(db, { enabledOnly: true })).length === 1,
  );

  const firstClaim = await claimAlarmTrigger(db, alarm.alarm_id, 1_000_000);
  const secondClaim = await claimAlarmTrigger(db, alarm.alarm_id, 1_000_000 + 5_000);
  const thirdClaim = await claimAlarmTrigger(db, alarm.alarm_id, 1_000_000 + 120_000);
  check('the first trigger is claimed', firstClaim === true);
  check('a re-entry inside the cooldown is not re-notified', secondClaim === false);
  check('a re-entry after the cooldown is claimed again', thirdClaim === true);

  let invalidRejected = false;
  try {
    await createStopAlarm(db, { stopId, radiusMeters: 99 });
  } catch {
    invalidRejected = true;
  }
  check('an out-of-range radius is rejected', invalidRejected);

  await setSetting(db, 'onboarding_complete', '1');
  check('settings round-trip', (await getSetting(db, 'onboarding_complete')) === '1');
  await setThemeMode(db, 'outdoor');
  check('theme mode round-trips', (await getThemeMode(db)) === 'outdoor');

  const coverage = await getCalendarCoverage(db);
  check('calendar coverage is reported', coverage.serviceCount > 0 && coverage.startDate !== null);

  const runLogs = await listRecentSyncLogs(db, 5);
  check('sync runs are logged', runLogs.length >= 2, `rows=${runLogs.length}`);
  check(
    'a completed run records its totals',
    runLogs.some((row) => row.status === 'success' && row.rows_written > 0),
  );

  // -------------------------------------------------------------------------------------------
  announceSection('7. Upsert plan + purge');

  const upsert = buildUpsertPlan('stops');
  check(
    'upsert uses ON CONFLICT … DO UPDATE (never INSERT OR REPLACE)',
    upsert.sql.includes('ON CONFLICT') && upsert.sql.includes('DO UPDATE SET'),
  );
  check('upsert never rewrites primary keys', !upsert.sql.includes('stop_id = excluded.stop_id'));
  check(
    'rowToBindValues normalises booleans to 0/1',
    JSON.stringify(rowToBindValues(['a'], { a: true })) === '[1]',
  );

  const purge = await purgeGtfsData(db);
  const purged = await getTableCounts(db);
  check('purge empties every feed table', purged.total === 0, JSON.stringify(purged));
  check('purge resets cursors', (await readSyncCursor(db, 'stop_times')) === 0);
  check('purge reports the rows it removed', purge.deletedRows > 0, `rows=${purge.deletedRows}`);
  // Alarms hang off `stops` with ON DELETE CASCADE — documented, and surfaced to the user before
  // they confirm the reset, because an alarm without its stop's coordinates cannot be armed.
  check(
    'purging stops removes the alarms that pointed at them (and says so)',
    purge.alarmsRemoved === 1 && (await countEnabledAlarms(db)) === 0,
    `alarmsRemoved=${purge.alarmsRemoved}`,
  );

  database.close();
  finish();
}

run(main);
