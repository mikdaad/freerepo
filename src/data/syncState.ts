/**
 * Sync bookkeeping: cursors, run logs, and the maintenance operations the settings screen needs.
 *
 * The cursor is the *only* thing that decides how much data a device pulls next time, so it is
 * written inside the same transaction as the rows it accounts for (see sync/engine.ts). Never
 * advance a cursor outside of that transaction.
 */

import { buildTableCountsQuery } from '../db/sql';
import {
  SYNCABLE_TABLES,
  type SqlExecutor,
  type SyncLogRow,
  type SyncLogStatus,
  type SyncStateRow,
  type SyncableTable,
} from '../db/types';
import { createLogger } from '../utils/logger';

const log = createLogger('data:sync-state');

/** Reads the high-water mark for one entity. Missing rows read as 0 (full backfill). */
export async function readSyncCursor(db: SqlExecutor, entity: SyncableTable): Promise<number> {
  const row = await db.getFirstAsync<{ cursor: number }>(
    'SELECT cursor FROM sync_state WHERE entity = ?;',
    [entity],
  );
  return row?.cursor ?? 0;
}

export async function readAllSyncState(db: SqlExecutor): Promise<SyncStateRow[]> {
  return db.getAllAsync<SyncStateRow>(
    `SELECT entity, cursor, rows_synced, last_synced_at, last_error
       FROM sync_state
      ORDER BY entity ASC;`,
  );
}

export interface EntityProgress {
  readonly cursor: number;
  readonly rowsSynced: number;
  readonly lastError?: string | null;
}

/**
 * Records progress for one entity. **Call inside the sync transaction** — a cursor that outlives
 * the rows it describes means those rows are never fetched again.
 */
export async function commitEntityProgress(
  db: SqlExecutor,
  entity: SyncableTable,
  progress: EntityProgress,
): Promise<void> {
  await db.runAsync(
    `INSERT INTO sync_state (entity, cursor, rows_synced, last_synced_at, last_error)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (entity) DO UPDATE SET
       cursor         = excluded.cursor,
       rows_synced    = excluded.rows_synced,
       last_synced_at = excluded.last_synced_at,
       last_error     = excluded.last_error;`,
    [entity, progress.cursor, progress.rowsSynced, Date.now(), progress.lastError ?? null],
  );
}

/** Clears cursors so the next pass re-downloads everything ("Reset local data"). */
export async function resetSyncCursors(db: SqlExecutor): Promise<void> {
  await db.runAsync('UPDATE sync_state SET cursor = 0, rows_synced = 0, last_error = NULL;');
  log.info('sync cursors reset — next pass will be a full backfill');
}

export interface PurgeResult {
  readonly deletedRows: number;
  /**
   * Alarms removed because the stop they pointed at was purged.
   *
   * Not an accident and not avoidable: a geofenced alarm is armed from the *stop's* coordinates, so
   * an alarm whose stop is gone can never fire. The settings screen must warn the commuter with this
   * number before they confirm.
   */
  readonly alarmsRemoved: number;
  readonly favoritesRemoved: number;
}

/**
 * Deletes every locally stored GTFS row and resets the sync cursors, so the next pass is a full
 * backfill. Used by "Reset local data" when a device is stuck on a bad feed.
 *
 * User data (alarms, favourites) references `stops` with `ON DELETE CASCADE`, so entries pointing at
 * purged stops disappear with them — see `PurgeResult`.
 */
export async function purgeGtfsData(db: SqlExecutor): Promise<PurgeResult> {
  const alarms = await db.getFirstAsync<{ count: number }>(
    'SELECT COUNT(*) AS count FROM stop_alarms;',
  );
  const favorites = await db.getFirstAsync<{ count: number }>(
    'SELECT COUNT(*) AS count FROM favorite_stops;',
  );

  let deletedRows = 0;

  await db.execAsync('BEGIN IMMEDIATE;');
  try {
    // Children first: explicit ordering keeps this correct even with foreign_keys = OFF.
    for (const table of ['stop_times', 'trips', 'calendar_dates', 'calendar'] as const) {
      const result = await db.runAsync(`DELETE FROM ${table};`);
      deletedRows += result.changes;
    }
    for (const table of ['routes', 'stops'] as const) {
      const result = await db.runAsync(`DELETE FROM ${table};`);
      deletedRows += result.changes;
    }
    await resetSyncCursors(db);
    await db.execAsync('COMMIT;');
  } catch (error) {
    await db.execAsync('ROLLBACK;');
    throw error;
  }

  log.warn('all local GTFS data purged', { deletedRows });

  return {
    deletedRows,
    alarmsRemoved: alarms?.count ?? 0,
    favoritesRemoved: favorites?.count ?? 0,
  };
}

/** How much user data a purge would destroy — for the confirmation dialog. */
export async function countUserData(
  db: SqlExecutor,
): Promise<{ alarms: number; favorites: number }> {
  const row = await db.getFirstAsync<{ alarms: number; favorites: number }>(
    `SELECT (SELECT COUNT(*) FROM stop_alarms)    AS alarms,
            (SELECT COUNT(*) FROM favorite_stops) AS favorites;`,
  );
  return { alarms: row?.alarms ?? 0, favorites: row?.favorites ?? 0 };
}

export interface TableCounts {
  readonly routes: number;
  readonly stops: number;
  readonly trips: number;
  readonly stop_times: number;
  readonly calendar: number;
  readonly calendar_dates: number;
  readonly total: number;
}

/** Row counts per GTFS table — the sync screen's "do I have data?" panel. */
export async function getTableCounts(db: SqlExecutor): Promise<TableCounts> {
  const query = buildTableCountsQuery();
  const row = await db.getFirstAsync<Record<SyncableTable, number>>(query.sql, query.params);

  const counts = {
    routes: row?.routes ?? 0,
    stops: row?.stops ?? 0,
    trips: row?.trips ?? 0,
    stop_times: row?.stop_times ?? 0,
    calendar: row?.calendar ?? 0,
    calendar_dates: row?.calendar_dates ?? 0,
  };

  return {
    ...counts,
    total: SYNCABLE_TABLES.reduce((sum, table) => sum + counts[table], 0),
  };
}

export interface DatabaseFootprint {
  readonly pageCount: number;
  readonly pageSize: number;
  readonly bytes: number;
}

/** On-disk size of the database (WAL excluded — this is the main file). */
export async function getDatabaseFootprint(db: SqlExecutor): Promise<DatabaseFootprint> {
  const pageCount = await db.getFirstAsync<{ page_count: number }>('PRAGMA page_count;');
  const pageSize = await db.getFirstAsync<{ page_size: number }>('PRAGMA page_size;');
  const count = pageCount?.page_count ?? 0;
  const size = pageSize?.page_size ?? 0;
  return { pageCount: count, pageSize: size, bytes: count * size };
}

/** SQLite's own fragmentation metric; a high value after a large sync means "run VACUUM". */
export async function getFreelistRatio(db: SqlExecutor): Promise<number> {
  // Two plain PRAGMA reads rather than the `pragma_*()` table-valued functions, which are not
  // compiled into every SQLite distribution.
  const freelist = await db.getFirstAsync<{ freelist_count: number }>('PRAGMA freelist_count;');
  const pages = await db.getFirstAsync<{ page_count: number }>('PRAGMA page_count;');
  const pageCount = pages?.page_count ?? 0;
  if (pageCount === 0) return 0;
  return (freelist?.freelist_count ?? 0) / pageCount;
}

/**
 * Reclaims space after a large re-sync. Expensive (rewrites the file) and blocking, so it is only
 * ever triggered manually from the settings screen.
 */
export async function vacuum(db: SqlExecutor): Promise<void> {
  // VACUUM cannot run inside a transaction — it is its own statement.
  await db.execAsync('VACUUM;');
}

// ---------------------------------------------------------------------------------------------
// Run log
// ---------------------------------------------------------------------------------------------

export async function beginSyncLog(db: SqlExecutor, source: string): Promise<number> {
  const result = await db.runAsync(
    `INSERT INTO sync_log (started_at, status, source)
     VALUES (?, 'running', ?);`,
    [Date.now(), source],
  );
  return result.lastInsertRowId;
}

export interface SyncLogCompletion {
  readonly status: Exclude<SyncLogStatus, 'running'>;
  readonly entities: Record<string, unknown> | null;
  readonly rowsWritten: number;
  readonly rowsDeleted: number;
  readonly errorCode?: string | null;
  readonly errorMessage?: string | null;
}

export async function completeSyncLog(
  db: SqlExecutor,
  logId: number,
  completion: SyncLogCompletion,
): Promise<void> {
  await db.runAsync(
    `UPDATE sync_log
        SET finished_at   = ?,
            status        = ?,
            entities_json = ?,
            rows_written  = ?,
            rows_deleted  = ?,
            error_code    = ?,
            error_message = ?
      WHERE id = ?;`,
    [
      Date.now(),
      completion.status,
      completion.entities === null ? null : JSON.stringify(completion.entities),
      completion.rowsWritten,
      completion.rowsDeleted,
      completion.errorCode ?? null,
      completion.errorMessage ?? null,
      logId,
    ],
  );
}

export async function listRecentSyncLogs(db: SqlExecutor, limit = 10): Promise<SyncLogRow[]> {
  return db.getAllAsync<SyncLogRow>(
    `SELECT id, started_at, finished_at, status, source, entities_json,
            rows_written, rows_deleted, error_code, error_message
       FROM sync_log
      ORDER BY started_at DESC
      LIMIT ?;`,
    [limit],
  );
}

/** Marks runs abandoned by a process kill (no `finished_at`) as failed on next boot. */
export async function reconcileStaleSyncLogs(db: SqlExecutor): Promise<number> {
  const result = await db.runAsync(
    `UPDATE sync_log
        SET status = 'failed',
            finished_at = ?,
            error_code = 'SYNC_ABORTED',
            error_message = COALESCE(error_message, 'Interrupted — the app was closed mid-sync.')
      WHERE status = 'running';`,
    [Date.now()],
  );
  return result.changes;
}
