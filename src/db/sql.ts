/**
 * SQL construction.
 *
 * Everything that builds SQL lives here so that (a) the sync engine can reuse one prepared upsert
 * per table, and (b) the dashboard's hot queries are defined once and covered by the Node
 * verification harness.
 *
 * Safety: identifiers are validated against `^[a-z_][a-z0-9_]*$` and every *value* is bound as a
 * parameter. The only interpolation anywhere is validated identifiers and integer placeholders.
 */

import { boundingBox, type BoundingBox, type Coordinates } from '../utils/geo';
import { GTFS_WEEKDAY_COLUMNS, type GtfsWeekdayColumn } from '../utils/gtfsTime';
import { SYNCABLE_TABLES, type SqlBindValue, type SyncableTable } from './types';

const IDENTIFIER_PATTERN = /^[a-z_][a-z0-9_]*$/;

/**
 * SQLite's default `SQLITE_MAX_VARIABLE_NUMBER` was 999 until 3.32 and is 32 766 after. Devices
 * ship both. Staying under the old ceiling keeps one query shape working everywhere.
 */
export const MAX_SQL_VARIABLES = 900;

export function assertIdentifier(identifier: string): string {
  if (!IDENTIFIER_PATTERN.test(identifier)) {
    throw new Error(`Unsafe SQL identifier rejected: ${JSON.stringify(identifier)}`);
  }
  return identifier;
}

export function placeholders(count: number): string {
  if (!Number.isInteger(count) || count < 1) {
    throw new RangeError(`placeholders() requires a positive integer, received ${count}`);
  }
  return new Array(count).fill('?').join(', ');
}

// ---------------------------------------------------------------------------------------------
// Column registry — the single source of truth for what a sync writes.
// ---------------------------------------------------------------------------------------------

/** Insertable columns per synced table, in bind order. */
export const SYNC_TABLE_COLUMNS: Record<SyncableTable, readonly string[]> = {
  routes: [
    'route_id',
    'route_short_name',
    'route_long_name',
    'route_type',
    'route_color',
    'route_text_color',
    'updated_at',
    'sync_version',
  ],
  stops: [
    'stop_id',
    'stop_name',
    'stop_code',
    'stop_lat',
    'stop_lon',
    'location_type',
    'parent_station',
    'updated_at',
    'sync_version',
  ],
  trips: [
    'trip_id',
    'route_id',
    'service_id',
    'trip_headsign',
    'direction_id',
    'updated_at',
    'sync_version',
  ],
  stop_times: [
    'trip_id',
    'stop_sequence',
    'stop_id',
    'arrival_time',
    'departure_time',
    'arrival_seconds',
    'departure_seconds',
    'pickup_type',
    'updated_at',
    'sync_version',
  ],
  calendar: [
    'service_id',
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
    'start_date',
    'end_date',
    'updated_at',
    'sync_version',
  ],
  calendar_dates: ['service_id', 'date', 'exception_type', 'updated_at', 'sync_version'],
};

/** Primary key per synced table — the `ON CONFLICT` target. */
export const SYNC_TABLE_KEY_COLUMNS: Record<SyncableTable, readonly string[]> = {
  routes: ['route_id'],
  stops: ['stop_id'],
  trips: ['trip_id'],
  stop_times: ['trip_id', 'stop_sequence'],
  calendar: ['service_id'],
  calendar_dates: ['service_id', 'date'],
};

/** Columns that must never be overwritten from the payload on conflict. */
const IMMUTABLE_ON_CONFLICT = new Set(['stop_id', 'trip_id']);

export interface UpsertPlan {
  readonly table: SyncableTable;
  readonly sql: string;
  readonly bindColumns: readonly string[];
}

/**
 * Builds `INSERT … ON CONFLICT(key) DO UPDATE SET …`.
 *
 * Why not `INSERT OR REPLACE`: `OR REPLACE` deletes the conflicting row and inserts a new one,
 * which fires `ON DELETE CASCADE` on children. Replacing one `routes` row would wipe every `trip`
 * that references it. `DO UPDATE` mutates in place and leaves foreign keys intact.
 */
export function buildUpsertPlan(table: SyncableTable, columns?: readonly string[]): UpsertPlan {
  assertIdentifier(table);
  const bindColumns = (columns ?? SYNC_TABLE_COLUMNS[table]).map(assertIdentifier);
  const keyColumns = SYNC_TABLE_KEY_COLUMNS[table].map(assertIdentifier);

  for (const key of keyColumns) {
    if (!bindColumns.includes(key)) {
      throw new Error(`Upsert for ${table} is missing key column ${key}`);
    }
  }

  const updatable = bindColumns.filter(
    (column) => !keyColumns.includes(column) && !IMMUTABLE_ON_CONFLICT.has(column),
  );

  const conflictTarget = keyColumns.join(', ');
  const insertClause = `INSERT INTO ${table} (${bindColumns.join(', ')})
     VALUES (${placeholders(bindColumns.length)})`;

  // `DO NOTHING` is only reachable when every non-key column is immutable; keep the SQL valid.
  const conflictClause =
    updatable.length === 0
      ? `ON CONFLICT (${conflictTarget}) DO NOTHING`
      : `ON CONFLICT (${conflictTarget}) DO UPDATE SET ${updatable
          .map((column) => `${column} = excluded.${column}`)
          .join(', ')}`;

  return { table, sql: `${insertClause} ${conflictClause};`, bindColumns };
}

/** `DELETE FROM t WHERE k1 = ? AND k2 = ?` for tombstone handling. */
export function buildDeleteByKeyPlan(table: SyncableTable): UpsertPlan {
  assertIdentifier(table);
  const keyColumns = SYNC_TABLE_KEY_COLUMNS[table].map(assertIdentifier);
  return {
    table,
    sql: `DELETE FROM ${table} WHERE ${keyColumns.map((column) => `${column} = ?`).join(' AND ')};`,
    bindColumns: keyColumns,
  };
}

/**
 * Converts a row object into positional bind values, in the plan's column order.
 *
 * Normalisations that matter for portability:
 *  • `undefined` → `NULL` (SQLite has no concept of undefined; binding it throws).
 *  • `boolean`  → `0 | 1` (expo-sqlite accepts booleans, `node:sqlite` rejects them).
 *  • `Date`     → epoch milliseconds.
 */
export function rowToBindValues(bindColumns: readonly string[], row: object): SqlBindValue[] {
  const record = row as Record<string, unknown>;
  return bindColumns.map((column) => normalizeBindValue(record[column], column));
}

function normalizeBindValue(value: unknown, column: string): SqlBindValue {
  if (value === undefined || value === null) return null;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (value instanceof Date) return value.getTime();
  if (
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'bigint' ||
    value instanceof Uint8Array
  ) {
    return typeof value === 'bigint' ? Number(value) : value;
  }
  throw new TypeError(
    `Cannot bind column "${column}": expected string | number | boolean | null, received ${typeof value}`,
  );
}

// ---------------------------------------------------------------------------------------------
// Dashboard queries
// ---------------------------------------------------------------------------------------------

export interface BuiltQuery {
  readonly sql: string;
  readonly params: SqlBindValue[];
}

export interface NearbyStopsOptions {
  readonly radiusMeters: number;
  readonly limit: number;
  /** Include stations/parents and entrances (`location_type != 0`). Default false. */
  readonly includeNonBoardable?: boolean;
}

/**
 * Candidate stops inside the bounding box around the commuter.
 *
 * The box is a cheap, index-friendly superset of the true radius; `util/geo.haversineMeters()`
 * then ranks and filters the results in JavaScript. This keeps SQLite free of `sin()`/`cos()`,
 * which are not guaranteed to be compiled into every SQLite build shipping in an app store.
 */
export function buildNearbyStopsQuery(
  center: Coordinates,
  options: NearbyStopsOptions,
): BuiltQuery {
  const box: BoundingBox = boundingBox(center, options.radiusMeters);
  assertIdentifier('stops');

  // Normalised (min ≤ max) in the common case; the wrapped case needs both edge ranges, which
  // SQLite cannot express with a single BETWEEN.
  const lonClause = box.crossesAntimeridian
    ? '(stop_lon >= ? OR stop_lon <= ?)'
    : 'stop_lon BETWEEN ? AND ?';

  return {
    sql: `SELECT stop_id, stop_name, stop_code, stop_lat, stop_lon, location_type, parent_station
            FROM stops
           WHERE stop_lat BETWEEN ? AND ?
             AND ${lonClause}
             ${options.includeNonBoardable ? '' : 'AND (location_type IS NULL OR location_type = 0)'}
           LIMIT ?;`,
    params: [box.minLat, box.maxLat, box.minLon, box.maxLon, options.limit],
  };
}

export interface DeparturesQueryOptions {
  readonly stopId: string;
  /**
   * Service ids active on the candidate service day.
   * `null` means the feed carries no `calendar`/`calendar_dates` data at all — in that case the
   * service filter is dropped rather than returning an empty board for a feed that works fine.
   */
  readonly serviceIds: readonly string[] | null;
  /** Lower bound on `departure_seconds` for that service day. */
  readonly minSeconds: number;
  readonly limit: number;
}

/**
 * Departures at one stop from `minSeconds` onwards, for one service day.
 *
 * Hits `idx_stop_times_stop_departure (stop_id, departure_seconds)` and joins the route/trip
 * metadata the board needs. `pickup_type = 1` stops are excluded — those are drop-off-only.
 */
export function buildDeparturesQuery(options: DeparturesQueryOptions): BuiltQuery | null {
  const serviceIds =
    options.serviceIds === null ? null : options.serviceIds.slice(0, MAX_SQL_VARIABLES - 4);
  if (serviceIds !== null && serviceIds.length === 0) {
    return null; // A calendar is present and nothing runs on this service day: nothing to query.
  }

  const serviceClause =
    serviceIds === null ? '' : `AND t.service_id IN (${placeholders(serviceIds.length)})`;

  return {
    sql: `SELECT st.trip_id       AS trip_id,
                 st.stop_sequence AS stop_sequence,
                 st.departure_time AS departure_time,
                 st.departure_seconds AS departure_seconds,
                 t.service_id    AS service_id,
                 t.trip_headsign AS trip_headsign,
                 t.direction_id  AS direction_id,
                 r.route_id      AS route_id,
                 r.route_short_name AS route_short_name,
                 r.route_long_name  AS route_long_name,
                 r.route_type    AS route_type,
                 r.route_color   AS route_color,
                 r.route_text_color AS route_text_color
            FROM stop_times AS st
            JOIN trips  AS t ON t.trip_id = st.trip_id
            JOIN routes AS r ON r.route_id = t.route_id
           WHERE st.stop_id = ?
             AND st.departure_seconds IS NOT NULL
             AND st.departure_seconds >= ?
             AND (st.pickup_type IS NULL OR st.pickup_type = 0)
             ${serviceClause}
           ORDER BY st.departure_seconds ASC
           LIMIT ?;`,
    params: [options.stopId, options.minSeconds, ...(serviceIds ?? []), options.limit],
  };
}

/**
 * Service ids running on a `YYYYMMDD` date: the weekly pattern from `calendar`, minus removals,
 * plus one-off additions from `calendar_dates`.
 *
 * `weekday` is interpolated as a column name, so it is restricted to the GTFS column whitelist —
 * it can never come from user input.
 */
export function buildActiveServiceIdsQuery(date: string, weekday: GtfsWeekdayColumn): BuiltQuery {
  if (!GTFS_WEEKDAY_COLUMNS.includes(weekday)) {
    throw new RangeError(`Unsupported GTFS weekday column: ${weekday}`);
  }
  assertIdentifier(weekday);

  return {
    sql: `SELECT service_id
            FROM calendar
           WHERE start_date <= ?
             AND end_date >= ?
             AND ${weekday} = 1
             AND service_id NOT IN (
                   SELECT service_id FROM calendar_dates
                    WHERE date = ? AND exception_type = 2
                 )
           UNION
          SELECT service_id
            FROM calendar_dates
           WHERE date = ?
             AND exception_type = 1;`,
    params: [date, date, date, date],
  };
}

/** Counts rows per GTFS table — used by the sync screen and by the verification harness. */
export function buildTableCountsQuery(): BuiltQuery {
  const selects = SYNCABLE_TABLES.map(
    (table) => `(SELECT COUNT(*) FROM ${assertIdentifier(table)}) AS ${table}`,
  );
  return { sql: `SELECT ${selects.join(', ')};`, params: [] };
}
