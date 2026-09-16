/**
 * GTFS time semantics.
 *
 * Two facts drive every function in this file:
 *
 * 1. GTFS `arrival_time` / `departure_time` are **not** clock times. They are offsets from the
 *    *noon-minus-12-hours of the service day*, written `HH:MM:SS`, and `HH` may exceed 24. A bus
 *    leaving at 00:20 on a trip that started the previous evening is `24:20:00`, and the GTFS spec
 *    is explicit that this is expected — *"times are measured from noon minus 12h of the service
 *    day"*. Comparing them as strings works only accidentally, so we store an integer
 *    `departure_seconds` alongside the raw text (see db/schema.ts migration 2).
 *
 * 2. A service day is not a calendar day. At 00:40 the departures the commuter cares about belong
 *    to *yesterday's* service day with times ≥ 86400 — hence `serviceDayCandidates()` below.
 *
 * Timezone note: we interpret all of this in the device's local timezone. That is correct when the
 * commuter is riding in the agency's timezone (the normal case) and is the behaviour GTFS static
 * feeds cannot express per-trip anyway. A per-feed `agency_timezone` conversion is a documented
 * follow-up, not a correctness bug for a single-city app.
 */

export const SECONDS_PER_MINUTE = 60;
export const SECONDS_PER_HOUR = 3_600;
export const SECONDS_PER_DAY = 86_400;

/** `HH:MM:SS` or `HH:MM`, both with 1–3 digit hours. Leading zeros are forgiven. */
const GTFS_TIME_PATTERN = /^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?$/;

/**
 * Parses a GTFS time into seconds after the service day's midnight.
 * Returns `null` for blank or malformed input rather than throwing — real feeds contain both.
 */
export function parseGtfsTime(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const trimmed = value.trim();
  if (trimmed === '') return null;

  const match = GTFS_TIME_PATTERN.exec(trimmed);
  if (!match) return null;

  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = match[3] === undefined ? 0 : Number(match[3]);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds)) {
    return null;
  }

  return hours * SECONDS_PER_HOUR + minutes * SECONDS_PER_MINUTE + seconds;
}

/** Inverse of `parseGtfsTime`, preserving ≥24h hours. `90600 -> "25:10:00"`. */
export function formatGtfsTime(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / SECONDS_PER_HOUR);
  const minutes = Math.floor((total % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const secs = total % SECONDS_PER_MINUTE;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

/**
 * Wall-clock label for a service-day offset, e.g. `25:10:00 -> "01:10"`.
 * The `+1` marker tells the UI it belongs to the next calendar day.
 */
export function formatServiceClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '--:--';
  const dayOffset = Math.floor(Math.max(0, seconds) / SECONDS_PER_DAY);
  const withinDay = Math.max(0, Math.floor(seconds)) % SECONDS_PER_DAY;
  const hours = Math.floor(withinDay / SECONDS_PER_HOUR);
  const minutes = Math.floor((withinDay % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const clock = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
  return dayOffset > 0 ? `${clock} (+${dayOffset})` : clock;
}

/** Seconds elapsed since the given instant's local midnight (0 – 86 399). */
export function secondsSinceLocalMidnight(date: Date): number {
  return (
    date.getHours() * SECONDS_PER_HOUR +
    date.getMinutes() * SECONDS_PER_MINUTE +
    Math.floor(date.getSeconds())
  );
}

/** Local calendar date as the GTFS `YYYYMMDD` service date. */
export function toServiceDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}${month}${day}`;
}

/** Parses a `YYYYMMDD` service date into a local-midnight `Date`. */
export function parseServiceDate(value: string): Date | null {
  if (!/^\d{8}$/.test(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(year, month - 1, day, 0, 0, 0, 0);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Calendar-day arithmetic that is safe across DST transitions. */
export function addDays(date: Date, days: number): Date {
  const next = new Date(date.getTime());
  next.setDate(next.getDate() + days);
  next.setHours(0, 0, 0, 0);
  return next;
}

export const GTFS_WEEKDAY_COLUMNS = [
  'sunday',
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
] as const;

export type GtfsWeekdayColumn = (typeof GTFS_WEEKDAY_COLUMNS)[number];

/**
 * Maps `Date#getDay()` onto the GTFS `calendar` column name.
 * Whitelisted (never interpolated from free text) because it ends up in SQL as an identifier.
 */
export function weekdayColumn(date: Date): GtfsWeekdayColumn {
  const index = date.getDay();
  const column = GTFS_WEEKDAY_COLUMNS[index];
  if (column === undefined) throw new RangeError(`Invalid weekday index: ${index}`);
  return column;
}

export interface ServiceDayCandidate {
  /** `YYYYMMDD` service date to match against `calendar` / `calendar_dates`. */
  readonly serviceDate: string;
  /** `0` for today, `-1` for yesterday — surfaced in the UI as "yesterday's service". */
  readonly dayOffset: number;
  /**
   * This instant, expressed on the service day's own clock.
   * 14:00 today → `50 400`; 14:00 with yesterday's service day → `136 800`.
   */
  readonly nowSeconds: number;
  /**
   * Lowest `departure_seconds` worth showing for this service day — `nowSeconds` minus a grace
   * period, so a bus that is boarding right now does not blink out of existence.
   */
  readonly windowStartSeconds: number;
}

export interface ServiceDayOptions {
  /** How far back to keep departures that have technically just left. Default 90s. */
  readonly graceSeconds?: number;
  /**
   * How far into the calendar day yesterday's service day is still worth *querying*.
   * Defaults to `POST_MIDNIGHT_SERVICE_WINDOW_SECONDS` (04:00).
   */
  readonly postMidnightWindowSeconds?: number;
}

/**
 * Until this time of day, yesterday's service day can still contain departures in the future —
 * feeds routinely schedule revenue trips out to `26:00`–`28:00`. Querying it is a single indexed
 * lookup that returns nothing when the feed has no night service, so the window is deliberately
 * generous rather than clever: being wrong here means showing an empty board to someone standing at
 * a night stop.
 */
export const POST_MIDNIGHT_SERVICE_WINDOW_SECONDS = 4 * SECONDS_PER_HOUR;

/**
 * The service days that can legitimately have a departure in the next few minutes.
 *
 * At 00:40 that is *two* days: today's early trips (`00:45`) and yesterday's post-midnight trips
 * (`24:45`, already rolling). At 14:00 it is just today.
 */
export function serviceDayCandidates(
  now: Date,
  options: ServiceDayOptions = {},
): ServiceDayCandidate[] {
  const graceSeconds = options.graceSeconds ?? 90;
  const windowSeconds = options.postMidnightWindowSeconds ?? POST_MIDNIGHT_SERVICE_WINDOW_SECONDS;
  const nowSeconds = secondsSinceLocalMidnight(now);

  const candidates: ServiceDayCandidate[] = [
    {
      serviceDate: toServiceDate(now),
      dayOffset: 0,
      nowSeconds,
      windowStartSeconds: Math.max(0, nowSeconds - graceSeconds),
    },
  ];

  // Yesterday's service day only matters while trips scheduled past 24:00:00 are still on the road.
  if (nowSeconds < windowSeconds) {
    const nowOnYesterday = SECONDS_PER_DAY + nowSeconds;
    candidates.push({
      serviceDate: toServiceDate(addDays(now, -1)),
      dayOffset: -1,
      nowSeconds: nowOnYesterday,
      windowStartSeconds: Math.max(0, nowOnYesterday - graceSeconds),
    });
  }

  return candidates;
}

/**
 * Minutes until a departure, measured on the candidate service day's clock.
 * Negative means it has already left.
 */
export function minutesUntil(departureSeconds: number, candidate: ServiceDayCandidate): number {
  return (departureSeconds - candidate.nowSeconds) / SECONDS_PER_MINUTE;
}

/** Human countdown: `Due`, `4 min`, `1 h 12`. */
export function formatCountdown(minutes: number): string {
  if (!Number.isFinite(minutes)) return '--';
  if (minutes <= 0.5) return 'Due';
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return remainder === 0 ? `${hours} h` : `${hours} h ${String(remainder).padStart(2, '0')}`;
}
