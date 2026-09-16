/**
 * Sync contracts.
 *
 * The engine never talks to Supabase directly — it talks to a `SyncTransport`. That inversion buys
 * three things at once:
 *   • the whole pipeline is testable against a fake feed (scripts/verify-db.ts) and against the
 *     on-device mock source, with no network and no credentials;
 *   • a future GTFS-Realtime or GTFS-ZIP importer is a new transport, not a rewrite;
 *   • Supabase specifics (PostgREST paging, error codes, ISO timestamps) stay in one file.
 */

import type { AppErrorCode } from '../utils/errors';
import type { SyncedRowMap, SyncableTable } from '../db/types';

/**
 * A row as it arrives from the backend: the entity's columns plus soft-delete metadata.
 *
 * Deletes travel as tombstones rather than as a separate "ids deleted" endpoint so that a single
 * ordered cursor delivers inserts, updates *and* deletes in exactly one total order. Miss a page
 * and you retry it; you can never miss a delete.
 */
export type SyncRow = SyncedRowMap[SyncableTable] & { readonly deleted_at?: number | null };

export interface PageRequest {
  readonly entity: SyncableTable;
  /** Exclusive lower bound on `sync_version`. `0` means "from the beginning". */
  readonly cursor: number;
  readonly limit: number;
  /** Aborts the underlying HTTP request when the app backgrounds or the user cancels. */
  readonly signal?: AbortSignal;
}

export interface SyncPage {
  readonly entity: SyncableTable;
  readonly rows: readonly SyncRow[];
  /**
   * Cursor to resume from = highest `sync_version` observed in this page.
   * `null` when the page was empty (nothing to advance to).
   */
  readonly nextCursor: number | null;
  /** True when the server has more rows past this page. */
  readonly hasMore: boolean;
  /** Server clock at response time, ms since epoch. Used to warn about device clock skew. */
  readonly serverTime?: number;
}

export interface SyncTransport {
  /** Identifies the source in `sync_log.source` and in the UI. */
  readonly source: string;
  fetchPage(request: PageRequest): Promise<SyncPage>;
}

export type SyncPhase = 'start' | 'entity-start' | 'page' | 'entity-complete' | 'finish' | 'retry';

export interface SyncProgressEvent {
  readonly phase: SyncPhase;
  readonly entity: SyncableTable;
  /** Cumulative for the whole pass. */
  readonly rowsWritten: number;
  readonly rowsDeleted: number;
  readonly pageIndex: number;
  readonly cursor: number;
  /** Populated on `retry`. */
  readonly errorMessage?: string;
  readonly attempt?: number;
}

export type SyncProgressListener = (event: SyncProgressEvent) => void;

export interface SyncEntityResult {
  readonly entity: SyncableTable;
  readonly startCursor: number;
  readonly endCursor: number;
  readonly rowsWritten: number;
  readonly rowsDeleted: number;
  readonly pages: number;
  readonly durationMs: number;
  /** Per-entity failure. The pass continues with the next entity unless `abortOnEntityFailure`. */
  readonly error: { readonly code: AppErrorCode; readonly message: string } | null;
}

export type SyncRunStatus = 'success' | 'partial' | 'failed';

export interface SyncResult {
  readonly source: string;
  /** True when the run was joined to an already-running pass rather than started fresh. */
  readonly joinedExistingRun: boolean;
  readonly startedAt: number;
  readonly finishedAt: number;
  readonly durationMs: number;
  readonly status: SyncRunStatus;
  readonly entities: readonly SyncEntityResult[];
  readonly rowsWritten: number;
  readonly rowsDeleted: number;
  /** Set when the pass aborted before finishing every entity. */
  readonly error: { readonly code: AppErrorCode; readonly message: string } | null;
}

export interface SyncOptions {
  /** Subset to sync. Defaults to every entity, in dependency order. */
  readonly entities?: readonly SyncableTable[];
  /** Rows per page. Defaults to `config.syncPageSize`. */
  readonly pageSize?: number;
  /** Runaway guard per entity. Defaults to `config.syncMaxPagesPerEntity`. */
  readonly maxPagesPerEntity?: number;
  /** Retries for retryable failures. Defaults to `config.syncMaxRetries`. */
  readonly maxRetries?: number;
  readonly signal?: AbortSignal;
  readonly onProgress?: SyncProgressListener;
  /** Ignore stored cursors and re-download everything. */
  readonly fullResync?: boolean;
  /** Write `sync_log` rows. Default true. */
  readonly recordRun?: boolean;
  /** Stop the whole pass on the first entity failure (used by the "sync now" button). */
  readonly abortOnEntityFailure?: boolean;
  /** What to do when a pass is already running. Default `join`. */
  readonly onConcurrent?: 'join' | 'reject';
  /** Injectable clock, for deterministic tests. */
  readonly now?: () => number;
}

/** Extracts the composite primary key values of a row, in `SYNC_TABLE_KEY_COLUMNS` order. */
export interface KeyExtractor {
  (row: SyncRow): (string | number)[];
}
