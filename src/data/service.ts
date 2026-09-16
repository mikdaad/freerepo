/**
 * Service-calendar lookups: "which `service_id`s are running on this date?"
 *
 * GTFS models scheduled service in two files:
 *   • `calendar`        — the weekly pattern plus an active date window.
 *   • `calendar_dates`  — one-off exceptions: holidays (type 2 = no service) and extra
 *                          services such as a marathon shuttle (type 1 = added).
 *
 * A departure board that ignores either file will confidently show a Sunday timetable on Christmas
 * Day, so both are always consulted.
 */

import { buildActiveServiceIdsQuery } from '../db/sql';
import type { SqlExecutor } from '../db/types';
import {
  GTFS_WEEKDAY_COLUMNS,
  parseServiceDate,
  weekdayColumn,
  type GtfsWeekdayColumn,
} from '../utils/gtfsTime';

/**
 * Service ids active on `serviceDate` (`YYYYMMDD`).
 *
 * Returns `null` when the feed ships no calendar data at all — a legitimate (if unusual) situation
 * for feeds that encode service days in `trips.service_id` alone. The caller then skips the service
 * filter entirely rather than showing an empty board. An empty array means the opposite:
 * a calendar exists and nothing runs that day.
 */
export async function getActiveServiceIds(
  db: SqlExecutor,
  serviceDate: string,
): Promise<string[] | null> {
  const date = parseServiceDate(serviceDate);
  if (date === null) {
    throw new RangeError(`Invalid GTFS service date: ${JSON.stringify(serviceDate)}`);
  }

  const weekday: GtfsWeekdayColumn = weekdayColumn(date);
  const query = buildActiveServiceIdsQuery(serviceDate, weekday);
  const rows = await db.getAllAsync<{ service_id: string }>(query.sql, query.params);

  if (rows.length > 0) return rows.map((row) => row.service_id);

  return (await hasAnyCalendarData(db)) ? [] : null;
}

/** True when either calendar table carries at least one row. */
export async function hasAnyCalendarData(db: SqlExecutor): Promise<boolean> {
  const row = await db.getFirstAsync<{ has_calendar: number }>(
    `SELECT CASE
              WHEN EXISTS (SELECT 1 FROM calendar LIMIT 1)
                OR EXISTS (SELECT 1 FROM calendar_dates LIMIT 1)
              THEN 1 ELSE 0
            END AS has_calendar;`,
  );
  return row?.has_calendar === 1;
}

export interface CalendarCoverage {
  readonly serviceCount: number;
  /** Earliest active start date across all services, `YYYYMMDD`. */
  readonly startDate: string | null;
  /** Latest active end date, `YYYYMMDD`. */
  readonly endDate: string | null;
  readonly exceptionCount: number;
}

/**
 * Feed coverage, for the "your data is 40 days old" banner on the sync screen.
 * Cheap enough to run on mount: three aggregate queries over tiny tables.
 */
export async function getCalendarCoverage(db: SqlExecutor): Promise<CalendarCoverage> {
  const row = await db.getFirstAsync<{
    service_count: number;
    start_date: string | null;
    end_date: string | null;
  }>(
    `SELECT COUNT(*)          AS service_count,
            MIN(start_date)   AS start_date,
            MAX(end_date)     AS end_date
       FROM calendar;`,
  );
  const exceptions = await db.getFirstAsync<{ exception_count: number }>(
    'SELECT COUNT(*) AS exception_count FROM calendar_dates;',
  );

  return {
    serviceCount: row?.service_count ?? 0,
    startDate: row?.start_date ?? null,
    endDate: row?.end_date ?? null,
    exceptionCount: exceptions?.exception_count ?? 0,
  };
}

/** Exposed for tests and the debug screen: the weekday column a `YYYYMMDD` maps onto. */
export function weekdayColumnForServiceDate(serviceDate: string): GtfsWeekdayColumn | null {
  const date = parseServiceDate(serviceDate);
  return date === null ? null : weekdayColumn(date);
}

export { GTFS_WEEKDAY_COLUMNS };
