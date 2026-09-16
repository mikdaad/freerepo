/**
 * Identifier helpers.
 *
 * These are *unique*, not *unguessable*: `Math.random()` is not a cryptographic source and nothing
 * here is used as a security token. Alarm ids end up as iOS/Android geofence region identifiers,
 * which have a practical length limit and must be stable across app launches — hence the short,
 * URL-safe, prefixed format rather than a full UUID.
 */

const BASE36 = 36;

/** Short, sortable-ish, collision-resistant-within-a-device identifier. */
export function createShortId(prefix: string): string {
  const time = Date.now().toString(BASE36); // ~8 chars until the year 5000
  const random = Math.floor(Math.random() * 0xffffffff).toString(BASE36);
  return `${prefix}_${time}${random}`;
}

/** Category prefix for alarm ids, e.g. `alarm_...`. */
export const ALARM_ID_PREFIX = 'alarm';

export function createAlarmId(): string {
  return createShortId(ALARM_ID_PREFIX);
}

/**
 * Geofence region identifier handed to `Location.startGeofencingAsync()`.
 *
 * Constraints that shape this format:
 *  • iOS caps a monitored region identifier at 255 bytes and the OS keeps at most 20 of them.
 *  • Android restores regions from its own store after a reboot, so the string must be stable and
 *    unique — it is the only key the background task has to map a wake-up back to a database row.
 */
export function geofenceIdentifierForAlarm(alarmId: string, prefix: string): string {
  const identifier = `${prefix}${alarmId}`;
  if (identifier.length > 255) {
    throw new RangeError(`Geofence identifier too long: ${identifier.length} characters`);
  }
  return identifier;
}

/** Recovers the alarm id from a region identifier, or `null` for foreign regions. */
export function alarmIdFromGeofenceIdentifier(identifier: string, prefix: string): string | null {
  return identifier.startsWith(prefix) ? identifier.slice(prefix.length) : null;
}
