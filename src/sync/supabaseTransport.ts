/**
 * Supabase (PostgREST) transport — the only file that knows how the backend speaks.
 *
 * The contract with the server (see `supabase/migrations/0001_gtfs_sync.sql`):
 *   • every feed table exposes `sync_version BIGINT` fed by one shared sequence, set by a trigger on
 *     every insert/update/soft-delete. One sequence across tables means one global total order, so a
 *     single integer cursor is sufficient — no (updated_at, id) tuple comparison, no ties, no
 *     "same timestamp" rows silently skipped;
 *   • deletes are soft (`deleted_at timestamptz`) and travel as tombstones through the same stream;
 *   • the client only ever SELECTs.
 *
 * Why keyset pagination on `sync_version` instead of `.range()` offsets: offsets re-scan and can
 * both duplicate and skip rows while an ETL job is writing. A strict `> cursor` never does either.
 */

import type { SupabaseClient } from '@supabase/supabase-js';

import type { Database, GtfsRecordByTable, SupabaseGtfsTable } from '../api/database.types';
import { SUPABASE_TABLE_BY_ENTITY } from '../api/database.types';
import type { SqlBindValue, SyncableTable } from '../db/types';
import { SyncError } from '../utils/errors';
import { createLogger } from '../utils/logger';
import type { PageRequest, SyncPage, SyncRow, SyncTransport } from './types';
import {
  mapCalendarDateRecord,
  mapCalendarRecord,
  mapRouteRecord,
  mapStopRecord,
  mapStopTimeRecord,
  mapTripRecord,
} from './mappers';

const log = createLogger('sync:supabase');

/** Shape PostgREST returns for `select('*')`, keyed by table. */
function mapRow(entity: SyncableTable, record: GtfsRecordByTable[SupabaseGtfsTable]): SyncRow {
  switch (entity) {
    case 'routes':
      return mapRouteRecord(record as GtfsRecordByTable['gtfs_routes']);
    case 'stops':
      return mapStopRecord(record as GtfsRecordByTable['gtfs_stops']);
    case 'trips':
      return mapTripRecord(record as GtfsRecordByTable['gtfs_trips']);
    case 'stop_times':
      return mapStopTimeRecord(record as GtfsRecordByTable['gtfs_stop_times']);
    case 'calendar':
      return mapCalendarRecord(record as GtfsRecordByTable['gtfs_calendar']);
    case 'calendar_dates':
      return mapCalendarDateRecord(record as GtfsRecordByTable['gtfs_calendar_dates']);
    default: {
      // Exhaustiveness guard: adding a table to SYNCABLE_TABLES without a mapper fails to compile.
      const unreachable: never = entity;
      throw new SyncError(`No mapper for entity ${String(unreachable)}`, {
        code: 'SYNC_PAYLOAD_INVALID',
        retryable: false,
      });
    }
  }
}

export interface SupabaseTransportOptions {
  readonly client: SupabaseClient<Database>;
  /** Overrides `sync_log.source`. */
  readonly source?: string;
}

export function createSupabaseTransport(options: SupabaseTransportOptions): SyncTransport {
  const { client } = options;

  return {
    source: options.source ?? 'supabase',

    async fetchPage(request: PageRequest): Promise<SyncPage> {
      const table = SUPABASE_TABLE_BY_ENTITY[request.entity];

      let query = client
        .from(table)
        .select('*')
        .gt('sync_version', request.cursor)
        .order('sync_version', { ascending: true })
        .limit(request.limit);

      // supabase-js accepts an AbortSignal through `.abortSignal()` in v2.6+; guard for older builds.
      if (request.signal && typeof query.abortSignal === 'function') {
        query = query.abortSignal(request.signal);
      }

      const { data, error } = await query;

      if (error !== null) throw toSyncError(error, request);

      const records = (data ?? []) as GtfsRecordByTable[SupabaseGtfsTable][];
      const rows: SyncRow[] = [];

      for (const record of records) {
        try {
          rows.push(mapRow(request.entity, record));
        } catch (mappingError) {
          // One malformed row must not fail the whole page: log it, skip it, keep the cursor
          // moving. (It will be re-delivered only if the server bumps its sync_version.)
          log.error('skipping an unmappable row', mappingError, {
            entity: request.entity,
            recordId:
              (record as { id?: unknown; route_id?: unknown; stop_id?: unknown }).stop_id ?? null,
          });
        }
      }

      const nextCursor = rows.reduce<number | null>((highest, row) => {
        const version = row.sync_version;
        if (typeof version !== 'number' || !Number.isFinite(version)) return highest;
        return highest === null || version > highest ? version : highest;
      }, null);

      return {
        entity: request.entity,
        rows,
        nextCursor,
        // A short page means the server has nothing more past this cursor. (`nextCursor === null`
        // with a full page would mean unreadable rows; the engine treats that as an error.)
        hasMore: rows.length >= request.limit && nextCursor !== null,
        serverTime: Date.now(),
      };
    },
  };
}

interface PostgrestErrorLike {
  message?: string;
  code?: string;
  details?: string | null;
  hint?: string | null;
}

/**
 * Maps a PostgREST/GoTrue failure onto the retryable/permanent taxonomy.
 *
 * Retryable: 5xx, 408, 429, and anything that looks like a transport failure.
 * Permanent: 401/403 (bad or missing key), 400/404 (unknown table — a deploy mismatch).
 */
function toSyncError(error: PostgrestErrorLike, request: PageRequest): SyncError {
  const message = error.message ?? 'Supabase request failed';
  const code = error.code ?? '';
  const status = extractStatus(code, error.details ?? '', error.hint ?? '');

  const context = { entity: request.entity, cursor: request.cursor, code, status: status ?? null };

  if (status === 401 || status === 403 || code === 'PGRST301' || code === 'PGRST302') {
    return new SyncError(
      `${message} — check EXPO_PUBLIC_SUPABASE_ANON_KEY and the RLS policies on the gtfs_* tables.`,
      {
        code: 'SYNC_UNAUTHORIZED',
        entity: request.entity,
        phase: 'fetch',
        retryable: false,
        context,
      },
    );
  }

  if (status === 429) {
    return new SyncError(`${message} — rate limited by Supabase.`, {
      code: 'SYNC_RATE_LIMITED',
      entity: request.entity,
      phase: 'fetch',
      retryable: true,
      context,
    });
  }

  if (status !== null && status >= 500) {
    return new SyncError(`${message} — Supabase returned ${status}.`, {
      code: 'SYNC_SERVER',
      entity: request.entity,
      phase: 'fetch',
      retryable: true,
      context,
    });
  }

  if (status === 400 || status === 404 || code.startsWith('42')) {
    return new SyncError(
      `${message} — the local schema and the deployed one disagree. Run the SQL in supabase/migrations/.`,
      { code: 'SYNC_SERVER', entity: request.entity, phase: 'fetch', retryable: false, context },
    );
  }

  // A missing status usually means the request never reached the server (DNS, offline, TLS).
  return new SyncError(message, {
    code: 'SYNC_NETWORK',
    entity: request.entity,
    phase: 'fetch',
    retryable: true,
    context,
  });
}

function extractStatus(code: string, details: string, hint: string): number | null {
  const haystack = `${code} ${details} ${hint}`;
  const match = /(?:^|\D)(4\d{2}|5\d{2})(?:\D|$)/.exec(haystack);
  if (match?.[1] !== undefined) return Number(match[1]);
  return null;
}

/** Exposed for the sync screen: how stale is the newest row on the server? */
export function latestSyncVersionFrom(page: SyncPage): number {
  return page.nextCursor ?? 0;
}

export type { SqlBindValue };
