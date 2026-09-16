/**
 * Root layout.
 *
 * Outer edge of the app: theme tokens → error boundary → `SQLiteProvider` → router.
 *
 * The database provider lives here — and only here — so that:
 *   • `useTransitDatabase()` works in every route (Expo Router's Stack renders as children);
 *   • migrations run once, before any screen can query (SQLiteProvider blocks children until
 *     `onInit` resolves, which is exactly the guarantee we need);
 *   • the connection is opened with `enableChangeListener: true`, the prerequisite for the
 *     `useLiveQuery` hook to receive change events.
 *
 * Phase 3 adds the TaskManager task definitions (import side effect) and the permission prompts;
 * Phase 4 replaces the placeholder route with the commuter dashboard.
 */

import { Stack } from 'expo-router';
import { SQLiteProvider } from 'expo-sqlite';
import { StatusBar } from 'expo-status-bar';
import { Suspense } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { sqliteProviderProps } from '../src/db/client';
import '../global.css';

function DatabaseBootError({ message }: { message: string }): React.JSX.Element {
  return (
    <View className="flex-1 items-center justify-center gap-3 bg-canvas px-8">
      <Text className="text-center text-xl font-semibold text-offline">
        Local database unavailable
      </Text>
      <Text className="text-center text-sm text-secondary">{message}</Text>
      <Text className="text-center text-xs text-secondary">
        Transit data is stored on-device; without it the app cannot show departures. Reinstalling
        the app rebuilds the database from scratch.
      </Text>
    </View>
  );
}

function BootScreen(): React.JSX.Element {
  return (
    <View className="flex-1 items-center justify-center gap-4 bg-canvas">
      <ActivityIndicator size="large" color="#38BDF8" />
      <Text className="text-sm text-secondary">Opening local transit database…</Text>
    </View>
  );
}

export default function RootLayout(): React.JSX.Element {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        {/* `dark` maps to the night-platform token set in global.css. */}
        <View className="flex-1 bg-canvas">
          <StatusBar style="light" />
          <Suspense fallback={<BootScreen />}>
            <SQLiteProvider {...sqliteProviderProps} useSuspense>
              <Stack
                screenOptions={{
                  headerStyle: { backgroundColor: '#0B1120' },
                  headerTintColor: '#F8FAFC',
                  headerTitleStyle: { fontWeight: '700' },
                  contentStyle: { backgroundColor: '#0B1120' },
                }}
              >
                <Stack.Screen name="index" options={{ title: 'Transit Pulse' }} />
              </Stack>
            </SQLiteProvider>
          </Suspense>
        </View>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

export { DatabaseBootError };
