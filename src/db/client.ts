/**
 * Device-side SQLite wiring for `expo-sqlite`.
 *
 * This is the only file in the data layer that imports a native module. Everything else depends on
 * the `SqlExecutor` interface from ./types, which is why the repositories and the sync engine can
 * be executed against a real SQLite engine in Node (scripts/verify-db.ts).
 *
 * SDK 57 note: `useLiveQuery` / `useSQLiteContext().liveQuery` were **removed** from expo-sqlite.
 * Live updates are now opt-in through `enableChangeListener` + `addDatabaseChangeListener`; the
 * `useLiveQuery` hook re-exported from ./useLiveQuery builds on those primitives and keeps the
 * ergonomics the app was designed around.
 */

import * as SQLite from 'expo-sqlite';
import { Platform } from 'react-native';

import { config } from '../config/env';
import { DatabaseError } from '../utils/errors';
import { createLogger } from '../utils/logger';
import { initializeDatabase } from './migrations';
import type { SqlBindParams, SqlExecutor, SqlPreparedStatement, SqlRunResult } from './types';

const log = createLogger('db:client');

/** On-disk database file name. Shared with the background task entry point. */
export const DATABASE_NAME = config.databaseName;

/**
 * Whether WAL should be requested.
 * The web build runs wa-sqlite in a worker and has no real `-wal` file, so it uses the default
 * rollback journal instead.
 */
export const SUPPORTS_WAL = Platform.OS !== 'web';

/**
 * Open options applied to every connection.
 *
 * `enableChangeListener: true` hooks `sqlite3_update_hook()`. That hook is what makes the
 * dashboard tick over the instant a background sync commits, instead of polling on a timer.
 * It costs a small amount of write throughput — acceptable, because our writes are batched.
 */
export const DATABASE_OPEN_OPTIONS: SQLite.SQLiteOpenOptions = {
  enableChangeListener: true,
  useNewConnection: false,
};

/**
 * Adapts expo-sqlite's `SQLiteDatabase` to the framework-agnostic `SqlExecutor`.
 * The casts are confined to this file on purpose: expo-sqlite exposes overloads
 * (`runAsync(sql, ...params)`), while `SqlExecutor` declares the single canonical shape.
 */
export function adaptSQLiteDatabase(database: SQLite.SQLiteDatabase): SqlExecutor {
  return {
    execAsync: (source: string): Promise<void> => database.execAsync(source),

    runAsync: async (source: string, params?: SqlBindParams): Promise<SqlRunResult> => {
      const result =
        params === undefined
          ? await database.runAsync(source)
          : await database.runAsync(source, params as SQLite.SQLiteBindParams);
      return { changes: result.changes, lastInsertRowId: result.lastInsertRowId };
    },

    getAllAsync: <T>(source: string, params?: SqlBindParams): Promise<T[]> =>
      params === undefined
        ? database.getAllAsync<T>(source)
        : database.getAllAsync<T>(source, params as SQLite.SQLiteBindParams),

    getFirstAsync: <T>(source: string, params?: SqlBindParams): Promise<T | null> =>
      params === undefined
        ? database.getFirstAsync<T>(source)
        : database.getFirstAsync<T>(source, params as SQLite.SQLiteBindParams),

    prepareAsync: async (source: string): Promise<SqlPreparedStatement> => {
      const statement = await database.prepareAsync(source);
      return {
        executeAsync: async (params: SqlBindParams): Promise<void> => {
          await statement.executeAsync(params as SQLite.SQLiteBindParams);
        },
        finalizeAsync: (): Promise<void> => statement.finalizeAsync(),
      };
    },
  };
}

/**
 * Runs the full boot sequence (pragmas → migrations → sync_state seed) against a live connection.
 * Wrapped so any failure surfaces as a typed `DatabaseError` the UI can render.
 */
export async function initializeDatabaseConnection(database: SQLite.SQLiteDatabase): Promise<void> {
  try {
    await initializeDatabase(adaptSQLiteDatabase(database), { preferWal: SUPPORTS_WAL });
  } catch (error) {
    log.error('database initialisation failed', error, { databaseName: DATABASE_NAME });
    if (error instanceof DatabaseError) throw error;
    throw new DatabaseError('Unexpected failure during database initialisation', {
      code: 'DB_OPEN_FAILED',
      cause: error,
    });
  }
}

/** Props for the root `<SQLiteProvider>`; kept here so app/_layout.tsx stays declarative. */
export const sqliteProviderProps: {
  databaseName: string;
  options: SQLite.SQLiteOpenOptions;
  onInit: (database: SQLite.SQLiteDatabase) => Promise<void>;
  onError: (error: Error) => void;
} = {
  databaseName: DATABASE_NAME,
  options: DATABASE_OPEN_OPTIONS,
  onInit: initializeDatabaseConnection,
  onError: (error: Error) => {
    // Rethrown, not swallowed: a database that cannot be opened is not something the UI can
    // paper over, and ErrorBoundary should show the developer the real cause.
    log.error('SQLiteProvider reported an error', error, { databaseName: DATABASE_NAME });
  },
};

/**
 * Opens a connection synchronously.
 *
 * Used by background entry points (`TaskManager` executors and notification handlers) which run
 * with a hard wall-clock budget and cannot afford the async open handshake. **The caller must close
 * it**: see `withTemporaryDatabase`.
 */
export function openTransitDatabaseSync(): SQLite.SQLiteDatabase {
  const database = SQLite.openDatabaseSync(DATABASE_NAME, DATABASE_OPEN_OPTIONS);
  return database;
}

/** Opens a connection asynchronously (preferred outside of background tasks). */
export async function openTransitDatabaseAsync(): Promise<SQLite.SQLiteDatabase> {
  return SQLite.openDatabaseAsync(DATABASE_NAME, DATABASE_OPEN_OPTIONS);
}

/**
 * Opens the database, ensures it is migrated, hands the executor to `work`, then closes it.
 *
 * Always use this from a background task: Android may kill the process at any moment, and an
 * unclosed WAL connection there means the next wake-up pays for recovery.
 */
export async function withTemporaryDatabase<T>(
  work: (db: SqlExecutor, database: SQLite.SQLiteDatabase) => Promise<T>,
): Promise<T> {
  const database = await openTransitDatabaseAsync();
  try {
    await initializeDatabaseConnection(database);
    return await work(adaptSQLiteDatabase(database), database);
  } finally {
    try {
      await database.closeAsync();
    } catch (error) {
      log.warn('failed to close a temporary database connection', {
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }
}
