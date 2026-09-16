/**
 * Storage-layer types.
 *
 * `SqlExecutor` is the seam that keeps this app's data layer testable: `expo-sqlite`'s
 * `SQLiteDatabase` satisfies it on device, and `node:sqlite` satisfies it in the Node verification
 * harness (scripts/verify-db.ts). Repositories therefore never import a native module, which means
 * every query in src/data can be executed against a real SQLite engine in CI.
 *
 * Note the method-shorthand syntax: it makes the interface *bivariant* in its parameters, so
 * expo-sqlite's stricter overloads (which accept `SQLiteBindValue[]`) remain assignable even though
 * this file deliberately depends on nothing from Expo.
 */

export type SqlBindValue = string | number | null | boolean | Uint8Array;
export type SqlBindParams = SqlBindValue[] | Record<string, SqlBindValue>;

export interface SqlRunResult {
  readonly changes: number;
  readonly lastInsertRowId: number;
}

/** A compiled statement that can be executed repeatedly with different bind values. */
export interface SqlPreparedStatement {
  executeAsync(params: SqlBindParams): Promise<void>;
  finalizeAsync(): Promise<void>;
}

export interface SqlExecutor {
  execAsync(source: string): Promise<void>;
  runAsync(source: string, params?: SqlBindParams): Promise<SqlRunResult>;
  getAllAsync<T>(source: string, params?: SqlBindParams): Promise<T[]>;
  getFirstAsync<T>(source: string, params?: SqlBindParams): Promise<T | null>;
  /**
   * Optional capability. When present, the sync engine compiles its UPSERT **once per page**
   * instead of once per row — on a 500 000-row `stop_times` backfill that removes 500 000
   * `sqlite3_prepare_v2` compiles from the critical path.
   */
  prepareAsync?(source: string): Promise<SqlPreparedStatement>;
}

/** Tables populated by the GTFS sync. Order matters: parents before children (FK safety). */
export const SYNCABLE_TABLES = [
  'routes',
  'stops',
  'trips',
  'stop_times',
  'calendar',
  'calendar_dates',
] as const;

export type SyncableTable = (typeof SYNCABLE_TABLES)[number];

/** Columns every synced row carries to make incremental sync possible. */
export interface SyncedRowMeta {
  /** Server-side last-modified time, ms since epoch. Diagnostics + conflict visibility. */
  readonly updated_at: number;
  /** Monotonic server sequence. This — not `updated_at` — is the sync cursor. */
  readonly sync_version: number;
}

export interface RouteRow extends SyncedRowMeta {
  readonly route_id: string;
  readonly route_short_name: string | null;
  readonly route_long_name: string | null;
  readonly route_type: number | null;
  readonly route_color: string | null;
  readonly route_text_color: string | null;
}

export interface StopRow extends SyncedRowMeta {
  readonly stop_id: string;
  readonly stop_name: string | null;
  readonly stop_code: string | null;
  readonly stop_lat: number;
  readonly stop_lon: number;
  /** GTFS `location_type`: 0/null = boardable stop or platform. */
  readonly location_type: number | null;
  readonly parent_station: string | null;
}

export interface TripRow extends SyncedRowMeta {
  readonly trip_id: string;
  readonly route_id: string;
  readonly service_id: string;
  readonly trip_headsign: string | null;
  readonly direction_id: number | null;
}

export interface StopTimeRow extends SyncedRowMeta {
  readonly trip_id: string;
  readonly stop_id: string;
  readonly stop_sequence: number;
  readonly arrival_time: string | null;
  readonly departure_time: string | null;
  /** Derived from `departure_time` at write time; see utils/gtfsTime.ts. */
  readonly arrival_seconds: number | null;
  readonly departure_seconds: number | null;
  /** GTFS `pickup_type`; 1 = riders cannot board here. */
  readonly pickup_type: number | null;
}

export interface CalendarRow extends SyncedRowMeta {
  readonly service_id: string;
  readonly monday: number;
  readonly tuesday: number;
  readonly wednesday: number;
  readonly thursday: number;
  readonly friday: number;
  readonly saturday: number;
  readonly sunday: number;
  /** `YYYYMMDD` */
  readonly start_date: string;
  /** `YYYYMMDD` */
  readonly end_date: string;
}

export interface CalendarDateRow extends SyncedRowMeta {
  readonly service_id: string;
  /** `YYYYMMDD` */
  readonly date: string;
  /** 1 = service added on this date, 2 = service removed. */
  readonly exception_type: number;
}

/** Row shape per synced table. Used by the sync engine to type its column lists. */
export interface SyncedRowMap {
  routes: RouteRow;
  stops: StopRow;
  trips: TripRow;
  stop_times: StopTimeRow;
  calendar: CalendarRow;
  calendar_dates: CalendarDateRow;
}

export interface SyncStateRow {
  readonly entity: string;
  readonly cursor: number;
  readonly rows_synced: number;
  readonly last_synced_at: number | null;
  readonly last_error: string | null;
}

export interface FavoriteStopRow {
  readonly stop_id: string;
  readonly nickname: string | null;
  readonly sort_order: number;
  readonly created_at: number;
}

export interface StopAlarmRow {
  readonly alarm_id: string;
  readonly stop_id: string;
  readonly route_id: string | null;
  readonly label: string;
  readonly radius_meters: number;
  readonly lead_time_minutes: number;
  readonly enabled: number;
  readonly geofence_identifier: string;
  readonly created_at: number;
  readonly updated_at: number;
  readonly last_triggered_at: number | null;
  readonly trigger_count: number;
}

export type SyncLogStatus = 'running' | 'success' | 'partial' | 'failed';

export interface SyncLogRow {
  readonly id: number;
  readonly started_at: number;
  readonly finished_at: number | null;
  readonly status: SyncLogStatus;
  readonly source: string;
  readonly entities_json: string | null;
  readonly rows_written: number;
  readonly rows_deleted: number;
  readonly error_code: string | null;
  readonly error_message: string | null;
}
