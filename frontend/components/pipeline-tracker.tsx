import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { PhaseState } from "@/lib/api";
import { cn } from "@/lib/utils";

function StatusIcon({ status }: { status: PhaseState["status"] }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-5 w-5 animate-spin text-blue-600" aria-label="Running" />;
    case "complete":
      return <CheckCircle2 className="h-5 w-5 text-green-600" aria-label="Complete" />;
    case "failed":
      return <XCircle className="h-5 w-5 text-red-600" aria-label="Failed" />;
    default:
      return <Circle className="h-5 w-5 text-muted-foreground/40" aria-label="Pending" />;
  }
}

/** One human-readable line per phase, extracted from the SSE `detail` payload. */
function PhaseDetail({ phase }: { phase: PhaseState }) {
  if (!phase.detail) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const d = phase.detail as Record<string, any>;
  let text: string | null = null;

  switch (phase.phase) {
    case 1:
      if (phase.status === "failed") {
        text = String(d.message ?? "Extraction failed.");
      } else if (d.summary) {
        text =
          `${d.summary.entities} geometry entities · ${d.summary.texts} texts · ` +
          `${d.summary.layers} layers · units: ${d.summary.units}` +
          (d.bypassed ? " · (geometry supplied directly — C# step bypassed)" : "");
      }
      break;
    case 2:
      if (phase.status === "failed") {
        text = String(d.message ?? "Semantic identification failed.");
      } else if (Array.isArray(d.building_lines)) {
        text =
          `Building: [${d.building_lines.join(", ")}] · ` +
          `Boundary: [${(d.boundary_lines ?? []).join(", ")}]`;
      }
      break;
    case 3:
      if (phase.status === "failed") {
        text = String(d.message ?? "Verification failed.");
      } else if (d.min_distance_m !== undefined) {
        text =
          `Calculated distance: ${d.min_distance_m} m — required: ` +
          `${d.required_distance_m} m → ${d.verdict}`;
      }
      break;
    case 4:
      if (phase.status === "failed") {
        text = String(d.message ?? "Report generation failed.");
      } else if (d.report_length !== undefined) {
        text = `Report drafted (${d.report_length} characters).`;
      }
      break;
  }

  if (!text) return null;
  return (
    <p
      className={cn(
        "mt-1 text-xs",
        phase.status === "failed" ? "text-red-600" : "text-muted-foreground"
      )}
    >
      {text}
    </p>
  );
}

export function PipelineTracker({ phases }: { phases: PhaseState[] }) {
  return (
    <ol className="space-y-1">
      {phases.map((phase, index) => (
        <li key={phase.phase} className="relative flex gap-3 pb-5 last:pb-0">
          {index < phases.length - 1 && (
            <span
              aria-hidden
              className="absolute left-[9px] top-6 h-[calc(100%-1.25rem)] w-px bg-border"
            />
          )}
          <div className="mt-0.5 shrink-0">
            <StatusIcon status={phase.status} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "text-sm font-semibold",
                  phase.status === "pending" && "text-muted-foreground"
                )}
              >
                Phase {phase.phase} · {phase.name}
              </span>
              <span className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                {phase.engine}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{phase.description}</p>
            <PhaseDetail phase={phase} />
          </div>
        </li>
      ))}
    </ol>
  );
}
