/**
 * Stop queries. Pure functions over `SqlExecutor` — no React, no Expo, fully unit-testable.
 */

import { buildNearbyStopsQuery } from '../db/sql';
import type { SqlExecutor, StopRow } from '../db/types';
import {
  haversineMeters,
  walkingDistanceMeters,
  walkingMinutes,
  type Coordinates,
} from '../utils/geo';
import type { FavoriteStop, NearbyStop, StopSearchResult } from './types';

export interface FindNearbyStopsOptions {
  /** Search radius in metres. Riders will walk ~400 m to a frequent stop; default 600 m. */
  readonly radiusMeters?: number;
  /** Maximum stops returned after ranking. */
  readonly limit?: number;
  /** Include entrances/stations (`location_type != 0`). Default: boardable stops only. */
  readonly includeNonBoardable?: boolean;
}

interface StopCandidateRow {
  stop_id: string;
  stop_name: string | null;
  stop_code: string | null;
  stop_lat: number;
  stop_lon: number;
  location_type: number | null;
  parent_station: string | null;
}

/**
 * Stops near a coordinate, ranked by true great-circle distance.
 *
 * Two-phase on purpose:
 *   1. SQLite does an indexed bounding-box scan (`idx_stops_geo`) — no math functions required,
 *      so this works on every SQLite build.
 *   2. JavaScript ranks the (small) candidate set with haversine and drops the box corners.
 *
 * Requires zero network calls by construction: it only ever touches the local database.
 */
export async function findNearbyStops(
  db: SqlExecutor,
  center: Coordinates,
  options: FindNearbyStopsOptions = {},
): Promise<NearbyStop[]> {
  const radiusMeters = options.radiusMeters ?? 600;
  const limit = options.limit ?? 10;

  const favorites = await getFavoriteStopIds(db);
  const query = buildNearbyStopsQuery(center, {
    radiusMeters,
    limit: limit * 4, // Over-fetch: the box is a superset of the circle.
    includeNonBoardable: options.includeNonBoardable ?? false,
  });

  const rows = await db.getAllAsync<StopCandidateRow>(query.sql, query.params);

  return rows
    .map((row) => {
      const distanceMeters = haversineMeters(center, {
        latitude: row.stop_lat,
        longitude: row.stop_lon,
      });
      return {
        stopId: row.stop_id,
        stopName: row.stop_name ?? row.stop_code ?? row.stop_id,
        stopCode: row.stop_code,
        latitude: row.stop_lat,
        longitude: row.stop_lon,
        distanceMeters,
        walkingMeters: walkingDistanceMeters(distanceMeters),
        walkingMinutes: walkingMinutes(distanceMeters),
        isFavorite: favorites.has(row.stop_id),
      } satisfies NearbyStop;
    })
    .filter((stop) => stop.distanceMeters <= radiusMeters)
    .sort((a, b) => a.distanceMeters - b.distanceMeters)
    .slice(0, limit);
}

/** Single stop by id, or null. */
export async function getStopById(db: SqlExecutor, stopId: string): Promise<StopRow | null> {
  return db.getFirstAsync<StopRow>(
    `SELECT stop_id, stop_name, stop_code, stop_lat, stop_lon, location_type, parent_station,
            updated_at, sync_version
       FROM stops
      WHERE stop_id = ?;`,
    [stopId],
  );
}

export interface SearchStopsOptions {
  readonly limit?: number;
  readonly includeNonBoardable?: boolean;
}

/**
 * Substring search over stop names and codes, for the "pick a stop" screen.
 *
 * `LIKE` wildcards inside the user's text are escaped with an explicit `ESCAPE '\'` clause —
 * otherwise typing `%` would match every stop in the feed.
 */
export async function searchStops(
  db: SqlExecutor,
  term: string,
  options: SearchStopsOptions = {},
): Promise<StopSearchResult[]> {
  const limit = options.limit ?? 25;
  const trimmed = term.trim();

  if (trimmed.length === 0) {
    return db
      .getAllAsync<StopCandidateRow>(
        `SELECT stop_id, stop_name, stop_code, stop_lat, stop_lon, location_type, parent_station
           FROM stops
          ${options.includeNonBoardable ? '' : 'WHERE (location_type IS NULL OR location_type = 0)'}
          ORDER BY stop_name ASC
          LIMIT ?;`,
        [limit],
      )
      .then((rows) => rows.map(toSearchResult));
  }

  const pattern = `%${escapeLikePattern(trimmed)}%`;
  const rows = await db.getAllAsync<StopCandidateRow>(
    `SELECT stop_id, stop_name, stop_code, stop_lat, stop_lon, location_type, parent_station
       FROM stops
      WHERE (stop_name LIKE ? ESCAPE '\\' OR stop_code LIKE ? ESCAPE '\\')
        ${options.includeNonBoardable ? '' : 'AND (location_type IS NULL OR location_type = 0)'}
      ORDER BY
        -- Exact code match first ("4312"), then prefix matches, then everything else.
        CASE WHEN stop_code = ? THEN 0
             WHEN stop_name LIKE ? ESCAPE '\\' THEN 1
             ELSE 2 END,
        stop_name ASC
      LIMIT ?;`,
    [pattern, pattern, trimmed, `${escapeLikePattern(trimmed)}%`, limit],
  );

  return rows.map(toSearchResult);
}

function toSearchResult(row: StopCandidateRow): StopSearchResult {
  return {
    stopId: row.stop_id,
    stopName: row.stop_name,
    stopCode: row.stop_code,
    latitude: row.stop_lat,
    longitude: row.stop_lon,
    isFavorite: false,
  };
}

function escapeLikePattern(value: string): string {
  return value.replace(/[\\%_]/g, (match) => `\\${match}`);
}

// ---------------------------------------------------------------------------------------------
// Favourites
// ---------------------------------------------------------------------------------------------

export async function getFavoriteStopIds(db: SqlExecutor): Promise<Set<string>> {
  const rows = await db.getAllAsync<{ stop_id: string }>('SELECT stop_id FROM favorite_stops;');
  return new Set(rows.map((row) => row.stop_id));
}

export async function listFavoriteStops(db: SqlExecutor): Promise<FavoriteStop[]> {
  const rows = await db.getAllAsync<{
    stop_id: string;
    nickname: string | null;
    stop_name: string | null;
    stop_code: string | null;
    stop_lat: number | null;
    stop_lon: number | null;
  }>(
    `SELECT f.stop_id        AS stop_id,
            f.nickname       AS nickname,
            s.stop_name      AS stop_name,
            s.stop_code      AS stop_code,
            s.stop_lat       AS stop_lat,
            s.stop_lon       AS stop_lon
       FROM favorite_stops AS f
       LEFT JOIN stops AS s ON s.stop_id = f.stop_id
      ORDER BY f.sort_order ASC, f.created_at ASC;`,
  );

  return rows.map((row) => ({
    stopId: row.stop_id,
    stopName: row.stop_name ?? row.stop_code ?? row.stop_id,
    stopCode: row.stop_code,
    latitude: row.stop_lat ?? 0,
    longitude: row.stop_lon ?? 0,
    nickname: row.nickname,
    isFavorite: true,
  }));
}

export async function setFavoriteStop(
  db: SqlExecutor,
  stopId: string,
  favorite: boolean,
  nickname: string | null = null,
): Promise<void> {
  if (favorite) {
    await db.runAsync(
      `INSERT INTO favorite_stops (stop_id, nickname, sort_order, created_at)
       VALUES (?, ?, 0, ?)
       ON CONFLICT (stop_id) DO UPDATE SET nickname = excluded.nickname;`,
      [stopId, nickname, Date.now()],
    );
    return;
  }
  await db.runAsync('DELETE FROM favorite_stops WHERE stop_id = ?;', [stopId]);
}
