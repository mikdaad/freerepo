/**
 * Wire → row mappers.
 *
 * The backend speaks PostgREST/Postgres (`timestamptz` as ISO strings, `bigint` sometimes as
 * strings, `numeric` as strings); the local database speaks milliseconds and numbers. Converting in
 * one place means a malformed row is caught here, once, with a precise error, instead of surfacing
 * as `NaN` inside a query later.
 *
 * These functions are deliberately total: an unexpected value becomes `null`, never `NaN`, because a
 * single bad row must not abort an entire sync pass.
 */

import type {
  CalendarDateRow,
  CalendarRow,
  RouteRow,
  StopRow,
  StopTimeRow,
  TripRow,
} from '../db/types';
import type {
  GtfsCalendarDateRecord,
  GtfsCalendarRecord,
  GtfsRouteRecord,
  GtfsStopRecord,
  GtfsStopTimeRecord,
  GtfsTripRecord,
} from '../api/database.types';
import { parseGtfsTime } from '../utils/gtfsTime';

/** ISO-8601 or epoch input → milliseconds. Returns `null` rather than `NaN`. */
export function toEpochMs(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** PostgREST may serialise `bigint` and `numeric` as strings. */
export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** `YYYYMMDD` strings pass through validated; anything else becomes `null`. */
export function toServiceDateString(value: unknown): string | null {
  return typeof value === 'string' && /^\d{8}$/.test(value) ? value : null;
}

function toStringOrNull(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return typeof value === 'string' ? value : String(value);
}

/** GTFS tint colours reach the UI as `RRGGBB`; strip stray `#` and reject junk. */
function normalizeColor(value: unknown): string | null {
  const raw = toStringOrNull(value);
  if (raw === null) return null;
  const cleaned = raw.replace(/^#/, '').toUpperCase();
  return /^[0-9A-F]{6}$/.test(cleaned) ? cleaned : null;
}

export function mapRouteRecord(record: GtfsRouteRecord): RouteRow {
  return {
    route_id: record.route_id,
    route_short_name: toStringOrNull(record.route_short_name),
    route_long_name: toStringOrNull(record.route_long_name),
    route_type: toFiniteNumber(record.route_type),
    route_color: normalizeColor(record.route_color),
    route_text_color: normalizeColor(record.route_text_color),
    updated_at: toEpochMs(record.updated_at) ?? 0,
    sync_version: toFiniteNumber(record.sync_version) ?? 0,
  };
}

export function mapStopRecord(record: GtfsStopRecord): StopRow {
  const latitude = toFiniteNumber(record.stop_lat);
  const longitude = toFiniteNumber(record.stop_lon);

  if (latitude === null || longitude === null) {
    throw new TypeError(`Stop ${record.stop_id} has non-numeric coordinates`);
  }

  return {
    stop_id: record.stop_id,
    stop_name: toStringOrNull(record.stop_name),
    stop_code: toStringOrNull(record.stop_code),
    stop_lat: latitude,
    stop_lon: longitude,
    location_type: toFiniteNumber(record.location_type),
    parent_station: toStringOrNull(record.parent_station),
    updated_at: toEpochMs(record.updated_at) ?? 0,
    sync_version: toFiniteNumber(record.sync_version) ?? 0,
  };
}

export function mapTripRecord(record: GtfsTripRecord): TripRow {
  return {
    trip_id: record.trip_id,
    route_id: record.route_id,
    service_id: record.service_id,
    trip_headsign: toStringOrNull(record.trip_headsign),
    direction_id: toFiniteNumber(record.direction_id),
    updated_at: toEpochMs(record.updated_at) ?? 0,
    sync_version: toFiniteNumber(record.sync_version) ?? 0,
  };
}

/**
 * Stop times are the hot table, so the derived integer seconds are computed here — at write time —
 * rather than on every dashboard query.
 */
export function mapStopTimeRecord(record: GtfsStopTimeRecord): StopTimeRow {
  const arrivalTime = toStringOrNull(record.arrival_time);
  const departureTime = toStringOrNull(record.departure_time);

  return {
    trip_id: record.trip_id,
    stop_id: record.stop_id,
    stop_sequence: toFiniteNumber(record.stop_sequence) ?? 0,
    arrival_time: arrivalTime,
    departure_time: departureTime,
    arrival_seconds: parseGtfsTime(arrivalTime),
    departure_seconds: parseGtfsTime(departureTime ?? arrivalTime),
    pickup_type: toFiniteNumber(record.pickup_type),
    updated_at: toEpochMs(record.updated_at) ?? 0,
    sync_version: toFiniteNumber(record.sync_version) ?? 0,
  };
}

export function mapCalendarRecord(record: GtfsCalendarRecord): CalendarRow {
  const startDate = toServiceDateString(record.start_date);
  const endDate = toServiceDateString(record.end_date);
  if (startDate === null || endDate === null) {
    throw new TypeError(`Calendar ${record.service_id} has malformed start/end dates`);
  }

  return {
    service_id: record.service_id,
    monday: toFiniteNumber(record.monday) ?? 0,
    tuesday: toFiniteNumber(record.tuesday) ?? 0,
    wednesday: toFiniteNumber(record.wednesday) ?? 0,
    thursday: toFiniteNumber(record.thursday) ?? 0,
    friday: toFiniteNumber(record.friday) ?? 0,
    saturday: toFiniteNumber(record.saturday) ?? 0,
    sunday: toFiniteNumber(record.sunday) ?? 0,
    start_date: startDate,
    end_date: endDate,
    updated_at: toEpochMs(record.updated_at) ?? 0,
    sync_version: toFiniteNumber(record.sync_version) ?? 0,
  };
}

export function mapCalendarDateRecord(record: GtfsCalendarDateRecord): CalendarDateRow {
  const date = toServiceDateString(record.date);
  if (date === null) {
    throw new TypeError(`calendar_dates row for ${record.service_id} has a malformed date`);
  }

  return {
    service_id: record.service_id,
    date,
    exception_type: toFiniteNumber(record.exception_type) ?? 0,
    updated_at: toEpochMs(record.updated_at) ?? 0,
    sync_version: toFiniteNumber(record.sync_version) ?? 0,
  };
}
