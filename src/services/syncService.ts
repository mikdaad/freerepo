/**
 * The app-facing sync service.
 *
 * Everything above this line is source-agnostic: the engine cannot tell whether it is talking to
 * Supabase or to the in-process mock feed. This module is where that decision is made, so no screen
 * ever has to know which mode the build is in.
 */

import type { SqlExecutor } from '../db/types';
import { config, isRemoteSyncConfigured, configIssues } from '../config/env';
import { getSupabaseClient } from '../api/client';
import { createSupabaseTransport } from '../sync/supabaseTransport';
import { createMockTransport } from '../sync/mockTransport';
import { syncGtfs, isSyncInProgress, toSyncError } from '../sync/engine';
import type { SyncOptions, SyncResult, SyncTransport } from '../sync/types';
import { SyncError } from '../utils/errors';
import { createLogger } from '../utils/logger';

const log = createLogger('services:sync');

/** Builds the transport for the configured source. Throws a typed error when unusable. */
export function createTransport(): SyncTransport {
  if (config.sourceMode === 'mock') {
    return createMockTransport();
  }

  if (!isRemoteSyncConfigured) {
    throw new SyncError(
      `Supabase is not configured (${configIssues.map((issue) => issue.key).join(', ')}). ` +
        'Set the values in .env, or run with EXPO_PUBLIC_USE_MOCK_GTFS=1.',
      { code: 'CONFIG_INVALID', retryable: false },
    );
  }

  const client = getSupabaseClient();
  if (client === null) {
    throw new SyncError('The Supabase client could not be created.', {
      code: 'CONFIG_INVALID',
      retryable: false,
    });
  }

  return createSupabaseTransport({ client });
}

/**
 * Runs a sync pass against whichever source is configured.
 *
 * `onConcurrent: 'join'` is the default: if a background wake-up is already syncing and the user
 * pulls to refresh, both callers await the same pass and get the same result.
 */
export async function syncNow(db: SqlExecutor, options: SyncOptions = {}): Promise<SyncResult> {
  const transport = createTransport();
  return syncGtfs(db, transport, options);
}

/**
 * Non-throwing wrapper for UI call sites.
 *
 * The dashboard never needs to handle a thrown sync error: a stale board with a "last synced
 * 2 hours ago" line is the correct behaviour, and the reason belongs in the diagnostics panel.
 */
export async function trySyncNow(
  db: SqlExecutor,
  options: SyncOptions = {},
): Promise<{ ok: true; result: SyncResult } | { ok: false; code: string; message: string }> {
  try {
    const result = await syncNow(db, options);
    return { ok: true, result };
  } catch (error) {
    const syncError = toSyncError(error, 'routes');
    log.warn('sync attempt failed', { code: syncError.code, message: syncError.message });
    return { ok: false, code: syncError.code, message: syncError.message };
  }
}

export type SourceStatus =
  | { readonly kind: 'mock' }
  | { readonly kind: 'remote'; readonly url: string }
  | { readonly kind: 'unconfigured'; readonly missing: readonly string[] };

/** What the settings screen shows: which source this build is actually using. */
export function getSourceStatus(): SourceStatus {
  if (config.sourceMode === 'mock') return { kind: 'mock' };
  if (!isRemoteSyncConfigured) {
    return { kind: 'unconfigured', missing: configIssues.map((issue) => issue.key) };
  }
  return { kind: 'remote', url: config.supabaseUrl };
}

export { isSyncInProgress };
export type { SyncResult };
