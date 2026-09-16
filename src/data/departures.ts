/**
 * The dashboard query: upcoming departures at one stop, computed entirely offline.
 *
 * Algorithm
 * ---------
 * 1. Enumerate the *service days* that can have a departure in the requested window
 *    (`serviceDayCandidates`) — usually one, two in the first hour after midnight.
 * 2. For each service day, resolve the active `service_id`s from `calendar` + `calendar_dates`.
 * 3. Run one indexed query per service day over `stop_times` (stop_id, departure_seconds).
 * 4. Merge, convert to "minutes from now" on the correct service-day clock, sort, trim.
 *
 * Nothing here touches the network. The only inputs are the local database and the device clock,
 * which is what makes the dashboard usable in a tunnel or on a plane.
 */

import { buildDeparturesQuery } from '../db/sql';
import type { SqlExecutor } from '../db/types';
import {
  formatCountdown,
  formatServiceClock,
  minutesUntil,
  serviceDayCandidates,
  type ServiceDayCandidate,
} from '../utils/gtfsTime';
import { getActiveServiceIds } from './service';
import type { Departure, DepartureBoard, NearbyStop, RouteSummary } from './types';

export interface DepartureQueryRow {
  trip_id: string;
  stop_sequence: number;
  departure_time: string | null;
  departure_seconds: number | null;
  service_id: string | null;
  trip_headsign: string | null;
  direction_id: number | null;
  route_id: string;
  route_short_name: string | null;
  route_long_name: string | null;
  route_type: number | null;
  route_color: string | null;
  route_text_color: string | null;
}

export interface GetDepartureBoardOptions {
  /** Reference instant. Defaults to now; injected by tests and previews. */
  readonly now?: Date;
  /** How far ahead to look, in minutes. Default 90 — enough for the next few buses. */
  readonly horizonMinutes?: number;
  /** Maximum departures returned. Default 12. */
  readonly limit?: number;
  /** Rows to fetch per service day before merging. Defaults to `limit * 3`. */
  readonly perDayLimit?: number;
  /** Attach the calling screen's already-computed nearby-stop record, if it has one. */
  readonly stop?: NearbyStop | null;
}

export async function getDepartureBoard(
  db: SqlExecutor,
  stopId: string,
  options: GetDepartureBoardOptions = {},
): Promise<DepartureBoard> {
  const now = options.now ?? new Date();
  const horizonMinutes = options.horizonMinutes ?? 90;
  const limit = options.limit ?? 12;
  const perDayLimit = options.perDayLimit ?? Math.max(limit * 3, 24);
  const graceMinutes = 1.5;

  const candidates = serviceDayCandidates(now, {
    graceSeconds: Math.round(graceMinutes * 60),
  });

  const collected: Departure[] = [];
  const serviceDates: string[] = [];
  let sawCalendar = false;
  /** Rows the database actually returned, before the horizon filter — see `noServiceToday`. */
  let rowsReturned = 0;

  for (const candidate of candidates) {
    serviceDates.push(candidate.serviceDate);

    const serviceIds = await getActiveServiceIds(db, candidate.serviceDate);
    if (serviceIds !== null) sawCalendar = true;

    const query = buildDeparturesQuery({
      stopId,
      serviceIds,
      minSeconds: candidate.windowStartSeconds,
      limit: perDayLimit,
    });
    if (query === null) continue;

    const rows = await db.getAllAsync<DepartureQueryRow>(query.sql, query.params);
    rowsReturned += rows.length;

    for (const row of rows) {
      const departure = toDeparture(row, candidate, options.stop ?? null);
      if (departure === null) continue;
      if (departure.minutesAway > horizonMinutes) continue;
      if (departure.minutesAway < -graceMinutes) continue;
      collected.push(departure);
    }
  }

  // Deduplicate: a trip that appears in two service days (possible in hand-edited feeds) would
  // otherwise be listed twice.
  const seen = new Set<string>();
  const departures = collected
    .sort((a, b) => a.minutesAway - b.minutesAway)
    .filter((departure) => {
      const key = `${departure.serviceDate}:${departure.tripId}:${departure.stopSequence}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, limit);

  return {
    stopId,
    stop: options.stop ?? null,
    generatedAt: now.getTime(),
    serviceDates,
    departures,
    // "No service today" means the calendar produced a service set but this stop has no upcoming
    // trip at all. Departures that exist but fall outside the horizon are a different message
    // ("nothing in the next 90 minutes") and must not be reported as "no service".
    noServiceToday: sawCalendar && rowsReturned === 0 && collected.length === 0,
  };
}

/**
 * Convenience wrapper used by the dashboard: board for the closest stop.
 * Returns `null` when the commuter is not near any stop with service.
 */
export async function getClosestStopBoard(
  db: SqlExecutor,
  stop: NearbyStop,
  options: GetDepartureBoardOptions = {},
): Promise<DepartureBoard> {
  return getDepartureBoard(db, stop.stopId, { ...options, stop });
}

function toDeparture(
  row: DepartureQueryRow,
  candidate: ServiceDayCandidate,
  stop: NearbyStop | null,
): Departure | null {
  const departureSeconds = row.departure_seconds;
  if (departureSeconds === null || !Number.isFinite(departureSeconds)) return null;

  const minutesAway = minutesUntil(departureSeconds, candidate);
  const route: RouteSummary = {
    routeId: row.route_id,
    shortName: row.route_short_name,
    longName: row.route_long_name,
    routeType: row.route_type,
    color: normalizeHexColor(row.route_color),
    textColor: normalizeHexColor(row.route_text_color),
  };

  return {
    tripId: row.trip_id,
    stopId: stop?.stopId ?? '',
    stopSequence: row.stop_sequence,
    serviceId: row.service_id,
    route,
    headsign: row.trip_headsign,
    directionId: row.direction_id,
    minutesAway,
    countdownLabel: formatCountdown(minutesAway),
    departureSeconds,
    departureClock: formatServiceClock(departureSeconds),
    serviceDate: candidate.serviceDate,
    serviceDayOffset: candidate.dayOffset,
    isBoarding: minutesAway <= 0.5,
  };
}

/** GTFS colours are `RRGGBB` without `#`; some feeds leak a leading `#` or lowercase. */
function normalizeHexColor(value: string | null): string | null {
  if (value === null) return null;
  const cleaned = value.trim().replace(/^#/, '');
  return /^[0-9a-fA-F]{6}$/.test(cleaned) ? cleaned.toUpperCase() : null;
}
