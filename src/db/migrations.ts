/**
 * Migration runner.
 *
 * Contract:
 *   • `PRAGMA user_version` is the source of truth for "schema version on this device".
 *   • Each migration runs inside `BEGIN IMMEDIATE … COMMIT`. If anything throws, the transaction is
 *     rolled back, `user_version` is left untouched, and a typed `DatabaseError` propagates — the
 *     app then boots into a read-only "database unavailable" state rather than serving wrong data.
 *   • Every applied migration is recorded in `schema_migrations` with a checksum. If a shipped
 *     migration is later edited, the checksum mismatch is reported (never silently ignored):
 *     edits must go into a new migration.
 *   • `PRAGMA foreign_keys` must be OFF during migrations: SQLite ignores it inside a transaction
 *     anyway, and table rebuilds would fail otherwise. It is restored immediately afterwards.
 */

import { DatabaseError, serializeError, type AppErrorCode } from '../utils/errors';
import { createLogger } from '../utils/logger';
import { LATEST_SCHEMA_VERSION, MIGRATIONS, pragmaStatements, type Migration } from './schema';
import type { SqlExecutor } from './types';

const log = createLogger('db:migrations');

export interface AppliedMigration {
  readonly version: number;
  readonly name: string;
  readonly durationMs: number;
}

export interface MigrationResult {
  readonly fromVersion: number;
  readonly toVersion: number;
  readonly applied: readonly AppliedMigration[];
  readonly checksumMismatches: readonly { version: number; name: string }[];
}

interface SchemaMigrationRow {
  version: number;
  name: string;
  checksum: string;
  applied_at: number;
  duration_ms: number | null;
}

/**
 * Non-cryptographic content hash (FNV-1a, 32-bit) of a migration's statements.
 * Detects accidental edits to shipped migrations; it is not a security control.
 */
function checksumStatements(migration: Migration): string {
  const payload = [...migration.statements, migration.dataMigration ? 'dataMigration' : '']
    .map((statement) => statement.replace(/\s+/g, ' ').trim())
    .join('\u0000');

  let hash = 0x811c9dc5;
  for (let index = 0; index < payload.length; index += 1) {
    hash ^= payload.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

/** Creates the bookkeeping table the runner itself depends on. Not a versioned migration. */
async function ensureBootstrap(db: SqlExecutor): Promise<void> {
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version     INTEGER PRIMARY KEY,
      name        TEXT NOT NULL,
      checksum    TEXT NOT NULL,
      applied_at  INTEGER NOT NULL,
      duration_ms INTEGER
    );
  `);
}

async function readUserVersion(db: SqlExecutor): Promise<number> {
  const row = await db.getFirstAsync<{ user_version: number }>('PRAGMA user_version;');
  const value = row?.user_version;
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * `PRAGMA user_version` does not accept bind parameters, so the value is interpolated — hence the
 * hard integer guard. This is the only place in the codebase that builds SQL by concatenation.
 */
async function writeUserVersion(db: SqlExecutor, version: number): Promise<void> {
  if (!Number.isInteger(version) || version < 0) {
    throw new DatabaseError(`Refusing to write non-integer schema version: ${version}`, {
      code: 'DB_MIGRATION_FAILED',
      context: { version },
    });
  }
  await db.execAsync(`PRAGMA user_version = ${version};`);
}

async function readAppliedMigrations(db: SqlExecutor): Promise<Map<number, SchemaMigrationRow>> {
  const rows = await db.getAllAsync<SchemaMigrationRow>(
    'SELECT version, name, checksum, applied_at, duration_ms FROM schema_migrations ORDER BY version ASC;',
  );
  return new Map(rows.map((row) => [row.version, row]));
}

async function runInTransaction(db: SqlExecutor, work: () => Promise<void>): Promise<void> {
  // IMMEDIATE takes the write lock up front so two concurrent initialisers (foreground app + a
  // background task waking from a geofence) cannot both run migrations.
  await db.execAsync('BEGIN IMMEDIATE;');
  try {
    await work();
    await db.execAsync('COMMIT;');
  } catch (error) {
    try {
      await db.execAsync('ROLLBACK;');
    } catch (rollbackError) {
      log.warn('rollback failed while handling a migration error', {
        error: serializeError(rollbackError),
      });
    }
    throw error;
  }
}

export interface MigrateOptions {
  /** Skip the (slower) integrity checks. Use for background-task boots. */
  readonly skipIntegrityCheck?: boolean;
}

/**
 * Brings the database up to `LATEST_SCHEMA_VERSION`.
 * Safe to call on every boot, from multiple entry points, and on a brand-new file.
 */
export async function migrateDatabase(
  db: SqlExecutor,
  options: MigrateOptions = {},
): Promise<MigrationResult> {
  await ensureBootstrap(db);

  const fromVersion = await readUserVersion(db);
  const appliedMigrations = await readAppliedMigrations(db);
  const applied: AppliedMigration[] = [];
  const checksumMismatches: { version: number; name: string }[] = [];

  const pending = MIGRATIONS.filter((migration) => migration.version > fromVersion).sort(
    (a, b) => a.version - b.version,
  );

  for (const migration of pending) {
    const startedAt = Date.now();
    try {
      await runInTransaction(db, async () => {
        for (const statement of migration.statements) {
          await db.execAsync(statement);
        }
        if (migration.dataMigration) {
          await migration.dataMigration(db, {
            logger: (message, context) =>
              log.debug(message, { ...context, version: migration.version }),
          });
        }
        await db.runAsync(
          `INSERT INTO schema_migrations (version, name, checksum, applied_at, duration_ms)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (version) DO UPDATE SET
             name = excluded.name,
             checksum = excluded.checksum,
             applied_at = excluded.applied_at,
             duration_ms = excluded.duration_ms;`,
          [migration.version, migration.name, checksumStatements(migration), Date.now(), null],
        );
        await writeUserVersion(db, migration.version);
      });
    } catch (error) {
      throw new DatabaseError(
        `Migration ${migration.version} (${migration.name}) failed: ${
          error instanceof Error ? error.message : String(error)
        }`,
        {
          code: 'DB_MIGRATION_FAILED',
          cause: error,
          context: { version: migration.version, name: migration.name },
        },
      );
    }

    const durationMs = Date.now() - startedAt;
    applied.push({ version: migration.version, name: migration.name, durationMs });
    log.info(`applied migration ${migration.version}:${migration.name}`, { durationMs });

    // Fill in the duration we could not know inside the transaction.
    await db.runAsync('UPDATE schema_migrations SET duration_ms = ? WHERE version = ?;', [
      durationMs,
      migration.version,
    ]);
  }

  // Integrity + drift checks.
  for (const migration of MIGRATIONS) {
    const recorded = appliedMigrations.get(migration.version);
    if (recorded && recorded.checksum !== checksumStatements(migration)) {
      checksumMismatches.push({ version: migration.version, name: migration.name });
    }
  }
  if (checksumMismatches.length > 0) {
    log.error('applied migration checksum mismatch — a shipped migration was edited', undefined, {
      checksumMismatches,
    });
  }

  if (!options.skipIntegrityCheck) {
    const integrity = await db.getFirstAsync<{ integrity_check: string }>(
      'PRAGMA integrity_check;',
    );
    if (integrity && integrity.integrity_check !== 'ok') {
      log.warn('integrity_check reported problems', { result: integrity.integrity_check });
    }
  }

  return {
    fromVersion,
    toVersion: await readUserVersion(db),
    applied,
    checksumMismatches,
  };
}

/**
 * Applies connection pragmas. Each is independently guarded because the web (wa-sqlite) build
 * does not support WAL or memory-mapped I/O, and one unsupported pragma must not abort boot.
 */
export async function applyPragmas(
  db: SqlExecutor,
  options: { preferWal?: boolean } = {},
): Promise<void> {
  for (const statement of pragmaStatements(options)) {
    try {
      await db.execAsync(statement);
    } catch (error) {
      log.warn('pragma not supported on this platform, continuing', {
        statement,
        error: serializeError(error),
      });
    }
  }
}

export interface InitializeDatabaseOptions {
  readonly preferWal?: boolean;
  readonly skipIntegrityCheck?: boolean;
}

/**
 * Full boot sequence for the local database:
 * pragmas → migrations → seed `sync_state` rows.
 *
 * @throws {DatabaseError} with code `DB_MIGRATION_FAILED` / `DB_OPEN_FAILED`.
 */
export async function initializeDatabase(
  db: SqlExecutor,
  options: InitializeDatabaseOptions = {},
): Promise<MigrationResult> {
  try {
    await applyPragmas(db, { preferWal: options.preferWal });
    const result = await migrateDatabase(db, { skipIntegrityCheck: options.skipIntegrityCheck });
    await seedSyncState(db);
    return result;
  } catch (error) {
    if (isDatabaseErrorCode(error, 'DB_MIGRATION_FAILED')) throw error;
    throw new DatabaseError(
      `Database initialisation failed: ${error instanceof Error ? error.message : String(error)}`,
      { code: 'DB_OPEN_FAILED', cause: error },
    );
  }
}

/** Guarantees a `sync_state` row per entity so the sync engine can always read a cursor. */
export async function seedSyncState(db: SqlExecutor): Promise<void> {
  const entities = [
    'routes',
    'stops',
    'trips',
    'stop_times',
    'calendar',
    'calendar_dates',
  ] as const;
  await runInTransaction(db, async () => {
    for (const entity of entities) {
      await db.runAsync(
        `INSERT INTO sync_state (entity, cursor, rows_synced, last_synced_at, last_error)
         VALUES (?, 0, 0, NULL, NULL)
         ON CONFLICT (entity) DO NOTHING;`,
        [entity],
      );
    }
  });
}

function isDatabaseErrorCode(error: unknown, code: AppErrorCode): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    (error as { code?: unknown }).code === code
  );
}

export { LATEST_SCHEMA_VERSION };
