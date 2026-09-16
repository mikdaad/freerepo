/**
 * `useLiveQuery` — reactive reads against the local database.
 *
 * expo-sqlite shipped `useLiveQuery` up to SDK 53 and **removed** it in SDK 54+. The supported
 * primitive now is `SQLiteProvider` opened with `enableChangeListener: true` plus the global
 * `addDatabaseChangeListener`, which fires for every committed row mutation. This hook is the thin
 * layer on top of that primitive, keeping the ergonomics the app was designed around:
 *
 * ```tsx
 * const { data, isLoading, error } = useLiveQuery(
 *   (db) => listFavouriteStops(db),
 *   [],                                  // query identity / re-run deps (like a query key)
 *   { tables: ['favorite_stops', 'stops'] },
 * );
 * ```
 *
 * Behaviour worth knowing:
 *  • Refresh is **table-scoped**. A sync touching 200 000 `stop_times` rows must not re-run the
 *    departure-board query; naming the tables it reads avoids exactly that.
 *  • Refresh is **debounced** (120 ms default, 1 s ceiling). A batch sync commits thousands of row
 *    events; without coalescing the UI would re-render thousands of times.
 *  • A stale response can never overwrite a fresh one: every run carries a sequence number and only
 *    the newest is allowed to commit state.
 */

import { addDatabaseChangeListener } from 'expo-sqlite';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getErrorMessage } from '../utils/errors';
import { useTransitDatabase } from './useTransitDatabase';
import type { SqlExecutor } from './types';

export interface LiveQueryOptions {
  /**
   * Tables this query reads. Only change events for these tables trigger a re-run.
   * Omit to re-run on *any* change in the database (rarely what you want during a sync).
   */
  readonly tables?: readonly string[];
  /** Coalescing window for bursts of change events. Default 120 ms. */
  readonly debounceMs?: number;
  /** Upper bound on how long coalescing may delay a refresh. Default 1000 ms. */
  readonly maxDebounceMs?: number;
  /** Set to false to suspend the query (e.g. a screen that is not focused). */
  readonly enabled?: boolean;
}

export interface LiveQueryResult<T> {
  readonly data: T | null;
  readonly error: string | null;
  readonly isLoading: boolean;
  /** Epoch ms of the last successful run — feeds "synced 2 min ago". */
  readonly updatedAt: number | null;
  /** Force a re-run right now (pull-to-refresh). */
  readonly refresh: () => void;
}

/** Counts runs so responses from superseded runs can be discarded. */
let runSequence = 0;

export function useLiveQuery<T>(
  queryFn: (db: SqlExecutor) => Promise<T>,
  deps: readonly unknown[] = [],
  options: LiveQueryOptions = {},
): LiveQueryResult<T> {
  const db = useTransitDatabase();
  const { tables, debounceMs = 120, maxDebounceMs = 1_000, enabled = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);

  // Latest query function without re-subscribing on every render. Assigned in an effect (never
  // during render) — updating a ref during render is a React 19 compiler violation.
  const queryRef = useRef(queryFn);
  useEffect(() => {
    queryRef.current = queryFn;
  }, [queryFn]);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(() => {
    setRevision((current) => current + 1);
  }, []);

  // --- Execution -------------------------------------------------------------------------------
  useEffect(() => {
    if (!enabled) return;

    const sequence = (runSequence += 1);
    let cancelled = false;

    void (async () => {
      // The loading flag is raised inside the async run rather than in the effect body: it belongs
      // to the query lifecycle (and React's rules forbid synchronous setState in an effect).
      setIsFetching(true);
      try {
        const result = await queryRef.current(db);
        if (cancelled || sequence !== runSequence || !mountedRef.current) return;
        setData(result);
        setError(null);
        setUpdatedAt(Date.now());
      } catch (queryError) {
        if (cancelled || sequence !== runSequence || !mountedRef.current) return;
        // Keep the previous `data` — a transient failure must not blank the board.
        setError(getErrorMessage(queryError));
      } finally {
        if (!cancelled && sequence === runSequence && mountedRef.current) setIsFetching(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // `deps` is the caller-supplied query identity (the same contract as React Query's `queryKey`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [db, enabled, revision, ...deps]);

  // --- Change subscription ---------------------------------------------------------------------
  const tableFilter = useMemo(() => {
    if (tables === undefined) return null;
    return new Set(tables);
  }, [tables]);

  useEffect(() => {
    if (!enabled) return;

    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let windowOpenedAt = 0;

    const scheduleRefresh = (): void => {
      const now = Date.now();
      if (windowOpenedAt === 0) windowOpenedAt = now;
      if (debounceTimer !== null) clearTimeout(debounceTimer);

      // Never let sustained churn starve the UI: past the ceiling, release immediately.
      const elapsed = now - windowOpenedAt;
      const delay = elapsed >= maxDebounceMs ? 0 : debounceMs;

      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        windowOpenedAt = 0;
        refresh();
      }, delay);
    };

    const subscription = addDatabaseChangeListener((event) => {
      if (tableFilter !== null && !tableFilter.has(event.tableName)) return;
      scheduleRefresh();
    });

    return () => {
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      subscription.remove();
    };
  }, [debounceMs, enabled, maxDebounceMs, refresh, tableFilter]);

  return {
    data,
    error,
    // Derived, not stored: a suspended query reports "not loading" without touching state in an
    // effect, which React 19's linter (rightly) rejects.
    isLoading: enabled && isFetching,
    updatedAt,
    refresh,
  };
}
