/**
 * Route lookups. Small, focused queries used by the departure board's route filter and by the
 * alarm editor ("only wake me for the 24").
 */

import type { SqlExecutor } from '../db/types';
import type { RouteSummary } from './types';

interface RouteRowShape {
  route_id: string;
  route_short_name: string | null;
  route_long_name: string | null;
  route_type: number | null;
  route_color: string | null;
  route_text_color: string | null;
}

function toSummary(row: RouteRowShape): RouteSummary {
  return {
    routeId: row.route_id,
    shortName: row.route_short_name,
    longName: row.route_long_name,
    routeType: row.route_type,
    color: row.route_color,
    textColor: row.route_text_color,
  };
}

/** GTFS `route_type`: 3 = bus. Used to sort the most useful routes first. */
const BUS_ROUTE_TYPE = 3;

export async function listRoutes(db: SqlExecutor, limit = 50): Promise<RouteSummary[]> {
  const rows = await db.getAllAsync<RouteRowShape>(
    `SELECT route_id, route_short_name, route_long_name, route_type, route_color, route_text_color
       FROM routes
      ORDER BY (route_type = ${BUS_ROUTE_TYPE}) DESC, route_short_name ASC
      LIMIT ?;`,
    [limit],
  );
  return rows.map(toSummary);
}

export async function getRouteSummary(
  db: SqlExecutor,
  routeId: string,
): Promise<RouteSummary | null> {
  const row = await db.getFirstAsync<RouteRowShape>(
    `SELECT route_id, route_short_name, route_long_name, route_type, route_color, route_text_color
       FROM routes
      WHERE route_id = ?;`,
    [routeId],
  );
  return row === null ? null : toSummary(row);
}

/**
 * Routes that actually serve a stop (distinct, with a departure count so the list can be ordered by
 * how useful each one is at this stop).
 */
export async function listRoutesServingStop(
  db: SqlExecutor,
  stopId: string,
  limit = 20,
): Promise<(RouteSummary & { departureCount: number })[]> {
  const rows = await db.getAllAsync<RouteRowShape & { departure_count: number }>(
    `SELECT r.route_id, r.route_short_name, r.route_long_name, r.route_type,
            r.route_color, r.route_text_color,
            COUNT(st.trip_id) AS departure_count
       FROM stop_times AS st
       JOIN trips  AS t ON t.trip_id = st.trip_id
       JOIN routes AS r ON r.route_id = t.route_id
      WHERE st.stop_id = ?
      GROUP BY r.route_id, r.route_short_name, r.route_long_name, r.route_type,
               r.route_color, r.route_text_color
      ORDER BY (r.route_type = ${BUS_ROUTE_TYPE}) DESC, departure_count DESC, r.route_short_name ASC
      LIMIT ?;`,
    [stopId, limit],
  );

  return rows.map((row) => ({ ...toSummary(row), departureCount: row.departure_count }));
}
