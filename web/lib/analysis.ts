/**
 * The contract between the cad2ai pipeline and this dashboard.
 *
 * `analysis.json` is produced by `python main.py analyze --task sheet_review`
 * (see `cad2ai/prompts.py` for the schema the model is asked to obey) and copied
 * here. Everything is parsed through `normalizeAnalysis` rather than trusted:
 * a model answer can omit a field, return a number as a string, hand back
 * `evidence` as a single string, or invent a severity label. The UI must render
 * the parts that are present and stay honest about the rest.
 */

export type Severity = "high" | "medium" | "low";

export type FindingBucket =
  | "missing_information"
  | "standards_issues"
  | "data_quality"
  | "complexity"
  | (string & {});

export type ReleaseVerdict = "release" | "release_with_comments" | "hold" | "unknown";

export interface Finding {
  id: string;
  bucket: FindingBucket;
  severity: Severity;
  title: string;
  detail: string;
  evidence: string[];
  recommendation: string;
}

export interface LayerFinding {
  layer: string;
  issue: string;
  evidence: string;
  /** Derived for sorting/colouring: which severity bucket this falls into. */
  severity: Severity;
}

export interface DimensionFinding {
  kind: string;
  count: number | null;
  issue: string;
  evidence: string;
}

export interface DisciplineCall {
  assigned: string | null;
  confirmed: boolean | null;
  comment: string | null;
}

export interface Analysis {
  drawing: string | null;
  discipline: DisciplineCall;
  confidence: number | null;
  findings: Finding[];
  layerFindings: LayerFinding[];
  dimensionFindings: DimensionFinding[];
  checksNotPossible: string[];
  dataGaps: string[];
  releaseRecommendation: ReleaseVerdict;
  releaseRecommendationRaw: string | null;
  effortHours: number | null;
  /** How this payload got here, shown in the header so nobody confuses a demo with a run. */
  origin: "mock" | "file";
  originLabel: string;
  warnings: string[];
}

export interface AnalysisStats {
  total: number;
  bySeverity: Record<Severity, number>;
  byBucket: Record<string, number>;
  blockers: number;
  evidenceLines: number;
}

const SEVERITY_ALIASES: Record<string, Severity> = {
  high: "high",
  critical: "high",
  blocker: "high",
  major: "high",
  severe: "high",
  "1": "high",
  medium: "medium",
  med: "medium",
  moderate: "medium",
  minor: "low",
  "2": "medium",
  low: "low",
  info: "low",
  cosmetic: "low",
  "3": "low",
  hint: "low",
};

export const BUCKET_LABELS: Record<string, string> = {
  missing_information: "Missing information",
  standards_issues: "Standards",
  data_quality: "Data quality",
  complexity: "Complexity",
  other: "Other",
};

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (typeof entry === "string") return entry.trim();
        if (entry && typeof entry === "object") {
          const record = entry as Record<string, unknown>;
          const parts = ["json.path", "path", "key", "evidence", "value", "detail", "note"]
            .map((field) => asString(record[field]))
            .filter(Boolean);
          if (parts.length) return parts.join(" ");
        }
        return asString(entry);
      })
      .filter((entry) => entry.length > 0);
  }
  const single = asString(value);
  if (!single) return [];
  // Models sometimes join evidence with "; " despite the schema.
  return single
    .split(/\s*[;\n]\s*/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const match = value.match(/-?\d+(\.\d+)?/);
    if (match) {
      const parsed = Number.parseFloat(match[0]);
      return Number.isFinite(parsed) ? parsed : null;
    }
  }
  return null;
}

function asBoolean(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  const text = asString(value).toLowerCase();
  if (!text) return null;
  if (["true", "yes", "1", "confirmed", "confirmed_by_review"].includes(text)) return true;
  if (["false", "no", "0", "not_confirmed", "unconfirmed"].includes(text)) return false;
  return null;
}

function normalizeSeverity(value: unknown): Severity {
  const key = asString(value).toLowerCase();
  return SEVERITY_ALIASES[key] ?? "low";
}

function normalizeVerdict(value: unknown): { verdict: ReleaseVerdict; raw: string | null } {
  const raw = asString(value) || null;
  const key = (raw ?? "").toLowerCase().replace(/[\s-]+/g, "_");
  if (!key) return { verdict: "unknown", raw };
  if (/^(hold|blocked?|reject|do_not_release|on_hold|revise)$/.test(key)) {
    return { verdict: "hold", raw };
  }
  if (/with_comments|conditional|comment/.test(key)) {
    return { verdict: "release_with_comments", raw };
  }
  if (/^(release|approved?|approve|ok|issue|clear|pass)$/.test(key)) {
    return { verdict: "release", raw };
  }
  return { verdict: "unknown", raw };
}

/** `json.path=value` strings get a human label; keep the raw string for the code block. */
export function evidencePath(entry: string): string {
  const match = entry.match(/^([a-zA-Z0-9_[\].-]+)=/);
  return match ? match[1] : "";
}

export function normalizeAnalysis(input: unknown): Analysis {
  const warnings: string[] = [];
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    warnings.push("payload was not a JSON object; showing the bundled sample instead");
    return { ...emptyAnalysis(), warnings };
  }
  const raw = input as Record<string, unknown>;

  const disciplineRaw = (raw.discipline ?? {}) as Record<string, unknown>;
  const discipline: DisciplineCall = {
    assigned: asString(disciplineRaw.assigned) || asString(disciplineRaw.primary) || null,
    confirmed: asBoolean(disciplineRaw.confirmed),
    comment: asString(disciplineRaw.comment) || null,
  };

  const findings: Finding[] = [];
  const rawFindings = Array.isArray(raw.findings) ? raw.findings : [];
  if (!Array.isArray(raw.findings) && raw.findings !== undefined) {
    warnings.push("`findings` was not an array and has been ignored");
  }
  rawFindings.forEach((entry, index) => {
    if (!entry || typeof entry !== "object") {
      warnings.push(`finding #${index + 1} was not an object and has been skipped`);
      return;
    }
    const record = entry as Record<string, unknown>;
    const detail = asString(record.detail) || asString(record.description) || asString(record.title);
    const title = asString(record.title) || detail || `Finding ${index + 1}`;
    findings.push({
      id: asString(record.id) || `F${index + 1}`,
      bucket: asString(record.bucket) || asString(record.category) || "other",
      severity: normalizeSeverity(record.severity ?? record.priority),
      title,
      detail: detail || title,
      evidence: asStringList(record.evidence),
      recommendation: asString(record.recommendation) || asString(record.action) || "No recommendation supplied.",
    });
  });

  const severityFromIssue = (text: string): Severity => {
    const lowered = text.toLowerCase();
    if (/locked|missing|undefined|not defined|no annotation|0 entities|empty|corrupt/.test(lowered)) return "high";
    if (/off\b|frozen|unused|inconsistent|mismatch|mixed/.test(lowered)) return "medium";
    return "low";
  };

  const layerFindings: LayerFinding[] = (Array.isArray(raw.layer_findings) ? raw.layer_findings : []).map(
    (entry, index) => {
      const record = (entry ?? {}) as Record<string, unknown>;
      const issue = asString(record.issue) || asString(record.detail) || "Flagged by the reviewer";
      return {
        layer: asString(record.layer) || asString(record.name) || `layer #${index + 1}`,
        issue,
        evidence: asStringList(record.evidence).join("  ") || "no evidence cited",
        severity: normalizeSeverity(record.severity) === "low" ? severityFromIssue(issue) : normalizeSeverity(record.severity),
      };
    },
  );

  const dimensionFindings: DimensionFinding[] = (
    Array.isArray(raw.dimension_findings) ? raw.dimension_findings : []
  ).map((entry, index) => {
    const record = (entry ?? {}) as Record<string, unknown>;
    const count = asNumber(record.count ?? record.affected);
    if (record.count !== undefined && count === null) {
      warnings.push(`dimension finding #${index + 1} had a non-numeric count`);
    }
    return {
      kind: asString(record.kind) || asString(record.type) || `dimension #${index + 1}`,
      count,
      issue: asString(record.issue) || "Flagged by the reviewer",
      evidence: asStringList(record.evidence).join("  ") || "no evidence cited",
    };
  });

  const confidenceRaw = asNumber(raw.confidence);
  let confidence = confidenceRaw;
  if (confidenceRaw !== null && confidenceRaw > 1) {
    // A model that answers "85" for 85% is common enough to normalise instead of rejecting.
    confidence = confidenceRaw / 100;
    warnings.push("`confidence` came in on a 0-100 scale and was rescaled to 0-1");
  }
  if (confidence !== null && (confidence < 0 || confidence > 1)) {
    warnings.push("`confidence` was outside 0-1 and is shown clamped");
    confidence = Math.max(0, Math.min(1, confidence));
  }

  const verdict = normalizeVerdict(raw.release_recommendation ?? raw.recommendation);

  return {
    drawing: asString(raw.drawing) || null,
    discipline,
    confidence,
    findings,
    layerFindings,
    dimensionFindings,
    checksNotPossible: asStringList(raw.checks_not_possible_from_data),
    dataGaps: asStringList(raw.data_gaps),
    releaseRecommendation: verdict.verdict,
    releaseRecommendationRaw: verdict.raw,
    effortHours: asNumber(raw.effort_hours_estimate ?? raw.effort_hours),
    origin: "file",
    originLabel: "",
    warnings,
  };
}

function emptyAnalysis(): Analysis {
  return {
    drawing: null,
    discipline: { assigned: null, confirmed: null, comment: null },
    confidence: null,
    findings: [],
    layerFindings: [],
    dimensionFindings: [],
    checksNotPossible: [],
    dataGaps: [],
    releaseRecommendation: "unknown",
    releaseRecommendationRaw: null,
    effortHours: null,
    origin: "mock",
    originLabel: "",
    warnings: [],
  };
}

export function analysisStats(analysis: Analysis): AnalysisStats {
  const bySeverity: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
  const byBucket: Record<string, number> = {};
  let evidenceLines = 0;
  for (const finding of analysis.findings) {
    bySeverity[finding.severity] += 1;
    byBucket[finding.bucket] = (byBucket[finding.bucket] ?? 0) + 1;
    evidenceLines += finding.evidence.length;
  }
  return {
    total: analysis.findings.length,
    bySeverity,
    byBucket,
    blockers: bySeverity.high,
    evidenceLines,
  };
}

export const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };
