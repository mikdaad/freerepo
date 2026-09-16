# Transit Pulse

An **offline-first commuter transit app**. GTFS data is synced from Supabase into an on-device
SQLite database, so the departure board works in a tunnel, on a plane, or when the backend is down —
and geofenced wake-up alarms fire shortly before your stop, even with the app closed.

| Layer | Choice |
| --- | --- |
| Framework | React Native via **Expo SDK 57** (managed, New Architecture) |
| Language | TypeScript, `strict` + `noUncheckedIndexedAccess` |
| Navigation | Expo Router (typed routes) |
| Styling | NativeWind 4 (Tailwind) — dark + high-contrast outdoor themes |
| Local data | `expo-sqlite` (`SQLiteProvider`, migrations, change-listener live queries) |
| Background | `expo-task-manager` + `expo-location` geofencing → `expo-notifications` |
| Backend | Supabase (Postgres + PostgREST), read-only anon access under RLS |

## Quickstart

```bash
npm install
cp .env.example .env      # optional: fill in Supabase URL + anon key
npm run verify            # typecheck (app + scripts) + 75-check data-layer harness
npm start                 # press i / a, or scan the QR code
```

With an empty `.env` the app runs against `EXPO_PUBLIC_USE_MOCK_GTFS=1`’s deterministic in-process
feed — no backend required. Set `EXPO_PUBLIC_USE_MOCK_GTFS=0` and fill in the two Supabase values to
sync for real; apply `supabase/migrations/0001_gtfs_sync.sql` first.

## Status

- **Phase 1 — setup & config**: complete (`app.json`, Babel, Metro, Tailwind, tsconfig, ESLint).
- **Phase 2 — database & sync**: complete. Schema + migrations, typed repositories, Supabase sync
  engine, and a Node harness that exercises all of it against a real SQLite engine.
- **Phase 3 — background geofencing**: next.
- **Phase 4 — offline UI**: dashboard + stop/alarm screens with the Phase-2 status screen as the
  placeholder.

See [`docs/PHASE-1-2.md`](docs/PHASE-1-2.md) for the full breakdown, the decisions behind the schema
and sync protocol, verification output, and the verified SDK 57 API facts for the next phases.

## Project layout

```
app/                 Expo Router routes (root layout wires SQLiteProvider)
src/
  api/               Supabase client + schema types
  background/        task names, platform geofence limits (native-free on purpose)
  config/            statically-inlined EXPO_PUBLIC_* configuration
  data/              repositories over SqlExecutor (stops, departures, alarms, sync state)
  db/                schema, migrations, SQL builders, expo-sqlite adapters, useLiveQuery
  services/          app-facing sync service (picks Supabase vs mock)
  sync/              transport contract, engine, Supabase + mock transports, mappers
  utils/             errors, logger, geo, GTFS time semantics, ids
scripts/             Node verification harness (node:sqlite)
supabase/migrations/ server-side GTFS schema + sync plumbing
```

## Scripts

| Command | What it does |
| --- | --- |
| `npm start` | Expo dev server |
| `npm run verify` | App + script typechecks, then the SQLite/sync harness |
| `npm run verify:db` | The harness on its own (`tsx scripts/verify-db.ts`) |
| `npm run typecheck` | `tsc --noEmit` for the app |
| `npm run typecheck:scripts` | `tsc -p scripts/tsconfig.json` (Node types) |
| `npm run lint` | ESLint (flat config) |

## Data-flow in one paragraph

The dashboard asks `getDepartureBoard()` for departures at the nearest stop; that query reads only
the local SQLite file — stops are found with an indexed bounding-box scan ranked by haversine in JS,
service days are resolved from `calendar` + `calendar_dates`, and departures come from an indexed
`(stop_id, departure_seconds)` lookup that understands GTFS’s past-midnight `24:xx` times. A
background or foreground sync pulls rows from Supabase paged by a server-side `sync_version`
sequence, writing each page and its cursor in one transaction, so an interrupted sync simply resumes.
