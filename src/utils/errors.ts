/**
 * Typed error taxonomy.
 *
 * Every failure that crosses a module boundary in this app is one of these classes, so callers can
 * branch on `error.code` / `error.retryable` instead of string-matching messages. The sync engine
 * uses exactly those two fields to decide between "back off and retry" and "give up, surface it".
 */

export type AppErrorCode =
  // configuration / environment
  | 'CONFIG_INVALID'
  // local database
  | 'DB_OPEN_FAILED'
  | 'DB_MIGRATION_FAILED'
  | 'DB_QUERY_FAILED'
  | 'DB_CONSTRAINT_VIOLATION'
  // remote sync
  | 'SYNC_NETWORK'
  | 'SYNC_TIMEOUT'
  | 'SYNC_UNAUTHORIZED'
  | 'SYNC_RATE_LIMITED'
  | 'SYNC_SERVER'
  | 'SYNC_PAYLOAD_INVALID'
  | 'SYNC_IN_PROGRESS'
  | 'SYNC_ABORTED'
  // device capabilities
  | 'PERMISSION_DENIED'
  | 'SERVICE_DISABLED'
  | 'GEOFENCE_LIMIT_EXCEEDED'
  | 'TASK_UNAVAILABLE'
  // catch-all
  | 'UNKNOWN';

export interface AppErrorOptions {
  /** Machine-readable code. */
  code: AppErrorCode;
  /** Whether retrying the same operation could plausibly succeed. */
  retryable?: boolean;
  /** Lower-level error or payload that caused this one. */
  cause?: unknown;
  /** Extra structured context, safe to log (no secrets, no PII). */
  context?: Record<string, unknown>;
}

export class AppError extends Error {
  readonly code: AppErrorCode;
  readonly retryable: boolean;
  readonly context: Record<string, unknown>;
  /** Original throw value, kept for logging chains. */
  override readonly cause?: unknown;

  constructor(message: string, options: AppErrorOptions) {
    super(message);
    this.name = new.target.name;
    this.code = options.code;
    this.retryable = options.retryable ?? false;
    this.context = options.context ?? {};
    this.cause = options.cause;
    // Keeps `instanceof` working when a transpiler downgrades classes (Hermes/JSC safe).
    Object.setPrototypeOf(this, new.target.prototype);
  }

  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      code: this.code,
      message: this.message,
      retryable: this.retryable,
      context: this.context,
    };
  }
}

export class ConfigError extends AppError {
  constructor(message: string, options?: Omit<AppErrorOptions, 'code'>) {
    super(message, { ...options, code: 'CONFIG_INVALID' });
  }
}

export class DatabaseError extends AppError {
  constructor(message: string, options: Omit<AppErrorOptions, 'code'> & { code?: AppErrorCode }) {
    super(message, { code: 'DB_QUERY_FAILED', ...options });
  }
}

export class SyncError extends AppError {
  /** Which feed entity was being synced when this happened. */
  readonly entity?: string;
  /** Which phase of the pass failed. */
  readonly phase?: 'read-cursor' | 'fetch' | 'write' | 'commit';
  /** 1-based attempt counter. */
  readonly attempt?: number;

  constructor(
    message: string,
    options: AppErrorOptions & {
      entity?: string;
      phase?: 'read-cursor' | 'fetch' | 'write' | 'commit';
      attempt?: number;
    },
  ) {
    super(message, options);
    this.entity = options.entity;
    this.phase = options.phase;
    this.attempt = options.attempt;
  }
}

export class PermissionError extends AppError {
  constructor(message: string, options?: Omit<AppErrorOptions, 'code' | 'retryable'>) {
    super(message, { ...options, code: 'PERMISSION_DENIED', retryable: false });
  }
}

/** Narrows an unknown throw value into something loggable. */
export function serializeError(error: unknown): Record<string, unknown> {
  if (error instanceof AppError) return error.toJSON();
  if (error instanceof Error) {
    return { name: error.name, message: error.message, stack: error.stack };
  }
  return { name: 'NonError', message: String(error) };
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof AppError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

/** True when `error` is an AppError explicitly marked retryable. */
export function isRetryable(error: unknown): boolean {
  return error instanceof AppError && error.retryable;
}
