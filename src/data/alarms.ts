/**
 * Wake-up alarm persistence.
 *
 * An "alarm" is a saved intent: *notify me when I get near stop X*. It is stored locally, survives
 * restarts, and is the source of truth from which the geofence regions are derived. The platform
 * registration lives in src/background (Phase 3) and always re-reads this table before touching the
 * OS — the OS is never treated as the database.
 */

import {
  ALARM_REARM_COOLDOWN_MS,
  GEOFENCE_IDENTIFIER_PREFIX,
  MAX_ALARM_LEAD_MINUTES,
  MAX_ALARM_RADIUS_METERS,
  MIN_ALARM_LEAD_MINUTES,
  MIN_ALARM_RADIUS_METERS,
} from '../background/constants';
import type { SqlExecutor, StopAlarmRow } from '../db/types';
import { createAlarmId, geofenceIdentifierForAlarm } from '../utils/ids';

export interface StopAlarm extends Omit<StopAlarmRow, 'enabled'> {
  readonly enabled: boolean;
  /** Denormalised for the list screen; `null` when the stop has not synced yet. */
  readonly stopName: string | null;
  readonly stopCode: string | null;
}

export interface CreateAlarmInput {
  readonly stopId: string;
  readonly routeId?: string | null;
  /** Defaults to the stop's name at call time; the UI usually pre-fills it. */
  readonly label?: string;
  readonly radiusMeters?: number;
  readonly leadTimeMinutes?: number;
}

export interface UpdateAlarmPatch {
  readonly label?: string;
  readonly radiusMeters?: number;
  readonly leadTimeMinutes?: number;
  readonly enabled?: boolean;
  readonly routeId?: string | null;
}

export class AlarmValidationError extends Error {
  readonly field: string;

  constructor(field: string, message: string) {
    super(message);
    this.name = 'AlarmValidationError';
    this.field = field;
  }
}

function assertRadius(radiusMeters: number): number {
  if (!Number.isFinite(radiusMeters)) {
    throw new AlarmValidationError('radiusMeters', 'Radius must be a number.');
  }
  const rounded = Math.round(radiusMeters);
  if (rounded < MIN_ALARM_RADIUS_METERS || rounded > MAX_ALARM_RADIUS_METERS) {
    throw new AlarmValidationError(
      'radiusMeters',
      `Radius must be between ${MIN_ALARM_RADIUS_METERS} m and ${MAX_ALARM_RADIUS_METERS} m.`,
    );
  }
  return rounded;
}

function assertLeadTime(leadTimeMinutes: number): number {
  if (!Number.isFinite(leadTimeMinutes)) {
    throw new AlarmValidationError('leadTimeMinutes', 'Lead time must be a number.');
  }
  const rounded = Math.round(leadTimeMinutes);
  if (rounded < MIN_ALARM_LEAD_MINUTES || rounded > MAX_ALARM_LEAD_MINUTES) {
    throw new AlarmValidationError(
      'leadTimeMinutes',
      `Lead time must be between ${MIN_ALARM_LEAD_MINUTES} and ${MAX_ALARM_LEAD_MINUTES} minutes.`,
    );
  }
  return rounded;
}

/** Inserts an alarm and returns the persisted row. Throws if the stop does not exist (FK). */
export async function createStopAlarm(
  db: SqlExecutor,
  input: CreateAlarmInput,
): Promise<StopAlarmRow> {
  const radiusMeters = assertRadius(input.radiusMeters ?? 400);
  const leadTimeMinutes = assertLeadTime(input.leadTimeMinutes ?? 5);
  const alarmId = createAlarmId();
  const now = Date.now();

  const stop = await db.getFirstAsync<{ stop_name: string | null; stop_code: string | null }>(
    'SELECT stop_name, stop_code FROM stops WHERE stop_id = ?;',
    [input.stopId],
  );
  if (stop === null) {
    throw new AlarmValidationError(
      'stopId',
      `Stop ${input.stopId} is not in the local database yet. Sync first, then set the alarm.`,
    );
  }

  const label = (input.label ?? stop.stop_name ?? stop.stop_code ?? input.stopId).trim();

  await db.runAsync(
    `INSERT INTO stop_alarms (
       alarm_id, stop_id, route_id, label, radius_meters, lead_time_minutes,
       enabled, geofence_identifier, created_at, updated_at, last_triggered_at, trigger_count
     ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, 0);`,
    [
      alarmId,
      input.stopId,
      input.routeId ?? null,
      label,
      radiusMeters,
      leadTimeMinutes,
      geofenceIdentifierForAlarm(alarmId, GEOFENCE_IDENTIFIER_PREFIX),
      now,
      now,
    ],
  );

  const created = await getStopAlarm(db, alarmId);
  if (created === null) throw new Error('Alarm insert reported success but the row is missing.');
  return created;
}

const ALARM_SELECT = `
  SELECT a.alarm_id, a.stop_id, a.route_id, a.label, a.radius_meters, a.lead_time_minutes,
         a.enabled, a.geofence_identifier, a.created_at, a.updated_at, a.last_triggered_at,
         a.trigger_count,
         s.stop_name AS stop_name,
         s.stop_code AS stop_code
    FROM stop_alarms AS a
    LEFT JOIN stops AS s ON s.stop_id = a.stop_id`;

interface AlarmJoinedRow extends StopAlarmRow {
  stop_name: string | null;
  stop_code: string | null;
}

function toStopAlarm(row: AlarmJoinedRow): StopAlarm {
  const { stop_name: stopName, stop_code: stopCode, ...rest } = row;
  return { ...rest, enabled: row.enabled === 1, stopName, stopCode };
}

export async function getStopAlarm(db: SqlExecutor, alarmId: string): Promise<StopAlarmRow | null> {
  return db.getFirstAsync<StopAlarmRow>(`${ALARM_SELECT} WHERE a.alarm_id = ?;`, [alarmId]);
}

export interface ListAlarmsOptions {
  readonly enabledOnly?: boolean;
  readonly stopId?: string;
}

export async function listStopAlarms(
  db: SqlExecutor,
  options: ListAlarmsOptions = {},
): Promise<StopAlarm[]> {
  const clauses: string[] = [];
  const params: (string | number)[] = [];

  if (options.enabledOnly === true) clauses.push('a.enabled = 1');
  if (options.stopId !== undefined) {
    clauses.push('a.stop_id = ?');
    params.push(options.stopId);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '';
  const rows = await db.getAllAsync<AlarmJoinedRow>(
    `${ALARM_SELECT} ${where} ORDER BY a.created_at DESC;`,
    params,
  );
  return rows.map(toStopAlarm);
}

export async function updateStopAlarm(
  db: SqlExecutor,
  alarmId: string,
  patch: UpdateAlarmPatch,
): Promise<StopAlarmRow | null> {
  const assignments: string[] = [];
  const params: (string | number | null)[] = [];

  if (patch.label !== undefined) {
    const label = patch.label.trim();
    if (label.length === 0) {
      throw new AlarmValidationError('label', 'Label cannot be empty.');
    }
    assignments.push('label = ?');
    params.push(label);
  }
  if (patch.radiusMeters !== undefined) {
    assignments.push('radius_meters = ?');
    params.push(assertRadius(patch.radiusMeters));
  }
  if (patch.leadTimeMinutes !== undefined) {
    assignments.push('lead_time_minutes = ?');
    params.push(assertLeadTime(patch.leadTimeMinutes));
  }
  if (patch.enabled !== undefined) {
    assignments.push('enabled = ?');
    params.push(patch.enabled ? 1 : 0);
  }
  if (patch.routeId !== undefined) {
    assignments.push('route_id = ?');
    params.push(patch.routeId);
  }

  if (assignments.length === 0) return getStopAlarm(db, alarmId);

  assignments.push('updated_at = ?');
  params.push(Date.now());
  params.push(alarmId);

  await db.runAsync(`UPDATE stop_alarms SET ${assignments.join(', ')} WHERE alarm_id = ?;`, params);
  return getStopAlarm(db, alarmId);
}

export async function deleteStopAlarm(db: SqlExecutor, alarmId: string): Promise<boolean> {
  const result = await db.runAsync('DELETE FROM stop_alarms WHERE alarm_id = ?;', [alarmId]);
  return result.changes > 0;
}

export async function deleteAllStopAlarms(db: SqlExecutor): Promise<number> {
  const result = await db.runAsync('DELETE FROM stop_alarms;');
  return result.changes;
}

/**
 * Records that an alarm actually fired.
 *
 * The cooldown check is part of the write so two background task invocations racing on the same
 * region cannot both notify: the `WHERE` clause only matches while the alarm is out of cooldown,
 * and `changes === 1` is the caller's permission to post a notification.
 */
export async function claimAlarmTrigger(
  db: SqlExecutor,
  alarmId: string,
  now = Date.now(),
): Promise<boolean> {
  const result = await db.runAsync(
    `UPDATE stop_alarms
        SET last_triggered_at = ?,
            trigger_count = trigger_count + 1,
            updated_at = updated_at
      WHERE alarm_id = ?
        AND enabled = 1
        AND (last_triggered_at IS NULL OR last_triggered_at < ?);`,
    [now, alarmId, now - ALARM_REARM_COOLDOWN_MS],
  );
  return result.changes === 1;
}

/** How many alarms would need to be registered with the OS right now. */
export async function countEnabledAlarms(db: SqlExecutor): Promise<number> {
  const row = await db.getFirstAsync<{ count: number }>(
    'SELECT COUNT(*) AS count FROM stop_alarms WHERE enabled = 1;',
  );
  return row?.count ?? 0;
}

/**
 * The set of alarms to arm, most recent first.
 *
 * `limit` is the platform's region ceiling passed in by the caller (20 on iOS, 100 on Android).
 * Anything beyond it is *not* silently dropped: the caller renders those alarms as "not armed —
 * over the device limit" so the commuter is never misled about being woken up.
 */
export async function selectAlarmsToArm(db: SqlExecutor, limit: number): Promise<StopAlarm[]> {
  const alarms = await listStopAlarms(db, { enabledOnly: true });
  return alarms.slice(0, Math.max(0, limit));
}
