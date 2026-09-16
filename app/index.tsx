/**
 * Phase 2 smoke screen.
 *
 * This route is a *placeholder*: Phase 4 replaces it with the Commuter Dashboard (nearby stops,
 * live departure board, alarm shortcuts). Until then it is the fastest way to see, on a real
 * device, that the Phase 1 + Phase 2 foundations are working:
 *
 *   • migrations ran (schema version + table list on screen);
 *   • the sync engine can talk to Supabase or the built-in mock feed;
 *   • the offline board query returns rows through the `SqlExecutor` seam;
 *   • `useLiveQuery` refreshes the counts when a sync commits, with no manual invalidation.
 */

import { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';

import { useLiveQuery } from '../src/db/useLiveQuery';
import { useTransitDatabase } from '../src/db/useTransitDatabase';
import { getDatabaseFootprint, getTableCounts, readAllSyncState } from '../src/data/syncState';
import { getSourceStatus, isSyncInProgress, trySyncNow } from '../src/services/syncService';
import { formatDistance, haversineMeters } from '../src/utils/geo';

function StatRow({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <View className="flex-row items-baseline justify-between py-1">
      <Text className="text-xs uppercase tracking-wide text-secondary">{label}</Text>
      <Text className="font-mono text-sm text-primary">{value}</Text>
    </View>
  );
}

export default function PhaseTwoStatusScreen(): React.JSX.Element {
  const db = useTransitDatabase();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const source = getSourceStatus();

  // Every number below re-reads itself when the sync engine commits a page.
  const { data: counts, isLoading } = useLiveQuery((executor) => getTableCounts(executor), [], {
    tables: ['routes', 'stops', 'trips', 'stop_times', 'calendar', 'calendar_dates'],
  });
  const { data: syncState } = useLiveQuery((executor) => readAllSyncState(executor), [], {
    tables: ['sync_state'],
  });
  const { data: footprint } = useLiveQuery((executor) => getDatabaseFootprint(executor), [], {
    tables: ['stop_times'],
  });

  const handleSync = useCallback(async () => {
    setSyncing(true);
    setMessage(null);
    const outcome = await trySyncNow(db, { onConcurrent: 'join' });
    setMessage(
      outcome.ok
        ? `Sync ${outcome.result.status}: ${outcome.result.rowsWritten} rows written in ${outcome.result.durationMs} ms`
        : `Sync failed (${outcome.code}): ${outcome.message}`,
    );
    setSyncing(false);
  }, [db]);

  return (
    <ScrollView className="flex-1 bg-canvas" contentContainerClassName="p-safe gap-4 pb-16">
      <View className="gap-1">
        <Text className="text-2xl font-bold text-primary">Phase 1 + 2 online</Text>
        <Text className="text-sm text-secondary">
          Local-first SQLite store, GTFS sync engine, and offline query layer are wired up.
        </Text>
      </View>

      <View className="rounded-card bg-surface p-4">
        <Text className="mb-2 text-xs font-semibold uppercase tracking-wide text-accent">
          Source
        </Text>
        <StatRow
          label="mode"
          value={
            source.kind === 'remote'
              ? 'supabase'
              : source.kind === 'mock'
                ? 'mock feed'
                : 'unconfigured'
          }
        />
        {source.kind === 'remote' ? <StatRow label="project" value={source.url} /> : null}
        {source.kind === 'unconfigured' ? (
          <StatRow label="missing" value={source.missing.join(', ')} />
        ) : null}
        <StatRow label="sync running" value={isSyncInProgress() ? 'yes' : 'no'} />
      </View>

      <View className="rounded-card bg-surface p-4">
        <Text className="mb-2 text-xs font-semibold uppercase tracking-wide text-accent">
          Local database
        </Text>
        {isLoading && counts === null ? (
          <ActivityIndicator color="#38BDF8" />
        ) : (
          <>
            <StatRow label="routes" value={String(counts?.routes ?? 0)} />
            <StatRow label="stops" value={String(counts?.stops ?? 0)} />
            <StatRow label="trips" value={String(counts?.trips ?? 0)} />
            <StatRow label="stop_times" value={String(counts?.stop_times ?? 0)} />
            <StatRow
              label="calendar"
              value={`${counts?.calendar ?? 0} / ${counts?.calendar_dates ?? 0}`}
            />
            <StatRow
              label="file size"
              value={footprint ? `${(footprint.bytes / 1024 / 1024).toFixed(2)} MB` : '--'}
            />
          </>
        )}
      </View>

      <View className="rounded-card bg-surface p-4">
        <Text className="mb-2 text-xs font-semibold uppercase tracking-wide text-accent">
          Cursors (sync_version per entity)
        </Text>
        {(syncState ?? []).map((row) => (
          <StatRow
            key={row.entity}
            label={row.entity}
            value={row.cursor === 0 ? 'not synced' : String(row.cursor)}
          />
        ))}
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Sync transit data now"
        disabled={syncing}
        onPress={handleSync}
        className={`min-h-tap items-center justify-center rounded-pill px-6 py-3 ${
          syncing ? 'bg-elevated' : 'bg-accent'
        }`}
      >
        {syncing ? (
          <ActivityIndicator color="#041626" />
        ) : (
          <Text className="text-base font-bold text-accent-ink">Sync transit data</Text>
        )}
      </Pressable>

      {message !== null ? <Text className="text-xs text-secondary">{message}</Text> : null}

      <View className="rounded-card bg-elevated p-4">
        <Text className="mb-2 text-xs font-semibold uppercase tracking-wide text-caution">
          Coming next
        </Text>
        <Text className="text-sm text-secondary">
          Phase 3: geofenced wake-up alarms (TaskManager + expo-location), permission flow, and the
          background notification.
        </Text>
        <Text className="mt-2 text-sm text-secondary">
          Phase 4: the commuter dashboard reading this database with zero network calls, styled for
          outdoor readability.
        </Text>
      </View>

      <Text className="text-2xs text-secondary">
        Sanity check: the harness in scripts/verify-db.ts exercises this exact data layer against a
        real SQLite engine (`npm run verify`).
      </Text>
      <Text className="text-2xs text-secondary">
        Haversine self-test — 1° of latitude ≈{' '}
        {formatDistance(
          haversineMeters({ latitude: 0, longitude: 0 }, { latitude: 1, longitude: 0 }),
        )}
      </Text>
    </ScrollView>
  );
}
