import ReactMarkdown from "react-markdown";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ComplianceResult } from "@/lib/api";

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {sub ? <p className="text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

export function ComplianceResultView({ result }: { result: ComplianceResult }) {
  const pass = result.verdict === "PASS";
  const v = result.verification;

  return (
    <div className="space-y-4">
      <Card className={pass ? "border-success/60" : "border-destructive/60"}>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-3 text-lg">
              Determination
              <Badge
                variant={pass ? "success" : "destructive"}
                className="px-4 py-1 text-sm"
              >
                {result.verdict}
              </Badge>
            </CardTitle>
            <span className="font-mono text-xs text-muted-foreground">
              {result.report_id.slice(0, 8)}
            </span>
          </div>
          <CardDescription>
            {result.source_file} · {new Date(result.created_at).toLocaleString()}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Minimum distance" value={`${v.min_distance_m.toFixed(2)} m`} />
            <Metric label="Required" value={`${v.required_distance_m.toFixed(2)} m`} />
            <Metric
              label="Margin"
              value={`${v.margin_m >= 0 ? "+" : ""}${v.margin_m.toFixed(2)} m`}
            />
            <Metric
              label="Drawing units"
              value={v.drawing_units}
              sub={`${v.distance_in_drawing_units} units measured`}
            />
          </div>

          {v.closest_point_building && v.closest_point_boundary ? (
            <p className="font-mono text-xs text-muted-foreground">
              Closest pair → building ({v.closest_point_building.join(", ")}) · boundary (
              {v.closest_point_boundary.join(", ")})
            </p>
          ) : null}

          {v.warnings.length > 0 ? (
            <ul className="list-inside list-disc text-xs text-amber-700">
              {v.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">AI semantic mapping (Phase 2)</CardTitle>
          <CardDescription>
            DeepSeek selected which deterministic entity ids play each role — it performed
            no measurements.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="font-medium">Building perimeter:</span>{" "}
            <span className="font-mono text-xs">
              {result.mapping.building_lines.join(", ")}
            </span>
          </p>
          <p>
            <span className="font-medium">Boundary wall:</span>{" "}
            <span className="font-mono text-xs">
              {result.mapping.boundary_lines.join(", ")}
            </span>
          </p>
          {result.mapping.rationale ? (
            <p className="text-xs text-muted-foreground">{result.mapping.rationale}</p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Municipality compliance report</CardTitle>
          <CardDescription>
            Drafted by DeepSeek from the exact deterministic figures
            {result.persisted_to_database ? " · stored in Supabase" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="markdown-body text-sm">
            <ReactMarkdown>{result.report_markdown}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
