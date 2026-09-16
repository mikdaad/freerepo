/**
 * The sync engine.
 *
 * Responsibilities, in order of how badly they break things if wrong:
 *
 * 1. **Atomicity per page.** Rows and the cursor that accounts for them are written in one
 *    transaction. A crash mid-backfill therefore resumes exactly where it stopped instead of
 *    silently skipping a page forever.
 * 2. **Idempotence.** Every write is an UPSERT keyed on the feed's natural key, so re-running any
 *    pass (or replaying a page after a retry) converges to the same state.
 * 3. **Bounded work.** Page size, page-count ceiling, and an abort signal keep a background wake-up
 *    inside the ~30 s budget Android gives a `TaskManager` job — a sync must never be the reason a
 *    wake-up alarm is late.
 * 4. **Honest failure.** Retryable errors (network, 429, 5xx) back off exponentially; permanent ones
 *    (auth, schema) fail fast and are recorded, so the UI can say *why* the board may be stale.
 *
 * Ordering: parents before children (`routes`, `stops` → `trips` → `stop_times`) because
 * `PRAGMA foreign_keys = ON` means a stop_time whose trip has not landed yet is rejected outright.
 */

import { config } from '../config/env';
import {
  buildDeleteByKeyPlan,
  buildUpsertPlan,
  rowToBindValues,
  SYNC_TABLE_KEY_COLUMNS,
  type UpsertPlan,
} from '../db/sql';
import { SYNCABLE_TABLES, type SqlExecutor, type SyncableTable } from '../db/types';
import { AppError, getErrorMessage, SyncError, type AppErrorCode } from '../utils/errors';
import { createLogger } from '../utils/logger';
import {
  beginSyncLog,
  commitEntityProgress,
  completeSyncLog,
  readSyncCursor,
  reconcileStaleSyncLogs,
} from '../data/syncState';
import type {
  SyncEntityResult,
  SyncOptions,
  SyncPage,
  SyncProgressEvent,
  SyncResult,
  SyncRow,
  SyncTransport,
} from './types';

const log = createLogger('sync:engine');

/** How many rows are written per prepared-statement flush. */
const WRITE_CHUNK_SIZE = 250;

const DEFAULT_ENTITIES: readonly SyncableTable[] = SYNCABLE_TABLES;

const BACKOFF_BASE_MS = 750;
const BACKOFF_MAX_MS = 8_000;

/**
 * In-process mutex. Two entry points can legitimately race: the user taps "Sync now" while a
 * `TaskManager` wake-up is already mid-pass. Without this, both would write and both would advance
 * the cursor.
 */
let inFlight: Promise<SyncResult> | null = null;

export function isSyncInProgress(): boolean {
  return inFlight !== null;
}

/**
 * Syncs the local database from a transport.
 *
 * @throws {SyncError} when the pass fails and `onConcurrent: 'reject'` finds another pass running,
 *         or when `abortOnEntityFailure` is set and an entity fails.
 */
export async function syncGtfs(
  db: SqlExecutor,
  transport: SyncTransport,
  options: SyncOptions = {},
): Promise<SyncResult> {
  if (inFlight !== null) {
    if (options.onConcurrent === 'reject') {
      throw new SyncError('A sync pass is already running.', {
        code: 'SYNC_IN_PROGRESS',
        retryable: true,
        context: { source: transport.source },
      });
    }
    log.info('joining the in-flight sync pass', { source: transport.source });
    const result = await inFlight;
    return { ...result, joinedExistingRun: true };
  }

  const run = runSyncPass(db, transport, options).finally(() => {
    inFlight = null;
  });
  inFlight = run;
  return run;
}

async function runSyncPass(
  db: SqlExecutor,
  transport: SyncTransport,
  options: SyncOptions,
): Promise<SyncResult> {
  const now = options.now ?? (() => Date.now());
  const pageSize = options.pageSize ?? config.syncPageSize;
  const maxPagesPerEntity = options.maxPagesPerEntity ?? config.syncMaxPagesPerEntity;
  const maxRetries = options.maxRetries ?? config.syncMaxRetries;
  const entities = options.entities ?? DEFAULT_ENTITIES;
  const recordRun = options.recordRun ?? true;
  const startedAt = now();

  const entityResults: SyncEntityResult[] = [];
  let rowsWritten = 0;
  let rowsDeleted = 0;
  let abortError: { code: AppErrorCode; message: string } | null = null;

  let logId: number | null = null;
  if (recordRun) {
    try {
      await reconcileStaleSyncLogs(db);
      logId = await beginSyncLog(db, transport.source);
    } catch (error) {
      // Diagnostics must never block the sync itself.
      log.warn('could not open a sync_log row', { error: getErrorMessage(error) });
    }
  }

  emit(options, {
    phase: 'start',
    entity: entities[0] ?? 'routes',
    rowsWritten,
    rowsDeleted,
    pageIndex: 0,
    cursor: 0,
  });

  for (const entity of entities) {
    if (isAborted(options.signal)) {
      abortError = { code: 'SYNC_ABORTED', message: 'Sync cancelled.' };
      break;
    }

    const entityStartedAt = now();
    let startCursor = 0;
    let cursor = 0;
    let entityRowsWritten = 0;
    let entityRowsDeleted = 0;
    let pages = 0;
    let entityError: { code: AppErrorCode; message: string } | null = null;

    const upsert = buildUpsertPlan(entity);
    const deleteByKey = buildDeleteByKeyPlan(entity);
    const keyColumns = SYNC_TABLE_KEY_COLUMNS[entity];

    try {
      startCursor = options.fullResync === true ? 0 : await readSyncCursor(db, entity);
      cursor = startCursor;

      emit(options, {
        phase: 'entity-start',
        entity,
        rowsWritten,
        rowsDeleted,
        pageIndex: 0,
        cursor,
      });

      for (;;) {
        if (isAborted(options.signal)) throw abortedError(entity);
        if (pages >= maxPagesPerEntity) {
          throw new SyncError(
            `Stopped after ${maxPagesPerEntity} pages for "${entity}" — the page ceiling was reached.`,
            {
              code: 'SYNC_SERVER',
              entity,
              phase: 'fetch',
              retryable: false,
              context: { cursor, pageSize },
            },
          );
        }

        const page = await withRetry(
          () =>
            transport.fetchPage({
              entity,
              cursor,
              limit: pageSize,
              ...(options.signal ? { signal: options.signal } : {}),
            }),
          { maxRetries, entity, phase: 'fetch', options, now },
        );

        if (page.entity !== entity) {
          throw new SyncError(
            `Transport returned a page for "${page.entity}" while syncing "${entity}".`,
            { code: 'SYNC_PAYLOAD_INVALID', entity, phase: 'fetch' },
          );
        }

        // Even an empty page can advance the cursor (a page of pure tombstones, for example).
        const advanced = await writePage(db, {
          entity,
          page,
          cursor,
          upsertPlan: upsert,
          deletePlan: deleteByKey,
          keyColumns,
          maxRetries,
          options,
          now,
          rowsWrittenSoFar: entityRowsWritten,
          rowsDeletedSoFar: entityRowsDeleted,
        });

        entityRowsWritten += advanced.written;
        entityRowsDeleted += advanced.deleted;
        cursor = advanced.cursor;
        pages += 1;

        log.debug('page committed', {
          entity,
          pages,
          written: advanced.written,
          deleted: advanced.deleted,
          cursor,
        });

        emit(options, {
          phase: 'page',
          entity,
          rowsWritten: rowsWritten + entityRowsWritten,
          rowsDeleted: rowsDeleted + entityRowsDeleted,
          pageIndex: pages,
          cursor,
        });

        if (!page.hasMore) break;

        if (advanced.written === 0 && advanced.deleted === 0 && page.nextCursor === null) {
          // Defensive: a server that claims `hasMore` but never advances the cursor would spin
          // this loop forever.
          throw new SyncError(
            `Transport reported more rows for "${entity}" without advancing the cursor.`,
            { code: 'SYNC_PAYLOAD_INVALID', entity, phase: 'fetch', context: { cursor } },
          );
        }
      }
    } catch (error) {
      const syncError = toSyncError(error, entity);
      entityError = { code: syncError.code, message: syncError.message };
      log.error(`entity "${entity}" failed`, syncError, { entity, cursor });
      try {
        await db.runAsync('UPDATE sync_state SET last_error = ? WHERE entity = ?;', [
          syncError.message,
          entity,
        ]);
      } catch {
        // Non-fatal.
      }
    }

    const entityResult: SyncEntityResult = {
      entity,
      startCursor,
      endCursor: cursor,
      rowsWritten: entityRowsWritten,
      rowsDeleted: entityRowsDeleted,
      pages,
      durationMs: now() - entityStartedAt,
      error: entityError,
    };
    entityResults.push(entityResult);
    rowsWritten += entityRowsWritten;
    rowsDeleted += entityRowsDeleted;

    emit(options, {
      phase: 'entity-complete',
      entity,
      rowsWritten,
      rowsDeleted,
      pageIndex: pages,
      cursor,
    });

    if (entityError !== null && options.abortOnEntityFailure === true) {
      abortError = entityError;
      break;
    }
  }

  const finishedAt = now();
  const failureCount = entityResults.filter((result) => result.error !== null).length;
  const status: SyncResult['status'] =
    abortError !== null
      ? 'failed'
      : failureCount === 0
        ? 'success'
        : failureCount === entityResults.length
          ? 'failed'
          : 'partial';

  const result: SyncResult = {
    source: transport.source,
    joinedExistingRun: false,
    startedAt,
    finishedAt,
    durationMs: finishedAt - startedAt,
    status,
    entities: entityResults,
    rowsWritten,
    rowsDeleted,
    error: abortError,
  };

  if (logId !== null) {
    try {
      await completeSyncLog(db, logId, {
        status,
        entities: Object.fromEntries(
          entityResults.map((entry) => [
            entry.entity,
            { written: entry.rowsWritten, deleted: entry.rowsDeleted, endCursor: entry.endCursor },
          ]),
        ),
        rowsWritten,
        rowsDeleted,
        errorCode: abortError?.code ?? null,
        errorMessage: abortError?.message ?? null,
      });
    } catch (error) {
      log.warn('could not close the sync_log row', { error: getErrorMessage(error) });
    }
  }

  emit(options, {
    phase: 'finish',
    entity: entityResults.at(-1)?.entity ?? 'routes',
    rowsWritten,
    rowsDeleted,
    pageIndex: 0,
    cursor: 0,
  });

  log.info('sync pass finished', {
    status,
    source: transport.source,
    rowsWritten,
    rowsDeleted,
    durationMs: result.durationMs,
  });

  return result;
}

interface WritePageInput {
  readonly entity: SyncableTable;
  readonly page: SyncPage;
  readonly cursor: number;
  readonly upsertPlan: UpsertPlan;
  readonly deletePlan: UpsertPlan;
  readonly keyColumns: readonly string[];
  readonly maxRetries: number;
  readonly options: SyncOptions;
  readonly now: () => number;
  readonly rowsWrittenSoFar: number;
  readonly rowsDeletedSoFar: number;
}

/**
 * Persists one page: tombstones first (so a delete and an insert of the same key in the same page
 * end up inserted), then the upserts, then the cursor — all in one transaction.
 */
async function writePage(
  db: SqlExecutor,
  input: WritePageInput,
): Promise<{ written: number; deleted: number; cursor: number }> {
  const { page, entity, keyColumns } = input;

  const liveRows: SyncRow[] = [];
  const tombstonedRows: SyncRow[] = [];
  for (const row of page.rows) {
    if (isTombstone(row)) tombstonedRows.push(row);
    else liveRows.push(row);
  }

  const nextCursor = page.nextCursor ?? input.cursor;

  await withRetry(
    async () => {
      await db.execAsync('BEGIN IMMEDIATE;');
      try {
        for (const row of tombstonedRows) {
          await db.runAsync(input.deletePlan.sql, rowToBindValues(keyColumns, row));
        }

        await writeRows(db, input.upsertPlan, liveRows);

        await commitEntityProgress(db, entity, {
          cursor: nextCursor,
          rowsSynced: input.rowsWrittenSoFar + liveRows.length,
          lastError: null,
        });

        await db.execAsync('COMMIT;');
      } catch (error) {
        try {
          await db.execAsync('ROLLBACK;');
        } catch {
          // The original error is the one that matters.
        }
        throw error;
      }
    },
    {
      maxRetries: input.maxRetries,
      entity,
      phase: 'write',
      options: input.options,
      now: input.now,
    },
  );

  return { written: liveRows.length, deleted: tombstonedRows.length, cursor: nextCursor };
}

function isTombstone(row: SyncRow): boolean {
  const deletedAt = (row as { deleted_at?: number | null }).deleted_at;
  return typeof deletedAt === 'number' && deletedAt > 0;
}

/**
 * Writes one chunk of rows with a single compiled statement.
 *
 * Falls back to per-row `runAsync` when the executor has no `prepareAsync` (the Node harness, any
 * future non-SQLite backend). `WRITE_CHUNK_SIZE` bounds how long the JS thread is held in one go,
 * which matters because this runs inside a background task's wall-clock budget.
 */
async function writeRows(
  db: SqlExecutor,
  plan: UpsertPlan,
  rows: readonly SyncRow[],
): Promise<void> {
  if (rows.length === 0) return;

  if (typeof db.prepareAsync === 'function') {
    const prepared = await db.prepareAsync(plan.sql);
    try {
      for (let index = 0; index < rows.length; index += WRITE_CHUNK_SIZE) {
        for (const row of rows.slice(index, index + WRITE_CHUNK_SIZE)) {
          await prepared.executeAsync(rowToBindValues(plan.bindColumns, row));
        }
      }
    } finally {
      await prepared.finalizeAsync().catch((error: unknown) => {
        log.warn('failed to finalize the prepared upsert statement', {
          error: getErrorMessage(error),
        });
      });
    }
    return;
  }

  for (let index = 0; index < rows.length; index += WRITE_CHUNK_SIZE) {
    for (const row of rows.slice(index, index + WRITE_CHUNK_SIZE)) {
      await db.runAsync(plan.sql, rowToBindValues(plan.bindColumns, row));
    }
  }
}

interface RetryContext {
  readonly maxRetries: number;
  readonly entity: SyncableTable;
  readonly phase: 'fetch' | 'write' | 'commit';
  readonly options: SyncOptions;
  readonly now: () => number;
}

/**
 * Retries a step with exponential backoff + jitter.
 *
 * Only `AppError.retryable` failures are retried. Everything else — an auth failure, a malformed
 * payload, a constraint violation — is deterministic, and retrying it only delays the error the
 * user needs to see.
 */
async function withRetry<T>(work: () => Promise<T>, context: RetryContext): Promise<T> {
  let attempt = 0;

  for (;;) {
    try {
      return await work();
    } catch (error) {
      const syncError = toSyncError(error, context.entity, context.phase);
      const canRetry = syncError.retryable && attempt < context.maxRetries;

      if (!canRetry) throw syncError;

      attempt += 1;
      const delay = Math.min(
        BACKOFF_MAX_MS,
        BACKOFF_BASE_MS * 2 ** (attempt - 1) + Math.random() * 250,
      );

      log.warn(`retrying after failure (attempt ${attempt}/${context.maxRetries})`, {
        entity: context.entity,
        phase: context.phase,
        code: syncError.code,
        delayMs: Math.round(delay),
        message: syncError.message,
      });

      emit(context.options, {
        phase: 'retry',
        entity: context.entity,
        rowsWritten: 0,
        rowsDeleted: 0,
        pageIndex: 0,
        cursor: 0,
        errorMessage: syncError.message,
        attempt,
      });

      await sleep(delay, context.options.signal);
    }
  }
}

/**
 * Reads `signal.aborted` at call time.
 *
 * Deliberately a function rather than an inline `=== true` test: TypeScript narrows
 * `options.signal?.aborted` to `false` after the first such check in a scope, which would make every
 * later check in the same loop look like dead code — even though the flag really can flip between
 * iterations (the user navigating away mid-sync, or an OS timeout).
 */
function isAborted(signal?: AbortSignal): boolean {
  return signal?.aborted === true;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (isAborted(signal)) {
      reject(new SyncError('Sync cancelled.', { code: 'SYNC_ABORTED', retryable: false }));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    function onAbort(): void {
      clearTimeout(timer);
      reject(new SyncError('Sync cancelled.', { code: 'SYNC_ABORTED', retryable: false }));
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

function abortedError(entity: SyncableTable): SyncError {
  return new SyncError('Sync cancelled.', { code: 'SYNC_ABORTED', entity, retryable: false });
}

/** Normalises anything thrown inside the engine into a `SyncError`. */
export function toSyncError(
  error: unknown,
  entity: SyncableTable,
  phase?: 'fetch' | 'write' | 'commit',
): SyncError {
  if (error instanceof SyncError) return error;
  if (error instanceof AppError) {
    return new SyncError(error.message, {
      code: error.code,
      cause: error,
      entity,
      retryable: error.retryable,
      context: error.context,
      ...(phase ? { phase } : {}),
    });
  }
  // Unknown failures default to *retryable* — a thrown string from a transport is more often a
  // transient socket error than a permanent one, and one wasted retry is cheaper than a stale board.
  return new SyncError(getErrorMessage(error), {
    code: 'SYNC_NETWORK',
    entity,
    retryable: true,
    cause: error,
    ...(phase ? { phase } : {}),
  });
}

function emit(options: SyncOptions, event: SyncProgressEvent): void {
  try {
    options.onProgress?.(event);
  } catch (error) {
    // A misbehaving listener must never take down a sync.
    log.warn('progress listener threw', { error: getErrorMessage(error) });
  }
}
