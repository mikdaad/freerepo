/**
 * Client for the FastAPI orchestration backend.
 *
 * All requests go through relative URLs (`/backend/...`) which the Next.js
 * dev server rewrites to the backend origin (see next.config.mjs). This keeps
 * the browser free of hardcoded origins and avoids CORS entirely.
 */

export type Verdict = "PASS" | "FAIL";
export type PhaseStatus = "pending" | "running" | "complete" | "failed";

export interface PhaseInfo {
  phase: number;
  name: string;
  engine: string;
  description: string;
}

export interface PhaseState extends PhaseInfo {
  status: PhaseStatus;
  detail?: Record<string, unknown>;
}

export interface Verification {
  verdict: Verdict;
  min_distance_m: number;
  required_distance_m: number;
  margin_m: number;
  drawing_units: string;
  unit_factor_to_meters: number;
  distance_in_drawing_units: number;
  closest_point_building: [number, number] | null;
  closest_point_boundary: [number, number] | null;
  building_entity_ids: string[];
  boundary_entity_ids: string[];
  skipped_entity_ids: string[];
  warnings: string[];
}

export interface SemanticMappingResult {
  building_lines: string[];
  boundary_lines: string[];
  rationale: string;
}

export interface ComplianceResult {
  report_id: string;
  verdict: Verdict;
  source_file: string;
  created_at: string;
  verification: Verification;
  mapping: SemanticMappingResult;
  report_markdown: string;
  persisted_to_database: boolean;
  cad_metadata: Record<string, unknown>;
}

export interface SseEvent {
  event: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

export type PipelineTarget =
  | { kind: "dwg"; file: File }
  | { kind: "json"; file: File }
  | { kind: "sample" };

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/backend";

/**
 * POST to the pipeline endpoint and stream Server-Sent Events back,
 * invoking `onEvent` for every `event:`/`data:` pair.
 */
export async function streamPipeline(
  target: PipelineTarget,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  let url: string;
  let body: FormData | undefined;

  if (target.kind === "dwg") {
    url = `${API_BASE}/api/pipeline/run`;
    body = new FormData();
    body.append("file", target.file);
  } else if (target.kind === "json") {
    url = `${API_BASE}/api/pipeline/run-json`;
    body = new FormData();
    body.append("file", target.file);
  } else {
    url = `${API_BASE}/api/pipeline/run-sample`;
  }

  const response = await fetch(url, { method: "POST", body });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      /* response body was not JSON */
    }
    throw new Error(detail);
  }
  if (!response.body) {
    throw new Error("The server did not return a response stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separator = buffer.indexOf("\n\n");
    while (separator >= 0) {
      const block = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const event = parseSseBlock(block);
      if (event) onEvent(event);
      separator = buffer.indexOf("\n\n");
    }
  }
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;

  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: raw };
  }
}
