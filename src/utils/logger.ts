/**
 * Tiny structured logger.
 *
 * Why not `console.log` everywhere: background tasks (geofencing, sync) run in a JS context with no
 * dev tools attached, so the only way to debug "why did my alarm not fire" is a consistent,
 * timestamped, namespaced log line you can read from `npx expo start` output after the fact.
 *
 * Redaction: values whose key looks secret are replaced before printing. This app never logs keys,
 * but the guard keeps a careless `logger.debug('config', config)` from leaking one.
 */

import { serializeError } from './errors';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'silent';

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  silent: 100,
};

const SECRET_KEY_PATTERN = /key|token|secret|password|authorization|cookie|session/i;

/**
 * `__DEV__` exists in the Metro bundle but not under Node, and this module is shared with the
 * verification harness (scripts/verify-db.ts). Same code path, two runtimes.
 */
const isDevelopment: boolean =
  typeof __DEV__ === 'boolean' ? __DEV__ : process.env.NODE_ENV !== 'production';

let globalLevel: LogLevel = isDevelopment ? 'debug' : 'warn';

/** Change the minimum level emitted. Used by the debug screen and by the sync engine. */
export function setLogLevel(level: LogLevel): void {
  globalLevel = level;
}

export function getLogLevel(): LogLevel {
  return globalLevel;
}

function redact(value: unknown, depth = 0): unknown {
  if (depth > 4) return '[deep]';
  if (value === null || value === undefined) return value;
  if (value instanceof Error) return serializeError(value);
  if (Array.isArray(value)) return value.slice(0, 25).map((item) => redact(item, depth + 1));
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SECRET_KEY_PATTERN.test(key) ? '[redacted]' : redact(entry, depth + 1);
    }
    return out;
  }
  return value;
}

export interface Logger {
  debug(message: string, context?: Record<string, unknown>): void;
  info(message: string, context?: Record<string, unknown>): void;
  warn(message: string, context?: Record<string, unknown>): void;
  error(message: string, error?: unknown, context?: Record<string, unknown>): void;
  child(namespace: string): Logger;
}

function emit(
  namespace: string,
  level: Exclude<LogLevel, 'silent'>,
  message: string,
  context?: Record<string, unknown>,
): void {
  if (LEVEL_ORDER[level] < LEVEL_ORDER[globalLevel]) return;

  const stamp = new Date().toISOString().slice(11, 23);
  const prefix = `[${stamp}] ${level.toUpperCase().padEnd(5)} ${namespace}:`;
  const payload = context && Object.keys(context).length > 0 ? redact(context) : undefined;

  if (level === 'error') {
    if (payload) console.error(prefix, message, payload);
    else console.error(prefix, message);
  } else if (level === 'warn') {
    if (payload) console.warn(prefix, message, payload);
    else console.warn(prefix, message);
  } else if (payload) {
    console.log(prefix, message, payload);
  } else {
    console.log(prefix, message);
  }
}

export function createLogger(namespace: string): Logger {
  return {
    debug: (message, context) => emit(namespace, 'debug', message, context),
    info: (message, context) => emit(namespace, 'info', message, context),
    warn: (message, context) => emit(namespace, 'warn', message, context),
    error: (message, error, context) => {
      const detail =
        error === undefined ? context : { ...(context ?? {}), error: serializeError(error) };
      emit(namespace, 'error', message, detail);
    },
    child: (childNamespace) => createLogger(`${namespace}:${childNamespace}`),
  };
}

export const logger = createLogger('transit-pulse');
