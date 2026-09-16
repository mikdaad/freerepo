/**
 * Deterministic in-process GTFS feed.
 *
 * Two jobs:
 *  1. **Development without a backend.** With `EXPO_PUBLIC_USE_MOCK_GTFS=1` the entire app —
 *     sync engine included — runs against this feed, so UI work and demos never depend on Supabase
 *     being reachable, seeded, or awake.
 *  2. **Testing the real pipeline.** `scripts/verify-db.ts` drives the *actual* sync engine with
 *     this transport, which means cursor handling, batching, tombstone deletes and cursors are all
 *     exercised in CI — against the same code that runs on the device.
 *
 * The feed is generated from a seed, so two runs produce byte-identical rows. It deliberately
 * includes the nasty cases: trips running past midnight (`25:10:00`), a holiday service exception,
 * a soft-deleted stop, and enough rows to force multi-page pagination.
 */

import type {
  CalendarDateRow,
  CalendarRow,
  RouteRow,
  StopRow,
  StopTimeRow,
  SyncedRowMeta,
  TripRow,
} from '../db/types';
import { SyncError } from '../utils/errors';
import type { Coordinates } from '../utils/geo';
import { toServiceDate, addDays, formatGtfsTime } from '../utils/gtfsTime';
import type { PageRequest, SyncPage, SyncRow, SyncTransport } from './types';

export interface MockFeedOptions {
  /** Centre of the generated stop grid. Defaults to downtown Seattle. */
  readonly center?: Coordinates;
  /** Stops per side of the grid (4 → 16 stops). Default 4. */
  readonly gridSize?: number;
  /** Metres between neighbouring stops. Default 220. */
  readonly spacingMeters?: number;
  /** Minutes between consecutive trips on the same route/direction. Default 15. */
  readonly headwayMinutes?: number;
  /** First departure of the service day, as `HH:MM`. Default `05:00`. */
  readonly firstDeparture?: string;
  /** Last departure of the service day, as `HH:MM` — may exceed 24:00. Default `25:30`. */
  readonly lastDeparture?: string;
  /** How long a trip takes between two consecutive stops, in minutes. Default 3. */
  readonly hopMinutes?: number;
  /** Reference date used for calendar coverage. Defaults to today. */
  readonly today?: Date;
  /** Days of calendar coverage either side of `today`. Default 60. */
  readonly coverageDays?: number;
}

/** Entity names as the sync engine knows them. */
export type MockFeedEntity =
  'routes' | 'stops' | 'trips' | 'stop_times' | 'calendar' | 'calendar_dates';

export interface MockFeed {
  readonly routes: readonly RouteRow[];
  readonly stops: readonly (StopRow & { readonly deleted_at?: number | null })[];
  readonly trips: readonly TripRow[];
  readonly stopTimes: readonly StopTimeRow[];
  readonly calendar: readonly CalendarRow[];
  readonly calendarDates: readonly CalendarDateRow[];
  /** Rows for one entity, in `sync_version` order (the order the server would stream them). */
  getAll(entity: MockFeedEntity): readonly SyncRow[];
}

interface RouteBlueprint {
  readonly routeId: string;
  readonly shortName: string;
  readonly longName: string;
  readonly color: string;
  readonly headsigns: readonly [string, string];
}

const ROUTE_BLUEPRINTS: readonly RouteBlueprint[] = [
  {
    routeId: 'MOCK-R10',
    shortName: '10',
    longName: 'Capitol Hill — Downtown',
    color: '1E40AF',
    headsigns: ['Downtown Transit Center', 'Capitol Hill'],
  },
  {
    routeId: 'MOCK-R49',
    shortName: '49',
    longName: 'University District — Waterfront',
    color: '047857',
    headsigns: ['Waterfront', 'University District'],
  },
  {
    routeId: 'MOCK-R2L',
    shortName: 'L2',
    longName: 'Airport Link (local)',
    color: 'B45309',
    headsigns: ['Airport', 'City Center'],
  },
];

const WEEKDAY_SERVICE = 'MOCK-WEEKDAY';
const WEEKEND_SERVICE = 'MOCK-WEEKEND';
const HOLIDAY_SERVICE = 'MOCK-HOLIDAY';

const METERS_PER_DEGREE_LAT = 111_320;

/** `sync_version` allocation is global and monotonic — exactly like the server-side sequence. */
class VersionClock {
  private value = 0;

  next(): number {
    this.value += 1;
    return this.value;
  }
}

function stamp(clock: VersionClock, updatedAtMs: number): SyncedRowMeta {
  return { updated_at: updatedAtMs, sync_version: clock.next() };
}

/** `HH:MM` → seconds; tolerates `25:30` because that is a legitimate service-day offset. */
function parseClock(clock: string): number {
  const match = /^(\d{1,3}):([0-5]\d)$/.exec(clock);
  if (match === null) throw new RangeError(`Mock feed received a malformed clock: ${clock}`);
  return Number(match[1]) * 3600 + Number(match[2]) * 60;
}

export function buildMockFeed(options: MockFeedOptions = {}): MockFeed {
  const center = options.center ?? { latitude: 47.6062, longitude: -122.3321 };
  const gridSize = options.gridSize ?? 4;
  const spacing = options.spacingMeters ?? 220;
  const headwaySeconds = (options.headwayMinutes ?? 15) * 60;
  const hopSeconds = (options.hopMinutes ?? 3) * 60;
  const firstDeparture = parseClock(options.firstDeparture ?? '05:00');
  const lastDeparture = parseClock(options.lastDeparture ?? '25:30');
  const today = options.today ?? new Date();
  const coverageDays = options.coverageDays ?? 60;
  const clock = new VersionClock();
  const updatedAt = today.getTime();

  // --- Stops: a grid offset so real haversine distances vary across the set.
  const stops: StopRow[] = [];
  for (let row = 0; row < gridSize; row += 1) {
    for (let column = 0; column < gridSize; column += 1) {
      const index = row * gridSize + column;
      const stopId = `MOCK-S${String(index + 1).padStart(3, '0')}`;
      stops.push({
        stop_id: stopId,
        stop_name: `${['Pine', 'Union', 'Seneca', 'Yesler'][row % 4]} St & ${column + 1}${column === 0 ? 'st' : 'th'} Ave`,
        stop_code: `${1000 + index}`,
        stop_lat: center.latitude + (row * spacing) / METERS_PER_DEGREE_LAT,
        stop_lon:
          center.longitude +
          (column * spacing) /
            (METERS_PER_DEGREE_LAT * Math.cos((center.latitude * Math.PI) / 180)),
        location_type: 0,
        parent_station: null,
        ...stamp(clock, updatedAt),
      });
    }
  }

  const routes: RouteRow[] = ROUTE_BLUEPRINTS.map((blueprint) => ({
    route_id: blueprint.routeId,
    route_short_name: blueprint.shortName,
    route_long_name: blueprint.longName,
    route_type: 3,
    route_color: blueprint.color,
    route_text_color: 'FFFFFF',
    ...stamp(clock, updatedAt),
  }));

  // --- Calendar coverage around today, plus a holiday exception.
  const calendar: CalendarRow[] = [
    {
      service_id: WEEKDAY_SERVICE,
      monday: 1,
      tuesday: 1,
      wednesday: 1,
      thursday: 1,
      friday: 1,
      saturday: 0,
      sunday: 0,
      start_date: toServiceDate(addDays(today, -coverageDays)),
      end_date: toServiceDate(addDays(today, coverageDays)),
      ...stamp(clock, updatedAt),
    },
    {
      service_id: WEEKEND_SERVICE,
      monday: 0,
      tuesday: 0,
      wednesday: 0,
      thursday: 0,
      friday: 0,
      saturday: 1,
      sunday: 1,
      start_date: toServiceDate(addDays(today, -coverageDays)),
      end_date: toServiceDate(addDays(today, coverageDays)),
      ...stamp(clock, updatedAt),
    },
  ];

  const calendarDates: CalendarDateRow[] = [
    {
      service_id: WEEKDAY_SERVICE,
      // 4 July: no weekday service.
      date: `${today.getFullYear()}0704`,
      exception_type: 2,
      ...stamp(clock, updatedAt),
    },
    {
      service_id: HOLIDAY_SERVICE,
      date: `${today.getFullYear()}0704`,
      exception_type: 1,
      ...stamp(clock, updatedAt),
    },
  ];

  // --- Trips + stop times. Every route runs both directions all day, past midnight.
  const trips: TripRow[] = [];
  const stopTimes: StopTimeRow[] = [];

  for (const blueprint of ROUTE_BLUEPRINTS) {
    for (const direction of [0, 1] as const) {
      let tripIndex = 0;
      for (
        let departure = firstDeparture;
        departure <= lastDeparture;
        departure += headwaySeconds, tripIndex += 1
      ) {
        const tripId = `${blueprint.routeId}-${direction}-${String(tripIndex).padStart(3, '0')}`;
        // Weekends get the same trips on a different service id — cheap, and it exercises the
        // calendar_dates/calendar split end to end.
        const serviceId = direction === 0 ? WEEKDAY_SERVICE : WEEKEND_SERVICE;

        trips.push({
          trip_id: tripId,
          route_id: blueprint.routeId,
          service_id: serviceId,
          trip_headsign: blueprint.headsigns[direction],
          direction_id: direction,
          ...stamp(clock, updatedAt),
        });

        const sequence = [...stops.keys()];
        const ordered = direction === 0 ? sequence : sequence.reverse();

        ordered.forEach((stopIndex, position) => {
          const stop = stops[stopIndex];
          if (stop === undefined) return;
          const departureSeconds = departure + position * hopSeconds;
          const arrivalSeconds = Math.max(0, departureSeconds - 45);
          stopTimes.push({
            trip_id: tripId,
            stop_id: stop.stop_id,
            stop_sequence: position + 1,
            arrival_time: formatGtfsTime(arrivalSeconds),
            departure_time: formatGtfsTime(departureSeconds),
            arrival_seconds: arrivalSeconds,
            departure_seconds: departureSeconds,
            pickup_type: 0,
            ...stamp(clock, updatedAt),
          });
        });
      }
    }
  }

  // A soft-deleted stop: the client must remove it, and the FK cascade must remove its stop_times.
  const deletedStopIndex = stops.length - 1;
  const deletedStop = stops[deletedStopIndex];
  const deletedAt = updatedAt + 1;
  const stopsWithTombstone: (StopRow & { deleted_at?: number | null })[] = stops.map(
    (stop, index) => (index === deletedStopIndex ? { ...stop, deleted_at: deletedAt } : stop),
  );

  const stopTimesWithoutDeleted = stopTimes.filter(
    (row) => deletedStop === undefined || row.stop_id !== deletedStop.stop_id,
  );

  const byEntity: Record<MockFeedEntity, readonly SyncRow[]> = {
    routes,
    stops: stopsWithTombstone,
    trips,
    stop_times: stopTimesWithoutDeleted,
    calendar,
    calendar_dates: calendarDates,
  };

  return {
    routes,
    stops: stopsWithTombstone,
    trips,
    stopTimes: stopTimesWithoutDeleted,
    calendar,
    calendarDates,
    getAll(entity: MockFeedEntity): readonly SyncRow[] {
      return byEntity[entity];
    },
  };
}

export interface MockTransportOptions extends MockFeedOptions {
  /** Fail the first N fetches with a retryable error — exercises the backoff path. */
  readonly failFirstAttempts?: number;
  /** Artificial per-page latency in milliseconds. Default 0. */
  readonly pageLatencyMs?: number;
  /** Pre-built feed, when the caller wants to inspect it (the verification script does). */
  readonly feed?: MockFeed;
}

export interface MockTransport extends SyncTransport {
  readonly feed: MockFeed;
  /** Fetches attempted so far, including failures. */
  readonly requestCount: number;
}

/**
 * A `SyncTransport` over the generated feed, paging by `sync_version` exactly like PostgREST.
 */
export function createMockTransport(options: MockTransportOptions = {}): MockTransport {
  const feed = options.feed ?? buildMockFeed(options);
  let remainingFailures = options.failFirstAttempts ?? 0;
  let requestCount = 0;

  return {
    source: 'mock',
    feed,

    get requestCount(): number {
      return requestCount;
    },

    async fetchPage(request: PageRequest): Promise<SyncPage> {
      requestCount += 1;

      if (remainingFailures > 0) {
        remainingFailures -= 1;
        throw new SyncError('Simulated transient network failure (mock transport).', {
          code: 'SYNC_NETWORK',
          retryable: true,
          entity: request.entity,
          phase: 'fetch',
          attempt: requestCount,
        });
      }

      if (options.pageLatencyMs !== undefined && options.pageLatencyMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, options.pageLatencyMs));
      }

      if (request.signal?.aborted === true) {
        throw new SyncError('Sync cancelled.', { code: 'SYNC_ABORTED', retryable: false });
      }

      const rows = feed
        .getAll(request.entity)
        .filter((row) => row.sync_version > request.cursor)
        .sort((a, b) => a.sync_version - b.sync_version)
        .slice(0, request.limit);

      const last = rows.at(-1);
      return {
        entity: request.entity,
        rows,
        nextCursor: last === undefined ? null : last.sync_version,
        hasMore: rows.length >= request.limit,
        serverTime: Date.now(),
      };
    },
  };
}

/** Convenience for the dashboard's "sync" button when mock mode is on. */
export function createDefaultMockTransport(): MockTransport {
  return createMockTransport();
}
