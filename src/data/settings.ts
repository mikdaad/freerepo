/**
 * Local key/value settings (SQLite-backed, *not* AsyncStorage).
 *
 * Kept tiny and typed: settings are read on every dashboard mount, so lookups are single-row
 * primary-key hits. JSON values are stored as text and parsed defensively — a corrupted value must
 * degrade to the fallback, never crash the boot path.
 */

import type { SqlExecutor } from '../db/types';

export const SETTING_KEYS = {
  /** `dark` | `outdoor` — the high-contrast theme switch. */
  themeMode: 'theme_mode',
  /** Last known position, cached so the dashboard can render instantly before GPS resolves. */
  lastLocation: 'last_location',
  /** Stop the commuter tapped "next bus" on most recently. */
  preferredStopId: 'preferred_stop_id',
  /** `1` once the location-permission explainer has been shown. */
  onboardingComplete: 'onboarding_complete',
  /** Epoch ms of the last successful sync, mirrored out of `sync_state` for cheap reads. */
  lastSyncAt: 'last_sync_at',
} as const;

export type SettingKey = (typeof SETTING_KEYS)[keyof typeof SETTING_KEYS];

export async function getSetting(db: SqlExecutor, key: SettingKey): Promise<string | null> {
  const row = await db.getFirstAsync<{ value: string }>(
    'SELECT value FROM app_settings WHERE key = ?;',
    [key],
  );
  return row?.value ?? null;
}

export async function setSetting(
  db: SqlExecutor,
  key: SettingKey,
  value: string | null,
): Promise<void> {
  if (value === null) {
    await db.runAsync('DELETE FROM app_settings WHERE key = ?;', [key]);
    return;
  }
  await db.runAsync(
    `INSERT INTO app_settings (key, value, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;`,
    [key, value, Date.now()],
  );
}

export async function getJsonSetting<T>(db: SqlExecutor, key: SettingKey, fallback: T): Promise<T> {
  const raw = await getSetting(db, key);
  if (raw === null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export async function setJsonSetting(
  db: SqlExecutor,
  key: SettingKey,
  value: unknown,
): Promise<void> {
  await setSetting(db, key, JSON.stringify(value));
}

export async function getBooleanSetting(
  db: SqlExecutor,
  key: SettingKey,
  fallback = false,
): Promise<boolean> {
  const raw = await getSetting(db, key);
  if (raw === null) return fallback;
  return raw === '1' || raw === 'true';
}

export async function setBooleanSetting(
  db: SqlExecutor,
  key: SettingKey,
  value: boolean,
): Promise<void> {
  await setSetting(db, key, value ? '1' : '0');
}

export interface CachedLocation {
  readonly latitude: number;
  readonly longitude: number;
  readonly accuracy: number | null;
  readonly capturedAt: number;
}

export async function getCachedLocation(db: SqlExecutor): Promise<CachedLocation | null> {
  return getJsonSetting<CachedLocation | null>(db, SETTING_KEYS.lastLocation, null);
}

export async function setCachedLocation(db: SqlExecutor, location: CachedLocation): Promise<void> {
  await setJsonSetting(db, SETTING_KEYS.lastLocation, location);
}

export type ThemeMode = 'dark' | 'outdoor';

export async function getThemeMode(db: SqlExecutor): Promise<ThemeMode> {
  const raw = await getSetting(db, SETTING_KEYS.themeMode);
  return raw === 'outdoor' ? 'outdoor' : 'dark';
}

export async function setThemeMode(db: SqlExecutor, mode: ThemeMode): Promise<void> {
  await setSetting(db, SETTING_KEYS.themeMode, mode);
}
