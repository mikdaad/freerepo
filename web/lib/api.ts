/**
 * Client for the FastAPI service in `server.py`.
 *
 * Base URL resolution, in order:
 *   1. `NEXT_PUBLIC_API_BASE` when set (e.g. `http://localhost:8000`)
 *   2. `http://localhost:8000` when the page itself is served from localhost — the
 *      documented default in the task brief
 *   3. same-origin `/api/...`, which `next.config.mjs` rewrites to the backend
 *      (needed behind a proxy/host you cannot hard-code, e.g. a review box on the
 *      network or the sandbox preview)
 *
 * Nothing here throws on `ok: false`: the pipeline returns rich typed errors
 * (message/hint/retryable/exit code) and the UI shows all of it verbatim.
 */

import type { ReleaseVerdict } from "@/lib/analysis";

export const DEFAULT_API_BASE = "http://localhost:8000";

export function resolveApiBase(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_API_BASE ?? "").trim();
  if (fromEnv) return fromEnv.replace(/\/+$/, "");
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") return DEFAULT_API_BASE;
  }
  return "";
}

export function apiUrl(path: string, base = resolveApiBase()): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${base}${clean}`;
}

export interface ApiErrorBody {
  code?: string;
  error?: string;
  message: string;
  hint?: string | null;
  retryable?: boolean;
  exit_code?: number;
  status?: number;
  details?: Record<string, unknown>;
  known_tasks?: string[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly hint: string | null;
  readonly code: string | null;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;

  constructor(body: ApiErrorBody | undefined, status: number, fallbackMessage: string) {
    super(body?.message || fallbackMessage);
    this.name = "ApiError";
    this.status = body?.status ?? status;
    this.hint = body?.hint ?? null;
    this.code = body?.code ?? body?.error ?? null;
    this.retryable = Boolean(body?.retryable);
    this.details = body?.details ?? {};
  }
}

export interface HealthPayload {
  ok: boolean;
  service?: { version?: string; uptime_s?: number; log_level?: string };
  backends?: { platform?: string; ezdxf_version?: string; oda_installed?: boolean; xvfb_available?: boolean; notes?: string[] };
  deepseek?: {
    base_url?: string;
    model?: string;
    key_present?: boolean;
    json_mode?: boolean;
    thinking?: string;
    probe?: { ok?: boolean; message?: string };
  };
  autodesk?: { configured?: boolean; missing?: string[] };
  limits?: {
    max_upload_mb?: number;
    timeout_s?: number;
    concurrency?: number;
    active?: number;
    allowed_suffixes?: string[];
  };
  tasks?: string[];
  readiness?: { accepts_dxf?: boolean; accepts_dwg?: boolean; full_pipeline?: boolean };
}

export interface AnalyzeResponse {
  ok: boolean;
  run_id?: string;
  filename?: string;
  task?: string;
  mode?: string;
  dry_run?: boolean;
  elapsed_s?: number;
  size_bytes?: number;
  timings?: Record<string, number>;
  generated_at?: string;
  analysis?: unknown;
  summary?: Record<string, unknown>;
  payload?: {
    chars?: number | null;
    token_estimate?: number | null;
    token_budget?: number | null;
    degraded?: string[];
    truncations?: Record<string, number>;
    budget_exceeded_by?: number | null;
    prompt_tokens_actual?: number | null;
    counts?: Record<string, number>;
  };
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null;
  warnings?: string[];
  markdown?: string;
  artifact_dir?: string | null;
  artifact_urls?: Record<string, string>;
}

export const ACCEPTED_SUFFIXES = [".dwg", ".dxf"] as const;

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_SUFFIXES.some((suffix) => lower.endsWith(suffix));
}

export interface AnalyzeOptions {
  task?: string;
  brief?: string;
  /** Phases 1+2 only: build the payload without spending tokens. */
  dryRun?: boolean;
  /** Keep artifacts server-side so they can be re-fetched by run id. */
  keep?: boolean;
  signal?: AbortSignal;
  base?: string;
  /** Override for tests / non-localhost deployments. */
  fetchImpl?: typeof fetch;
}

async function parseBody(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    // A proxy that returned HTML is a common failure; keep the first line visible.
    return { message: text.slice(0, 400) };
  }
}

export interface HealthOptions {
  signal?: AbortSignal;
  probe?: boolean;
  base?: string;
  fetchImpl?: typeof fetch;
}

export async function fetchHealth(options: HealthOptions = {}): Promise<HealthPayload> {
  const doFetch = options.fetchImpl ?? fetch;
  const url = apiUrl(`/api/health${options.probe ? "?probe=1" : ""}`, options.base);
  const response = await doFetch(url, { signal: options.signal, headers: { accept: "application/json" } });
  if (!response.ok) throw new ApiError(undefined, response.status, `health check failed (${response.status})`);
  return (await parseBody(response)) as unknown as HealthPayload;
}

/**
 * Upload a drawing and wait for the analysis. A sheet review typically takes
 * 60-90 s (ODA conversion + extraction + one long model call), so callers should
 * show progress and allow cancellation via `signal`.
 */
export async function analyzeDrawing(file: File, options: AnalyzeOptions = {}): Promise<AnalyzeResponse> {
  const doFetch = options.fetchImpl ?? fetch;
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("task", options.task ?? "sheet_review");
  if (options.brief && options.brief.trim()) form.append("brief", options.brief.trim());
  form.append("dry_run", options.dryRun ? "1" : "0");
  form.append("keep", options.keep ? "1" : "0");
  form.append("include_markdown", "1");

  const response = await doFetch(apiUrl("/api/analyze", options.base), {
    method: "POST",
    body: form,
    signal: options.signal,
  });

  const parsed = await parseBody(response);
  const body = parsed as unknown as AnalyzeResponse & { error?: ApiErrorBody };
  if (!response.ok || body.ok === false) {
    const error = body.error ?? (parsed as unknown as ApiErrorBody);
    throw new ApiError(error, response.status, `analysis failed (HTTP ${response.status})`);
  }
  return body;
}

/** Fetch a kept artifact (analysis/markdown/payload) by run id. */
export interface ArtifactOptions {
  base?: string;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

export async function fetchArtifact(runId: string, artifact: string, options: ArtifactOptions = {}): Promise<string> {
  const doFetch = options.fetchImpl ?? fetch;
  const response = await doFetch(apiUrl(`/api/runs/${encodeURIComponent(runId)}/${artifact}`, options.base), {
    signal: options.signal,
  });
  if (!response.ok) {
    const parsed = await parseBody(response);
    throw new ApiError(
      parsed.error as unknown as ApiErrorBody | undefined,
      response.status,
      `could not fetch ${artifact} (HTTP ${response.status})`,
    );
  }
  return response.text();
}

export const VERDICT_COPY: Record<ReleaseVerdict, string> = {
  release: "cleared to release",
  release_with_comments: "release with comments",
  hold: "hold",
  unknown: "no verdict",
};
