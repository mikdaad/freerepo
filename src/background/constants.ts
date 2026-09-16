/**
 * Background execution constants.
 *
 * Deliberately free of any `expo-*` or `react-native` import: this module is read by the pure data
 * layer (alarm validation) and by the Node verification harness, both of which would break if they
 * pulled in a native module. Callers pass `Platform.OS` in themselves.
 */

/** TaskManager task name for the geofencing wake-up alarms. Must be stable across app versions. */
export const GEOFENCE_TASK_NAME = 'transit-pulse-geofence-alarms';

/**
 * TaskManager task name reserved for a future continuous location-update task
 * (`Location.startLocationUpdatesAsync`) used by live "next stop" tracking.
 */
export const LOCATION_UPDATE_TASK_NAME = 'transit-pulse-location-updates';

/** Android notification channel for alarm notifications. */
export const ALARM_NOTIFICATION_CHANNEL_ID = 'transit-alarms';

/**
 * Key used inside the `stop_alarms.geofence_identifier` column and inside the TaskManager payload.
 * Regions are identified by this string, so it must stay ≤ 100 characters (iOS limit) and unique.
 */
export const GEOFENCE_IDENTIFIER_PREFIX = 'tp-stop-';

/**
 * Platform ceiling on simultaneously monitored geofenced regions.
 *
 * iOS: Core Location documents 20 monitored regions per app. Exceeding it does not error — the
 *   system silently ignores the extra registrations, so the app must enforce the cap itself and
 *   tell the user which alarms are not armed.
 * Android: the platform ceiling is 100 regions per app, and anything past it also fails quietly.
 *
 * Both numbers are *hard* limits, so they are treated as such: never register more, never pretend
 * an alarm is armed when it is not.
 */
export const MAX_GEOFENCES_IOS = 20;
export const MAX_GEOFENCES_ANDROID = 100;

/**
 * Android additionally re-arms geofences after reboot only if the app holds
 * `RECEIVE_BOOT_COMPLETED` (declared in app.json) — worth knowing when debugging "my alarm
 * disappeared overnight".
 */
export function maxGeofencesForPlatform(platformOs: string): number {
  switch (platformOs) {
    case 'ios':
      return MAX_GEOFENCES_IOS;
    case 'android':
      return MAX_GEOFENCES_ANDROID;
    default:
      // Web (and any future platform): geofencing is unavailable, so the cap is zero.
      return 0;
  }
}

/** Radius bounds shared by the DB CHECK constraints and the alarm editor UI. */
export const MIN_ALARM_RADIUS_METERS = 100;
export const MAX_ALARM_RADIUS_METERS = 5_000;

/** Lead-time bounds: how early the wake-up notification fires before the stop. */
export const MIN_ALARM_LEAD_MINUTES = 0;
export const MAX_ALARM_LEAD_MINUTES = 60;

/**
 * How long a fired alarm stays quiet for, in milliseconds.
 * Geofences re-fire on every dwell/re-entry; a commuter does not want four "wake up" notifications
 * for one bus ride, so a fired alarm is snoozed for this window.
 */
export const ALARM_REARM_COOLDOWN_MS = 90_000;
