# Transit Pulse — Phase 1 & 2 deliverables

Offline-first commuter transit app: Expo (SDK 57, managed workflow, Expo Router) + TypeScript
strict + NativeWind + `expo-sqlite` + Supabase sync, with `expo-location` / `expo-task-manager`
geofencing to come in Phase 3.

This document is the hand-off for **Phase 1 (setup & config)** and **Phase 2 (database + sync
layer)**. Every claim below is either verified by the harness (`npm run verify`) or by an actual
bundle build (`npx expo export`).

---

## 1. What runs today

```bash
npm install
cp .env.example .env          # optional — leave empty to run against the built-in mock feed
npm run verify                # typecheck (app + scripts) + 75-check database/sync harness
npm start                     # or: npm run ios / npm run android
```

With no `.env` the app still boots: `EXPO_PUBLIC_USE_MOCK_GTFS=1` switches the whole pipeline onto
a deterministic in-process feed (3 routes, 16 stops, ~490 trips, ~7 400 stop times, including
past-midnight trips and a soft-deleted stop).

---

## 2. File map

### Phase 1 — setup & configuration

| File | Purpose |
| --- | --- |
| `app.json` | Expo config. Plugins: `expo-router`, `expo-sqlite` (`enableFTS`, no cipher), `expo-location` (background + foreground-service flags **on**), `expo-notifications`, `expo-task-manager`. Android permissions incl. `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE_LOCATION`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`; iOS `UIBackgroundModes: ["location", "fetch"]`; `experiments.typedRoutes`. |
| `babel.config.js` | `babel-preset-expo` with `jsxImportSource: 'nativewind'` + `nativewind/babel`. **No manual worklets plugin** — `babel-preset-expo` appends `react-native-worklets/plugin` itself (verified in `node_modules/expo/node_modules/babel-preset-expo/build/configs/expo.js:97`); adding it twice corrupts worklet hashes. |
| `metro.config.js` | `withNativeWind(config, { input: './global.css' })`; `.wasm` added to `assetExts` and COOP/COEP headers set on the dev server for `expo-sqlite`'s web (wa-sqlite) build. |
| `tailwind.config.js` | NativeWind preset + semantic token palette (canvas/surface/elevated/hairline/primary/secondary/accent/live/caution/offline), an enlarged type scale for outdoor reading, `tap`/`tap-lg` spacing, `card`/`pill` radii. |
| `global.css` | Two themes over one token contract: the default night-platform palette and `.theme-outdoor` (near-black on near-white for direct sunlight). Levels chosen for WCAG AAA on body text. |
| `tsconfig.json` | `expo/tsconfig.base` + `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noImplicitReturns`; `@/*` → `src/*`. `scripts/**` is excluded — it is checked by `scripts/tsconfig.json` (which adds `@types/node`) so Node globals never leak into RN code. |
| `eslint.config.js`, `.prettierrc` | Flat config from `eslint-config-expo/flat`; Prettier with the Tailwind class sorter. |
| `types/globals.d.ts`, `types/css.d.ts` | Ambient types: `expo/types` reference, the `__DEV__` global (not declared by any shipped package), and a real `*.css` module declaration (TypeScript 6 rejects Expo's bodyless one for side-effect imports). |

### Phase 2 — database layer

| File | Purpose |
| --- | --- |
| `src/db/types.ts` | `SqlExecutor` (the seam), `SqlPreparedStatement`, bind types, row interfaces for every table. |
| `src/db/schema.ts` | The three migrations (DDL), pragmas, `LATEST_SCHEMA_VERSION`, and the frozen GTFS-time parser used by the v2 backfill. |
| `src/db/migrations.ts` | Runner: `schema_migrations` bootstrap, FNV-1a checksums, one `BEGIN IMMEDIATE` transaction per migration with rollback, `PRAGMA user_version` fast path, pragma application, integrity check, `sync_state` seeding. |
| `src/db/sql.ts` | Identifier validation, column registries, `buildUpsertPlan` / `buildDeleteByKeyPlan`, `rowToBindValues`, and the three hot queries (nearby stops, departures, active services). |
| `src/db/client.ts` | The only module that imports `expo-sqlite`: `adaptSQLiteDatabase`, provider props (`enableChangeListener: true`), open-sync/async, `withTemporaryDatabase` for background tasks. |
| `src/db/useLiveQuery.ts` | Reactive reads, built on `addDatabaseChangeListener` (the SDK 57 replacement for the removed `useLiveQuery`): table-scoped filtering, 120 ms debounce with a 1 s ceiling, stale-response guard. |
| `src/db/useTransitDatabase.ts` | `useSQLiteContext()` → memoised `SqlExecutor`. |
| `src/data/*.ts` | Repositories: stops (nearby/search/favourites), routes, service calendars, departure boards, sync state + run log, alarms, settings. |
| `src/sync/types.ts`, `engine.ts` | Transport contract and the sync engine (paging, transactions, retries, tombstones, progress, mutex). |
| `src/sync/supabaseTransport.ts`, `mappers.ts` | PostgREST keyset paging + wire→row mapping with Postgres quirks handled (`timestamptz` → ms, `bigint`/`numeric` as strings, colour normalisation). |
| `src/sync/mockTransport.ts` | Deterministic offline feed, used by the app in mock mode **and** by the harness against the real engine. |
| `src/api/database.types.ts`, `client.ts` | Supabase schema types and the RN client (URL polyfill, `expo-sqlite/kv-store` session storage, `AppState`-scoped auto-refresh, per-request timeout). |
| `src/services/syncService.ts` | Picks the transport for the configured mode; non-throwing `trySyncNow` for UI call sites. |
| `supabase/migrations/0001_gtfs_sync.sql` | Server schema: shared `sync_version` sequence + trigger, soft deletes, per-table cursor indexes, RLS (anon read-only), and a `gtfs_sync_health` view. |
| `scripts/verify-db.ts`, `scripts/lib/harness.ts` | The Node verification harness (see §4). |
| `app/_layout.tsx`, `app/index.tsx` | Root layout (provider wiring) and a Phase-2 status screen to smoke-test on device. Phase 4 replaces the screen. |

---

## 3. Decisions that matter (and why)

**The sync cursor is a server sequence, not a timestamp.** `updated_at` ties: two rows written in the
same millisecond are skipped or duplicated depending on the comparison operator. One shared
Postgres sequence feeds `sync_version` on all six tables, so a single integer cursor is a *total
order across the whole feed*, and `WHERE sync_version > :cursor ORDER BY sync_version` is exact.
Keyset paging (`.gt()`), never `.range()` offsets, which re-scan and can both skip and duplicate
while an ETL job writes.

**Deletes travel as tombstones through the same ordered stream.** A hard `DELETE` is invisible to a
client that has already synced past it, leaving a phantom row on every device forever. Soft deletes
mean one cursor delivers inserts, updates and deletes in one order.

**`ON CONFLICT … DO UPDATE`, never `INSERT OR REPLACE`.** `OR REPLACE` deletes the conflicting row
and inserts a new one, which fires `ON DELETE CASCADE` — replacing one route would silently wipe
every trip that references it. The harness asserts the generated SQL never contains the naive form.

**Foreign keys are enforced (`PRAGMA foreign_keys = ON`).** SQLite defaults to *off*; without it the
cascades that keep `trips`/`stop_times` consistent do nothing. Entities therefore sync parents-first
(`routes`, `stops` → `trips` → `stop_times`).

**GTFS times are stored twice: raw text *and* integer seconds.** GTFS `departure_time` is an offset
from the service day's midnight and may exceed 24 (`25:10:00`); ordering by the text column is only
accidentally correct. `departure_seconds` is derived at write time, indexed as
`(stop_id, departure_seconds)`, and backfilled by migration 2 for older rows.

**The service day is not the calendar day.** `serviceDayCandidates()` returns yesterday's service
day as well until 04:00, because post-midnight trips (`24:xx`–`27:xx`) belong to it. A naive
"today only" board is empty at 00:40 while a bus is 20 minutes away. (This was a real bug found by
the harness, not a hypothetical.)

**Service calendars are consulted, not assumed.** `calendar` minus type-2 exceptions, unioned with
type-1 additions. When a feed ships no calendar at all, `getActiveServiceIds` returns `null` and the
service filter is dropped rather than returning an empty board for a working feed.

**Geodesy lives in JavaScript, bounding boxes in SQL.** SQLite's `sin()`/`cos()` are a compile-time
option not guaranteed in every shipped build, so SQLite does the indexed box scan and `geo.ts` ranks
with haversine. The harness verifies ranking, radius filtering, and the antimeridian case.

**`SqlExecutor` keeps the data layer testable.** No repository imports `expo-sqlite`; the device
adapts `SQLiteDatabase`, Node adapts `node:sqlite`, and both run the same SQL.

**Supabase-in-RN details**: `react-native-url-polyfill` (RN's `URL` is incomplete), sessions stored
via `expo-sqlite/kv-store` (no AsyncStorage anywhere in this project), auto-refresh started/stopped
with `AppState`, and a hard per-request timeout because RN's `fetch` has none — a stalled request
would otherwise eat a background wake-up's entire budget.

**Purge semantics are explicit.** "Reset local data" clears the feed *and* the alarms/favourites
whose stops vanished, because a geofence is armed from stop coordinates — `purgeGtfsData()` returns
`alarmsRemoved` so the confirmation dialog can say so out loud.

---

## 4. Verification

```bash
npm run verify        # tsc (app) && tsc (scripts) && tsx scripts/verify-db.ts
```

```
75/75 checks passed
All Phase 2 invariants hold.
```

The harness runs the **real** migrations, repositories and sync engine against a **real** SQLite
engine (`node:sqlite`, SQLite 3.51) — no simulator, no emulator, no backend:

1. **Migrations** — apply from empty, are idempotent (`user_version`, `applied.length === 0` on the
   second run), leave no checksum drift, create every table and the derived `stop_times` columns.
2. **Sync** — a multi-page pass lands every row, registers `stop_times` pages > 1, and a second pass
   writes zero rows (cursor respected). A `fullResync` re-reads everything without duplicating rows.
3. **Tombstones & constraints** — the soft-deleted stop is gone, its `stop_times` cascade away,
   `PRAGMA foreign_key_check` is clean, `integrity_check` is `ok`, and inserting a trip with an
   unknown route is rejected.
4. **Retries** — a transport that fails three times still succeeds within budget; a permanent
   `SYNC_UNAUTHORIZED` is **not** retried and is reported per entity.
5. **Departure board** — ordered by time-to-arrival, horizon-bounded, labelled; the past-midnight
   board contains `24:xx` departures from yesterday's service day, and they are labelled `(+1)`.
6. **Data operations** — LIKE wildcards escaped, favourites, alarms with the re-arm cooldown
   (fired → suppressed → fired again), validation bounds, settings, calendar coverage, run log.
7. **SQL hygiene** — upsert uses `DO UPDATE` and never rewrites primary keys; booleans normalise to
   `0`/`1`; purge empties the feed, resets cursors, and reports the alarms it removed.

Additional checks run manually during this phase:

| Check | Result |
| --- | --- |
| `npx tsc --noEmit` (app) | 0 errors, `strict` + `noUncheckedIndexedAccess` |
| `tsc -p scripts/tsconfig.json` | 0 errors |
| `npm run lint` | 0 problems |
| `npx expo export --platform ios` | ✅ 1688 modules → 4.6 MB Hermes bundle |

The export is the end-to-end proof that `app.json`, `babel.config.js`, `metro.config.js`,
`tailwind.config.js`, Expo Router and NativeWind all agree with each other.

---

## 5. Phase 3 / 4 notes (verified API facts to code against)

Everything below was read out of the installed packages, not from memory.

**expo-location 57.0.18** — the enum is exported both as `LocationGeofencingEventType` and, at the
namespace import, as `Location.GeofencingEventType` (`Enter = 1`, `Exit = 2`). Regions:
`{ identifier?, latitude, longitude, radius, notifyOnEnter?, notifyOnExit?, state? }`.
`startGeofencingAsync(taskName, regions?)`, `stopGeofencingAsync(name)`,
`hasStartedGeofencingAsync(name)`, `requestForegroundPermissionsAsync()` **then**
`requestBackgroundPermissionsAsync()` (Android 11+ opens system settings; explain first).
Limits enforced in code: iOS **20** regions, Android **100** — past either, the OS silently drops
the extras, so the app must refuse to over-register and say which alarms are not armed.

**expo-task-manager 57.0.18** — `TaskManager.defineTask<T>(name, executor)` at module scope;
the body is `{ data, error, executionInfo }`. `isTaskRegisteredAsync`, `unregisterTaskAsync`,
`getTaskOptionsAsync`. The geofencing task receives
`{ eventType: GeofencingEventType, region: LocationRegion }`.

**expo-notifications 57.0.19** — a foreground handler must return
`{ shouldShowBanner, shouldShowList, shouldPlaySound, shouldSetBadge }` (`shouldShowAlert` is
deprecated). Schedule with
`{ trigger: { type: SchedulableTriggerInputTypes.TIME_INTERVAL | DATE, seconds | date, channelId?, repeats? } }`;
create the Android channel with `setNotificationChannelAsync(id, { name, importance: AndroidImportance.HIGH })`.
Note the documented Android quirk: `shouldPlaySound: false` also suppresses the heads-up banner.

**expo-network 57.0.2** — `useNetworkState(): { type?, isConnected?, isInternetReachable? }` plus
`addNetworkStateListener`. `isInternetReachable` equals `isConnected` on iOS.

**Background budget** — keep the geofence task under ~30 s: reuse `withTemporaryDatabase()`, set
`syncMaxPagesPerEntity` low, and let the foreground pass finish the backfill.

---

## 6. Known limitations (deliberate, documented)

- **Timezone**: GTFS times are interpreted in the device's local timezone — correct for a commuter
  riding in the agency's timezone, which is the app's case. Per-feed `agency_timezone` conversion is
  a follow-up, not a correctness bug for a single-city deployment.
- **`stop_times` is synced in full.** For metro-scale feeds (millions of rows) the next step is a
  server-side "stop_times for stops within N km" endpoint; the transport interface already allows it.
- **No GTFS-ZIP importer.** Supabase is the feed of record; `SyncTransport` is the seam where a ZIP
  or GTFS-Realtime source would slot in.
- **Web** runs the whole app but geofencing is unavailable (`maxGeofencesForPlatform('web') === 0`);
  `expo-sqlite` on web needs the COOP/COEP headers set in `metro.config.js`, which are dev-server
  only — a deployed web build must set them at the CDN.
