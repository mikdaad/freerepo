/**
 * Runtime configuration.
 *
 * All values originate from `EXPO_PUBLIC_*` environment variables. Metro performs a **literal text
 * substitution** at build time: `process.env.EXPO_PUBLIC_SUPABASE_URL` becomes the string itself.
 * That is why every read below is written out statically — `process.env[key]` is not substituted,
 * yields `undefined` in a release bundle, and is rejected by `eslint-config-expo`'s
 * `expo/no-dynamic-env-var` rule for exactly this reason.
 *
 * Nothing here is secret: an anon key is by definition public, and Supabase RLS is the security
 * boundary.
 *
 * Design rule: **never throw at import time**. A misconfigured project must still boot into a
 * usable UI (empty offline database + a screen explaining what is missing), because the entire point
 * of this app is to work when the network — or the backend — is unavailable.
 */

export type GtfsSourceMode = 'supabase' | 'mock';

export interface AppConfig {
  /** Supabase project URL, e.g. `https://xyzcompany.supabase.co`. Empty when unset. */
  readonly supabaseUrl: string;
  /** Supabase anon/public key. Empty when unset. */
  readonly supabaseAnonKey: string;
  /** Rows requested per page during a sync pass. */
  readonly syncPageSize: number;
  /** Retry attempts for *retryable* sync failures (network, 429, 5xx). */
  readonly syncMaxRetries: number;
  /** Per-request timeout for a single sync page, in milliseconds. */
  readonly syncTimeoutMs: number;
  /** Hard ceiling on pages fetched per entity per pass — a runaway guard. */
  readonly syncMaxPagesPerEntity: number;
  /** `mock` runs the whole sync pipeline against a deterministic in-process feed. */
  readonly sourceMode: GtfsSourceMode;
  /** Verbose sync logging. */
  readonly syncDebug: boolean;
  /** SQLite file name (mirrors `extra.databaseName` in app.json). */
  readonly databaseName: string;
}

export interface ConfigIssue {
  readonly key: string;
  readonly message: string;
}

const BOOLEAN_TRUTHY = new Set(['1', 'true', 'yes', 'on']);

/** Raw, statically-substituted values. One place to see every variable the app consumes. */
const RAW = {
  supabaseUrl: process.env.EXPO_PUBLIC_SUPABASE_URL,
  supabaseAnonKey: process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY,
  syncPageSize: process.env.EXPO_PUBLIC_SYNC_PAGE_SIZE,
  syncMaxRetries: process.env.EXPO_PUBLIC_SYNC_MAX_RETRIES,
  syncTimeoutMs: process.env.EXPO_PUBLIC_SYNC_TIMEOUT_MS,
  syncMaxPages: process.env.EXPO_PUBLIC_SYNC_MAX_PAGES,
  databaseName: process.env.EXPO_PUBLIC_DATABASE_NAME,
  useMockGtfs: process.env.EXPO_PUBLIC_USE_MOCK_GTFS,
  syncDebug: process.env.EXPO_PUBLIC_SYNC_DEBUG,
} as const;

const asString = (value: string | undefined, fallback = ''): string =>
  typeof value === 'string' ? value.trim() : fallback;

const asBoolean = (value: string | undefined, fallback = false): boolean => {
  const raw = asString(value);
  return raw === '' ? fallback : BOOLEAN_TRUTHY.has(raw.toLowerCase());
};

const asInt = (value: string | undefined, fallback: number, min: number, max: number): number => {
  const raw = asString(value);
  if (raw === '') return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
};

const SUPABASE_URL_PATTERN = /^https:\/\/[a-z0-9-]+\.supabase\.(co|in)$/i;

export const config: AppConfig = {
  supabaseUrl: asString(RAW.supabaseUrl),
  supabaseAnonKey: asString(RAW.supabaseAnonKey),
  syncPageSize: asInt(RAW.syncPageSize, 500, 25, 1000),
  syncMaxRetries: asInt(RAW.syncMaxRetries, 3, 0, 10),
  syncTimeoutMs: asInt(RAW.syncTimeoutMs, 20_000, 1_000, 120_000),
  syncMaxPagesPerEntity: asInt(RAW.syncMaxPages, 200, 1, 10_000),
  sourceMode: asBoolean(RAW.useMockGtfs, false) ? 'mock' : 'supabase',
  syncDebug: asBoolean(RAW.syncDebug, false),
  databaseName: asString(RAW.databaseName, 'transit.db'),
};

/**
 * Human-readable configuration problems. Empty array === the Supabase source is usable.
 * The dashboard surfaces these instead of failing silently.
 */
export const configIssues: readonly ConfigIssue[] = (() => {
  const issues: ConfigIssue[] = [];
  if (config.sourceMode === 'mock') return issues;

  if (!config.supabaseUrl) {
    issues.push({
      key: 'EXPO_PUBLIC_SUPABASE_URL',
      message: 'Missing. Copy .env.example to .env and paste your project URL.',
    });
  } else if (!SUPABASE_URL_PATTERN.test(config.supabaseUrl)) {
    issues.push({
      key: 'EXPO_PUBLIC_SUPABASE_URL',
      message: `"${config.supabaseUrl}" is not a valid Supabase project URL.`,
    });
  }

  if (!config.supabaseAnonKey) {
    issues.push({
      key: 'EXPO_PUBLIC_SUPABASE_ANON_KEY',
      message: 'Missing. Use the anon/public key — never the service_role key.',
    });
  }

  return issues;
})();

/** True when the remote GTFS source can actually be reached. */
export const isRemoteSyncConfigured: boolean = configIssues.length === 0;

/** True when the app should sync from Supabase (configured) or from the built-in mock feed. */
export const isSyncEnabled: boolean = config.sourceMode === 'mock' || isRemoteSyncConfigured;

/** Throws when Supabase settings are incomplete. Call before constructing the client. */
export function requireSupabaseConfig(): { url: string; anonKey: string } {
  if (configIssues.length > 0) {
    const summary = configIssues.map((issue) => `${issue.key}: ${issue.message}`).join(' | ');
    throw new Error(`Supabase is not configured — ${summary}`);
  }
  return { url: config.supabaseUrl, anonKey: config.supabaseAnonKey };
}
