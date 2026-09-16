/**
 * Geodesic helpers.
 *
 * All math here is plain JavaScript rather than SQLite `sin()`/`cos()` calls on purpose: SQLite's
 * math functions are a compile-time option (`SQLITE_ENABLE_MATH_FUNCTIONS`) and are *not*
 * guaranteed to be present in every build shipping through the app stores. Instead the database
 * does what it is good at — an indexed bounding-box scan — and this module ranks the handful of
 * candidate rows that come back.
 */

export interface Coordinates {
  readonly latitude: number;
  readonly longitude: number;
}

/** Mean Earth radius in meters (IUGG). */
export const EARTH_RADIUS_METERS = 6_371_008.8;

const DEG_TO_RAD = Math.PI / 180;

/** Latitude span of one degree, in meters (~111.32 km everywhere). */
export const METERS_PER_DEGREE_LATITUDE = 111_320;

export interface BoundingBox {
  readonly minLat: number;
  readonly maxLat: number;
  readonly minLon: number;
  readonly maxLon: number;
  /** True when the box wraps the ±180° antimeridian and must be queried as two ranges. */
  readonly crossesAntimeridian: boolean;
}

/**
 * Bounding box around a point, sized so it contains every location within `radiusMeters`.
 * Latitude degrees are constant-width; longitude degrees shrink with `cos(latitude)`, and this
 * clamps the divisor so behaviour stays sane near the poles (and at latitude ±90 exactly).
 */
export function boundingBox(center: Coordinates, radiusMeters: number): BoundingBox {
  const latDelta = radiusMeters / METERS_PER_DEGREE_LATITUDE;
  const cosLat = Math.max(Math.cos(center.latitude * DEG_TO_RAD), 1e-6);
  const lonDelta = radiusMeters / (METERS_PER_DEGREE_LATITUDE * cosLat);

  const minLat = center.latitude - latDelta;
  const maxLat = center.latitude + latDelta;
  const rawMinLon = center.longitude - lonDelta;
  const rawMaxLon = center.longitude + lonDelta;

  return {
    minLat: Math.max(minLat, -90),
    maxLat: Math.min(maxLat, 90),
    minLon: rawMinLon < -180 ? rawMinLon + 360 : rawMinLon,
    maxLon: rawMaxLon > 180 ? rawMaxLon - 360 : rawMaxLon,
    crossesAntimeridian: rawMinLon < -180 || rawMaxLon > 180,
  };
}

/**
 * Great-circle distance in meters (haversine). Accurate to ~0.5% which is far beyond what
 * "which stop is closest" needs.
 */
export function haversineMeters(a: Coordinates, b: Coordinates): number {
  const lat1 = a.latitude * DEG_TO_RAD;
  const lat2 = b.latitude * DEG_TO_RAD;
  const deltaLat = lat2 - lat1;
  const deltaLon = (b.longitude - a.longitude) * DEG_TO_RAD;

  const sinHalfLat = Math.sin(deltaLat / 2);
  const sinHalfLon = Math.sin(deltaLon / 2);
  const h = sinHalfLat * sinHalfLat + Math.cos(lat1) * Math.cos(lat2) * sinHalfLon * sinHalfLon;

  // `min(1, ...)` guards the haversine singularity against float error.
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Walking distance is 15–25% longer than straight-line distance in a street grid. */
export function walkingDistanceMeters(straightLineMeters: number): number {
  return straightLineMeters * 1.25;
}

/** Rough walking time in minutes at ~1.35 m/s (brisk, backpack, crossing lights). */
export function walkingMinutes(straightLineMeters: number): number {
  return walkingDistanceMeters(straightLineMeters) / 1.35 / 60;
}

/** Formats a distance for glance-reading: `120 m`, `1.4 km`. */
export function formatDistance(meters: number): string {
  if (!Number.isFinite(meters)) return '--';
  if (meters < 1000) return `${Math.round(meters / 10) * 10} m`;
  return `${(meters / 1000).toFixed(1)} km`;
}

/** Validates a coordinate pair coming from any untrusted source (GPS, Supabase payload, DB). */
export function isValidCoordinates(value: {
  latitude?: unknown;
  longitude?: unknown;
}): value is Coordinates {
  const { latitude, longitude } = value;
  return (
    typeof latitude === 'number' &&
    typeof longitude === 'number' &&
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180
  );
}
