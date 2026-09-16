/**
 * Domain types — what the UI consumes.
 *
 * These are intentionally *not* the raw row types from `db/types.ts`: rows are snake_case to match
 * the feed, the domain is camelCase and carries derived values (distance, countdown, boarding
 * status) so that components stay dumb and cheap to render.
 */

export interface NearbyStop {
  readonly stopId: string;
  readonly stopName: string;
  /** The number printed on the physical stop pole, when the feed publishes one. */
  readonly stopCode: string | null;
  readonly latitude: number;
  readonly longitude: number;
  /** Straight-line metres from the commuter. */
  readonly distanceMeters: number;
  /** Estimated walking metres (straight line × 1.25 grid factor). */
  readonly walkingMeters: number;
  /** Estimated minutes on foot. */
  readonly walkingMinutes: number;
  readonly isFavorite: boolean;
}

export interface RouteSummary {
  readonly routeId: string;
  readonly shortName: string | null;
  readonly longName: string | null;
  readonly routeType: number | null;
  /** `#RRGGBB` without the leading `#`, exactly as GTFS publishes it. */
  readonly color: string | null;
  readonly textColor: string | null;
}

export interface Departure {
  readonly tripId: string;
  readonly stopId: string;
  readonly stopSequence: number;
  readonly serviceId: string | null;
  readonly route: RouteSummary;
  readonly headsign: string | null;
  readonly directionId: number | null;
  /** Minutes from now; can be slightly negative for a bus still boarding (within the grace window). */
  readonly minutesAway: number;
  /** `Due`, `4 min`, `1 h 12`. Pre-formatted because formatting is cheap here and layout is not. */
  readonly countdownLabel: string;
  /** GTFS service-day offset in seconds (`25:10:00` → 90 600). */
  readonly departureSeconds: number;
  /** Wall-clock label already adjusted for ≥24h times (`01:10 (+1)`). */
  readonly departureClock: string;
  /** `YYYYMMDD` of the service day this departure belongs to. */
  readonly serviceDate: string;
  /** `0` today, `-1` yesterday's post-midnight service. */
  readonly serviceDayOffset: number;
  /** True when the trip is boarding right now (within the grace window). */
  readonly isBoarding: boolean;
}

export interface DepartureBoard {
  readonly stopId: string;
  readonly stop: NearbyStop | null;
  readonly generatedAt: number;
  /** Service dates that were consulted — surfaced in the debug view. */
  readonly serviceDates: readonly string[];
  readonly departures: readonly Departure[];
  /** True when a feed row exists but the calendar produced no service for these dates. */
  readonly noServiceToday: boolean;
}

export interface StopSearchResult {
  readonly stopId: string;
  readonly stopName: string | null;
  readonly stopCode: string | null;
  readonly latitude: number;
  readonly longitude: number;
  readonly isFavorite: boolean;
}

export interface FavoriteStop extends StopSearchResult {
  readonly nickname: string | null;
}
