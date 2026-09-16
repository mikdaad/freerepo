/**
 * Supabase client for React Native.
 *
 * Four things the browser-oriented docs do not cover, all of which matter on a device:
 *
 * 1. **URL polyfill.** React Native's `URL` implementation is incomplete; `supabase-js` throws
 *    "URL.hostname is not implemented" on a cold start without `react-native-url-polyfill`.
 * 2. **Token storage without AsyncStorage.** Sessions are persisted through `expo-sqlite/kv-store`
 *    — an AsyncStorage-shaped API backed by the same SQLite file as the transit data, so the app
 *    ships one storage engine instead of two.
 * 3. **Auto-refresh tied to app state.** A refresh timer that keeps running while the app is
 *    backgrounded is killed by the OS on iOS and burns battery on Android; it must be started and
 *    stopped with `AppState`.
 * 4. **Request timeouts.** `fetch` in RN has no default timeout — a stalled connection would hang a
 *    background wake-up until Android kills it. Every request is wrapped with an `AbortController`.
 */

import 'react-native-url-polyfill/auto';

import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import Storage from 'expo-sqlite/kv-store';
import { AppState, type AppStateStatus } from 'react-native';

import { config, isRemoteSyncConfigured, requireSupabaseConfig } from '../config/env';
import type { Database } from './database.types';
import { createLogger } from '../utils/logger';

const log = createLogger('api:supabase');

let client: SupabaseClient<Database> | null = null;
let appStateSubscription: { remove: () => void } | null = null;

/**
 * `fetch` with a hard timeout.
 *
 * A timeout is reported as an `AbortError`, which the transport maps to a retryable network error.
 * Timeouts are *not* silent retries here: retry policy belongs to the sync engine, in one place.
 */
function createFetchWithTimeout(timeoutMs: number): typeof fetch {
  return async (input, init) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    // Respect a caller-supplied signal (the sync engine passes one for cancellation).
    const upstream = init?.signal ?? null;
    const onUpstreamAbort = (): void => controller.abort();
    if (upstream !== null) {
      if (upstream.aborted) controller.abort();
      else upstream.addEventListener('abort', onUpstreamAbort, { once: true });
    }

    try {
      return await fetch(input, { ...init, signal: controller.signal });
    } finally {
      clearTimeout(timer);
      upstream?.removeEventListener('abort', onUpstreamAbort);
    }
  };
}

function attachAutoRefreshControl(supabase: SupabaseClient<Database>): void {
  if (appStateSubscription !== null) return;

  const handleChange = (state: AppStateStatus): void => {
    if (state === 'active') {
      supabase.auth.startAutoRefresh();
    } else {
      supabase.auth.stopAutoRefresh();
    }
  };

  appStateSubscription = AppState.addEventListener('change', handleChange);
  handleChange(AppState.currentState);
}

/**
 * Returns the shared client, creating it on first use, or `null` when Supabase is not configured.
 * Never throws — a missing key must degrade to "offline-only app", not a white screen.
 */
export function getSupabaseClient(): SupabaseClient<Database> | null {
  if (!isRemoteSyncConfigured) return null;
  if (client !== null) return client;

  try {
    const { url, anonKey } = requireSupabaseConfig();
    client = createClient<Database>(url, anonKey, {
      auth: {
        storage: Storage,
        autoRefreshToken: true,
        persistSession: true,
        // Native apps never receive the session in a redirect URL.
        detectSessionInUrl: false,
        flowType: 'pkce',
      },
      global: {
        fetch: createFetchWithTimeout(config.syncTimeoutMs),
        headers: { 'x-application-name': 'transit-pulse' },
      },
      db: { schema: 'public' },
    });
    attachAutoRefreshControl(client);
    log.info('Supabase client created', { url });
    return client;
  } catch (error) {
    log.error('failed to create the Supabase client', error);
    return null;
  }
}

/** Throws when Supabase is unconfigured — for code paths that genuinely require it. */
export function requireSupabaseClient(): SupabaseClient<Database> {
  const supabase = getSupabaseClient();
  if (supabase === null) {
    requireSupabaseConfig(); // throws a descriptive error naming the missing variable(s)
    throw new Error('Supabase client unavailable');
  }
  return supabase;
}

/** Releases the AppState listener. Test-only; the app keeps one client for its lifetime. */
export function disposeSupabaseClient(): void {
  appStateSubscription?.remove();
  appStateSubscription = null;
  client = null;
}
