/**
 * `useTransitDatabase()` — the app's single access point to the open SQLite connection.
 *
 * `useSQLiteContext()` returns expo-sqlite's class instance; everything downstream wants the
 * framework-agnostic `SqlExecutor`. Adapting once here means no component or repository in the app
 * ever imports `expo-sqlite` directly, which is what lets the whole data layer run in Node tests.
 */

import { useSQLiteContext } from 'expo-sqlite';
import { useMemo } from 'react';

import { adaptSQLiteDatabase } from './client';
import type { SqlExecutor } from './types';

export function useTransitDatabase(): SqlExecutor {
  const database = useSQLiteContext();
  // `useSQLiteContext` returns a stable instance for the lifetime of the provider, so memoising on
  // identity keeps effects from re-running on every render.
  return useMemo(() => adaptSQLiteDatabase(database), [database]);
}
