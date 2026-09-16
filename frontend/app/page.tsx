"use client";

import { useCallback, useRef, useState } from "react";
import { FileUp, Landmark, PlayCircle, UploadCloud } from "lucide-react";
import { ComplianceResultView } from "@/components/compliance-result";
import { PipelineTracker } from "@/components/pipeline-tracker";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  streamPipeline,
  type ComplianceResult,
  type PhaseState,
  type PipelineTarget,
  type SseEvent,
} from "@/lib/api";
import { freshPhases } from "@/lib/phases";

export default function DashboardPage() {
  const [file, setFile] = useState<File | null>(null);
  const [phases, setPhases] = useState<PhaseState[]>(freshPhases);
  const [result, setResult] = useState<ComplianceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleEvent = useCallback((event: SseEvent) => {
    switch (event.event) {
      case "pipeline_start": {
        const data = event.data as { phases?: PhaseState[] };
        setResult(null);
        setError(null);
        setPhases(
          (data.phases ?? freshPhases()).map((phase) => ({
            ...phase,
            status: "pending" as const,
          }))
        );
        break;
      }
      case "phase": {
        const data = event.data as {
          phase: number;
          status: PhaseState["status"];
          detail?: Record<string, unknown>;
        };
        setPhases((prev) =>
          prev.map((phase) =>
            phase.phase === data.phase
              ? { ...phase, status: data.status, detail: data.detail }
              : phase
          )
        );
        break;
      }
      case "result":
        setResult(event.data as ComplianceResult);
        break;
      case "error": {
        const data = event.data as { message?: string };
        setError(data.message ?? "The pipeline failed.");
        break;
      }
      default:
        break;
    }
  }, []);

  const run = useCallback(
    async (target: PipelineTarget) => {
      setIsRunning(true);
      setError(null);
      setResult(null);
      setPhases(freshPhases());
      try {
        await streamPipeline(target, handleEvent);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsRunning(false);
      }
    },
    [handleEvent]
  );

  return (
    <main className="min-h-screen bg-muted/30">
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Landmark className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold leading-tight">
                Hybrid CAD Compliance System
              </h1>
              <p className="text-xs text-muted-foreground">
                Deterministic geometry · AI semantics · Municipal setback verification
              </p>
            </div>
          </div>
          <span className="hidden rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground sm:inline">
            Rule: minimum setback 1.5 m
          </span>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-6 px-6 py-8 lg:grid-cols-[380px_1fr]">
        {/* Left column: upload + pipeline tracker */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Submit drawing</CardTitle>
              <CardDescription>
                Upload the site plan (.dwg). The 4-step pipeline verifies the minimum
                setback between the building perimeter and the boundary wall.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <input
                ref={inputRef}
                type="file"
                accept=".dwg,.dxf"
                className="hidden"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border bg-muted/30 px-4 py-8 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:bg-muted/60"
              >
                <UploadCloud className="h-6 w-6" />
                {file ? (
                  <span className="font-medium text-foreground">{file.name}</span>
                ) : (
                  <span>Choose a .dwg file</span>
                )}
                <span className="text-xs">
                  {file
                    ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
                    : "or click to browse"}
                </span>
              </button>

              <Button
                className="w-full"
                disabled={!file || isRunning}
                onClick={() => file && run({ kind: "dwg", file })}
              >
                <PlayCircle className="h-4 w-4" />
                {isRunning ? "Running pipeline…" : "Run compliance check"}
              </Button>

              <Button
                variant="outline"
                className="w-full"
                disabled={isRunning}
                onClick={() => run({ kind: "sample" })}
              >
                <FileUp className="h-4 w-4" />
                Run bundled sample (no DWG needed)
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Pipeline status</CardTitle>
            </CardHeader>
            <CardContent>
              <PipelineTracker phases={phases} />
            </CardContent>
          </Card>

          {error ? (
            <Card className="border-destructive/60">
              <CardHeader>
                <CardTitle className="text-base text-destructive">Pipeline error</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{error}</p>
              </CardContent>
            </Card>
          ) : null}
        </div>

        {/* Right column: deterministic result + AI report */}
        <div>
          {result ? (
            <ComplianceResultView result={result} />
          ) : (
            <Card className="flex min-h-[420px] items-center justify-center border-dashed">
              <CardContent className="text-center text-sm text-muted-foreground">
                {isRunning
                  ? "The pipeline is running — results will appear here."
                  : "Upload a .dwg file (or run the bundled sample) to generate a compliance report."}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <footer className="mx-auto max-w-6xl px-6 pb-8 text-xs text-muted-foreground">
        PASS/FAIL is decided exclusively by deterministic Shapely math (Phase 3). DeepSeek
        only maps entity semantics (Phase 2) and drafts prose (Phase 4) — it never
        participates in any measurement.
      </footer>
    </main>
  );
}
