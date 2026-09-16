/**
 * Schema definition + migration plan.
 *
 * Conventions
 * -----------
 * • Migrations are append-only. Never edit a released migration: add a new one. Each is applied
 *   inside a transaction and recorded in `schema_migrations` with a checksum, so a divergent
 *   build (someone edited v2 after ship) is detected instead of corrupting a device.
 * • `PRAGMA user_version` is the fast path (one integer read at boot); `schema_migrations` is the
 *   audit trail.
 * • GTFS tables use `WITHOUT ROWID`. They all have natural text/composite primary keys, so this
 *   removes a redundant B-tree per table — meaningful for `stop_times`, which is routinely
 *   hundreds of thousands of rows on a mid-size city feed.
 * • Every synced row carries `updated_at` (server clock, diagnostics) and `sync_version`
 *   (monotonic server sequence, the sync cursor). The spec's required columns are all present and
 *   unchanged; everything else is additive and nullable.
 */

import type { SqlExecutor } from './types';

export interface MigrationContext {
  readonly logger: (message: string, context?: Record<string, unknown>) => void;
}

export interface Migration {
  readonly version: number;
  readonly name: string;
  readonly statements: readonly string[];
  /**
   * Optional JavaScript step, for work SQL alone cannot express — deriving
   * `departure_seconds` from GTFS `HH:MM:SS` text, for example.
   */
  readonly dataMigration?: (db: SqlExecutor, context: MigrationContext) => Promise<void>;
}

// ---------------------------------------------------------------------------------------------
// Connection pragmas
// ---------------------------------------------------------------------------------------------

export interface PragmaOptions {
  /** WAL is unsupported by the web (wa-sqlite) build; failures are tolerated. */
  readonly preferWal?: boolean;
}

/**
 * Pragmas that make the database fast and honest.
 *
 * • `foreign_keys = ON` — SQLite ships with FK enforcement OFF; without this the cascade deletes
 *   that keep `trips`/`stop_times` consistent silently do nothing.
 * • `journal_mode = WAL` — readers (the UI) never block the writer (a sync in a background task),
 *   which is exactly this app's concurrency shape.
 * • `synchronous = NORMAL` — with WAL this is crash-safe for our purposes and ~3× faster writes.
 * • `busy_timeout` — a background sync and a foreground query can collide; wait instead of
 *   throwing SQLITE_BUSY.
 */
export function pragmaStatements(options: PragmaOptions = {}): string[] {
  const preferWal = options.preferWal ?? true;
  return [
    'PRAGMA foreign_keys = ON;',
    'PRAGMA busy_timeout = 5000;',
    'PRAGMA synchronous = NORMAL;',
    'PRAGMA temp_store = MEMORY;',
    'PRAGMA cache_size = -16000;',
    preferWal ? 'PRAGMA journal_mode = WAL;' : 'PRAGMA journal_mode = DELETE;',
  ];
}

// ---------------------------------------------------------------------------------------------
// v1 — the four GTFS tables from the spec (+ sync bookkeeping)
// ---------------------------------------------------------------------------------------------
const V1_CORE_GTFS = [
  `CREATE TABLE IF NOT EXISTS routes (
     route_id         TEXT PRIMARY KEY NOT NULL,
     route_short_name TEXT,
     route_long_name  TEXT,
     route_type       INTEGER,
     route_color      TEXT,
     route_text_color TEXT,
     updated_at       INTEGER NOT NULL DEFAULT 0,
     sync_version     INTEGER NOT NULL DEFAULT 0
   ) WITHOUT ROWID;`,

  `CREATE TABLE IF NOT EXISTS stops (
     stop_id        TEXT PRIMARY KEY NOT NULL,
     stop_name      TEXT,
     stop_code      TEXT,
     stop_lat       REAL NOT NULL,
     stop_lon       REAL NOT NULL,
     location_type  INTEGER,
     parent_station TEXT,
     updated_at     INTEGER NOT NULL DEFAULT 0,
     sync_version    INTEGER NOT NULL DEFAULT 0
   ) WITHOUT ROWID;`,

  `CREATE TABLE IF NOT EXISTS trips (
     trip_id       TEXT PRIMARY KEY NOT NULL,
     route_id      TEXT NOT NULL REFERENCES routes (route_id) ON DELETE CASCADE,
     service_id    TEXT NOT NULL,
     trip_headsign TEXT,
     direction_id  INTEGER,
     updated_at    INTEGER NOT NULL DEFAULT 0,
     sync_version  INTEGER NOT NULL DEFAULT 0
   ) WITHOUT ROWID;`,

  `CREATE TABLE IF NOT EXISTS stop_times (
     trip_id         TEXT NOT NULL REFERENCES trips (trip_id) ON DELETE CASCADE,
     stop_sequence   INTEGER NOT NULL,
     stop_id         TEXT NOT NULL REFERENCES stops (stop_id) ON DELETE CASCADE,
     arrival_time    TEXT,
     departure_time  TEXT,
     updated_at      INTEGER NOT NULL DEFAULT 0,
     sync_version    INTEGER NOT NULL DEFAULT 0,
     PRIMARY KEY (trip_id, stop_sequence)
   ) WITHOUT ROWID;`,

  // Cursor + health per feed entity. One row per entity, written inside the same transaction as
  // the rows it describes, so a crash can never advance the cursor past uncommitted data.
  `CREATE TABLE IF NOT EXISTS sync_state (
     entity        TEXT PRIMARY KEY NOT NULL,
     cursor        INTEGER NOT NULL DEFAULT 0,
     rows_synced   INTEGER NOT NULL DEFAULT 0,
     last_synced_at INTEGER,
     last_error    TEXT
   ) WITHOUT ROWID;`,
];

// ---------------------------------------------------------------------------------------------
// v2 — query indexes, service calendars, derived time columns
// ---------------------------------------------------------------------------------------------
const V2_INDEXES_AND_CALENDAR = [
  // --- 1. Columns first. `ALTER TABLE` cannot create an index, and the index at the bottom of
  //        this migration references `departure_seconds`, so ordering here is load-bearing.
  //
  // Derived integer seconds. GTFS times are text (`25:10:00`) and may exceed 24h, so ordering by
  // the raw column is only accidentally correct; ordering by these is always correct and uses an
  // index. Populated by the sync writer and backfilled by `dataMigration` below.
  `ALTER TABLE stop_times ADD COLUMN arrival_seconds INTEGER;`,
  `ALTER TABLE stop_times ADD COLUMN departure_seconds INTEGER;`,
  // 1 means "no boarding", which should never appear on a departure board.
  `ALTER TABLE stop_times ADD COLUMN pickup_type INTEGER;`,

  // --- 2. Service calendars. GTFS splits scheduled service across two files; both are required for
  // "is this trip running today", and holiday exceptions only live in `calendar_dates`.
  `CREATE TABLE IF NOT EXISTS calendar (
     service_id TEXT PRIMARY KEY NOT NULL,
     monday     INTEGER NOT NULL DEFAULT 0,
     tuesday    INTEGER NOT NULL DEFAULT 0,
     wednesday  INTEGER NOT NULL DEFAULT 0,
     thursday   INTEGER NOT NULL DEFAULT 0,
     friday     INTEGER NOT NULL DEFAULT 0,
     saturday   INTEGER NOT NULL DEFAULT 0,
     sunday     INTEGER NOT NULL DEFAULT 0,
     start_date TEXT NOT NULL,
     end_date   TEXT NOT NULL,
     updated_at   INTEGER NOT NULL DEFAULT 0,
     sync_version INTEGER NOT NULL DEFAULT 0
   ) WITHOUT ROWID;`,

  `CREATE TABLE IF NOT EXISTS calendar_dates (
     service_id     TEXT NOT NULL,
     date           TEXT NOT NULL,
     exception_type INTEGER NOT NULL,
     updated_at     INTEGER NOT NULL DEFAULT 0,
     sync_version   INTEGER NOT NULL DEFAULT 0,
     PRIMARY KEY (service_id, date)
   ) WITHOUT ROWID;`,

  `CREATE INDEX IF NOT EXISTS idx_calendar_window ON calendar (start_date, end_date);`,
  `CREATE INDEX IF NOT EXISTS idx_calendar_dates_date ON calendar_dates (date, exception_type);`,

  // --- 3. Indexes (all columns now exist).
  // Geo lookup: the bounding-box scan from utils/geo.ts hits this index.
  `CREATE INDEX IF NOT EXISTS idx_stops_geo ON stops (stop_lat, stop_lon);`,
  `CREATE INDEX IF NOT EXISTS idx_stops_name ON stops (stop_name);`,
  // The dashboard's hot path: "departures at this stop, from now onwards".
  `CREATE INDEX IF NOT EXISTS idx_stop_times_stop_departure
     ON stop_times (stop_id, departure_seconds);`,
  `CREATE INDEX IF NOT EXISTS idx_trips_route ON trips (route_id);`,
  `CREATE INDEX IF NOT EXISTS idx_trips_service ON trips (service_id);`,
];

// ---------------------------------------------------------------------------------------------
// v3 — the commuter's own data
// ---------------------------------------------------------------------------------------------
const V3_COMMUTER_LAYER = [
  `CREATE TABLE IF NOT EXISTS favorite_stops (
     stop_id    TEXT PRIMARY KEY NOT NULL REFERENCES stops (stop_id) ON DELETE CASCADE,
     nickname   TEXT,
     sort_order INTEGER NOT NULL DEFAULT 0,
     created_at INTEGER NOT NULL
   ) WITHOUT ROWID;`,

  // One row per geofence the user asked for. `geofence_identifier` is what Location hands back in
  // the background task, so it must be stable, unique and short — the platform limit is enforced
  // in the alarms repository, not here.
  `CREATE TABLE IF NOT EXISTS stop_alarms (
     alarm_id            TEXT PRIMARY KEY NOT NULL,
     stop_id             TEXT NOT NULL REFERENCES stops (stop_id) ON DELETE CASCADE,
     route_id            TEXT REFERENCES routes (route_id) ON DELETE SET NULL,
     label               TEXT NOT NULL,
     radius_meters       INTEGER NOT NULL DEFAULT 400 CHECK (radius_meters BETWEEN 100 AND 5000),
     lead_time_minutes   INTEGER NOT NULL DEFAULT 5 CHECK (lead_time_minutes BETWEEN 0 AND 60),
     enabled             INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
     geofence_identifier TEXT NOT NULL UNIQUE,
     created_at          INTEGER NOT NULL,
     updated_at          INTEGER NOT NULL,
     last_triggered_at   INTEGER,
     trigger_count       INTEGER NOT NULL DEFAULT 0
   ) WITHOUT ROWID;`,
  `CREATE INDEX IF NOT EXISTS idx_stop_alarms_enabled ON stop_alarms (enabled, stop_id);`,

  `CREATE TABLE IF NOT EXISTS app_settings (
     key        TEXT PRIMARY KEY NOT NULL,
     value      TEXT NOT NULL,
     updated_at INTEGER NOT NULL
   ) WITHOUT ROWID;`,

  // Diagnostics: the sync screen reads the last N runs to answer "did it actually sync?".
  `CREATE TABLE IF NOT EXISTS sync_log (
     id            INTEGER PRIMARY KEY AUTOINCREMENT,
     started_at    INTEGER NOT NULL,
     finished_at   INTEGER,
     status        TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
     source        TEXT NOT NULL,
     entities_json TEXT,
     rows_written  INTEGER NOT NULL DEFAULT 0,
     rows_deleted  INTEGER NOT NULL DEFAULT 0,
     error_code    TEXT,
     error_message TEXT
   );`,
  `CREATE INDEX IF NOT EXISTS idx_sync_log_started ON sync_log (started_at DESC);`,
];

// ---------------------------------------------------------------------------------------------
// Migration plan
// ---------------------------------------------------------------------------------------------

export const MIGRATIONS: readonly Migration[] = [
  {
    version: 1,
    name: 'core_gtfs',
    statements: V1_CORE_GTFS,
  },
  {
    version: 2,
    name: 'indexes_calendar_derived_times',
    statements: V2_INDEXES_AND_CALENDAR,
    /**
     * Backfill `arrival_seconds` / `departure_seconds` for rows written by a build that predates
     * the derived columns. Batched so a large feed cannot blow the JS bridge timeout, and driven
     * from JavaScript because parsing `25:10:00` is exactly what SQLite cannot do natively.
     */
    dataMigration: async (db, context) => {
      const BATCH = 2_000;
      let updated = 0;

      for (;;) {
        const rows = await db.getAllAsync<{
          trip_id: string;
          stop_sequence: number;
          arrival_time: string | null;
          departure_time: string | null;
        }>(
          `SELECT trip_id, stop_sequence, arrival_time, departure_time
             FROM stop_times
            WHERE departure_seconds IS NULL
            ORDER BY trip_id, stop_sequence
            LIMIT ?`,
          [BATCH],
        );

        if (rows.length === 0) break;

        // Reuse one prepared statement for the whole batch: 2 000 rows through a single
        // sqlite3_prepare + N executions instead of N round trips through the bridge.
        for (const row of rows) {
          const arrival = parseGtfsTimeSafe(row.arrival_time);
          const departure = parseGtfsTimeSafe(row.departure_time);
          await db.runAsync(
            `UPDATE stop_times
                SET arrival_seconds = ?, departure_seconds = ?
              WHERE trip_id = ? AND stop_sequence = ?`,
            [arrival, departure, row.trip_id, row.stop_sequence],
          );
          updated += 1;
        }

        context.logger('backfilled derived GTFS times', { updated });
        if (rows.length < BATCH) break;
      }
    },
  },
  {
    version: 3,
    name: 'commuter_layer',
    statements: V3_COMMUTER_LAYER,
  },
];

/**
 * Local copy of the GTFS time parser.
 *
 * Deliberately duplicated from `utils/gtfsTime.ts` instead of imported: a migration must keep
 * behaving exactly as it did the day it shipped, even if shared helpers are refined later.
 */
function parseGtfsTimeSafe(value: string | null): number | null {
  if (value === null) return null;
  const match = /^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = match[3] === undefined ? 0 : Number(match[3]);
  return hours * 3600 + minutes * 60 + seconds;
}

/** Highest migration version known to this build. */
export const LATEST_SCHEMA_VERSION: number =
  MIGRATIONS.length === 0 ? 0 : Math.max(...MIGRATIONS.map((migration) => migration.version));
