"use client";

import * as React from "react";
import { Download, FlaskConical, ScanLine, SquareArrowUpRight } from "lucide-react";
import { PayloadSummary } from "@/components/dashboard/payload-summary";
import { ProcessingPanel } from "@/components/dashboard/processing-panel";
import { ReviewConsole } from "@/components/dashboard/review-console";
import { UploadPanel, type UploadSelection } from "@/components/dashboard/upload-panel";
import { Badge } from "@/components/ui/badge";
import { ToastViewport, useToastStack } from "@/components/ui/toast";
import {
  analyzeDrawing,
  ApiError,
  fetchHealth,
  resolveApiBase,
  type AnalyzeResponse,
  type HealthPayload,
} from "@/lib/api";
import { normalizeAnalysis, type Analysis } from "@/lib/analysis";

export type WorkbenchStatus = "idle" | "processing" | "success" | "error";

export interface WorkbenchProps {
  /** A real `analysis.json` found on disk by the server (null when there is none). */
  initial: Analysis | null;
  /** The bundled sample, offered so the UI is explorable without a service. */
  sample: Analysis | null;
}

function notesFromResponse(response: AnalyzeResponse): string[] {
  const notes: string[] = [];
  for (const warning of response.warnings ?? []) notes.push(warning);
  const payload = response.payload ?? {};
  for (const step of payload.degraded ?? []) notes.push(`payload degraded for the token budget: ${step}`);
  for (const [section, dropped] of Object.entries(payload.truncations ?? {})) {
    notes.push(`${section} list was capped: ${dropped} item(s) not sent to the model`);
  }
  if (typeof payload.budget_exceeded_by === "number" && payload.budget_exceeded_by > 0) {
    notes.push(`payload still exceeded the budget by ${payload.budget_exceeded_by} tokens after degradation`);
  }
  if (response.dry_run) notes.push("dry run: phases 1+2 only — DeepSeek was not called, so there are no findings");
  return notes;
}

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5_000);
}

export function Workbench({ initial, sample }: WorkbenchProps) {
  const [status, setStatus] = React.useState<WorkbenchStatus>(initial ? "success" : "idle");
  const [analysis, setAnalysis] = React.useState<Analysis | null>(initial);
  const [response, setResponse] = React.useState<AnalyzeResponse | null>(null);
  const [rawAnalysis, setRawAnalysis] = React.useState<unknown>(null);
  const [error, setError] = React.useState<ApiError | null>(null);
  const [pending, setPending] = React.useState<{ filename: string; bytes: number; task: string } | null>(null);
  const [startedAt, setStartedAt] = React.useState(0);
  const [cancelling, setCancelling] = React.useState(false);
  const [health, setHealth] = React.useState<HealthPayload | null>(null);
  const [healthError, setHealthError] = React.useState<string | null>(null);
  const [probing, setProbing] = React.useState(false);
  const abortRef = React.useRef<AbortController | null>(null);
  const { toasts, push, dismiss } = useToastStack();
  const apiBase = React.useMemo(() => resolveApiBase(), []);

  const loadHealth = React.useCallback(
    async (probe: boolean, signal?: AbortSignal) => {
      if (probe) setProbing(true);
      try {
        const payload = await fetchHealth({ probe, signal });
        setHealth(payload);
        setHealthError(null);
        if (probe) {
          const result = payload.deepseek?.probe as { ok?: boolean; message?: string } | undefined;
          push({
            tone: result?.ok ? "success" : "warning",
            title: result?.ok ? "DeepSeek reachable" : "Service reachable, DeepSeek is not",
            message: result?.ok ? undefined : result?.message ?? payload.deepseek?.base_url,
            ttl: probe ? 9000 : 0,
          });
        }
      } catch (cause) {
        if ((cause as Error)?.name === "AbortError") return;
        setHealth(null);
        setHealthError(
          `the analysis service is not answering on ${apiBase || "the same origin"} (${
            (cause as Error)?.message ?? "network error"
          })`,
        );
      } finally {
        if (probe) setProbing(false);
      }
    },
    [apiBase, push],
  );

  React.useEffect(() => {
    const controller = new AbortController();
    void loadHealth(false, controller.signal);
    return () => controller.abort();
  }, [loadHealth]);

  // An abort only detaches the browser; say so instead of pretending the run stopped.
  function cancel() {
    setCancelling(true);
    abortRef.current?.abort();
  }

  async function submit(selection: UploadSelection) {
    const controller = new AbortController();
    abortRef.current = controller;
    setPending({ filename: selection.file.name, bytes: selection.file.size, task: selection.task });
    setStatus("processing");
    setStartedAt(Date.now());
    setError(null);

    try {
      const result = await analyzeDrawing(selection.file, {
        task: selection.task,
        brief: selection.brief,
        dryRun: selection.dryRun,
        keep: selection.keep,
        signal: controller.signal,
      });
      const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
      setResponse(result);
      setRawAnalysis(result.analysis ?? null);

      const notes = notesFromResponse(result);
      const base =
        result.analysis && typeof result.analysis === "object"
          ? normalizeAnalysis(result.analysis)
          : normalizeAnalysis({
              drawing: result.filename ?? selection.file.name,
              // Dry run: no model call, so there is nothing to report — say so
              // rather than letting an empty findings list look like a clean sheet.
              release_recommendation: "no verdict",
              data_gaps: ["phases 1+2 only: the payload was built but DeepSeek never ran"],
            });
      setAnalysis({
        ...base,
        origin: "file",
        originLabel: `${result.filename ?? selection.file.name} · run ${result.run_id ?? "unknown"} · ${elapsed}s`,
        warnings: notes,
      });
      setStatus("success");
      push({
        tone: "success",
        title: `${selection.file.name}: ${result.dry_run ? "payload built" : "analysis complete"}`,
        message:
          result.dry_run === true || result.analysis == null
            ? `payload ready in ${elapsed}s — no model call was made`
            : `reviewed in ${elapsed}s · ${
                (result.analysis as { findings?: unknown[] } | undefined)?.findings?.length ?? 0
              } findings · verdict ${String((result.analysis as { release_recommendation?: string } | undefined)?.release_recommendation ?? "n/a")}`,
        ttl: 9000,
      });
    } catch (cause) {
      if ((cause as Error)?.name === "AbortError" || cancelling) {
        setStatus(analysis ? "success" : "idle");
        push({
          tone: "info",
          title: "Detached from the analysis",
          message: "the browser stopped waiting; the run continues server-side",
        });
        return;
      }
      const apiError =
        cause instanceof ApiError
          ? cause
          : new ApiError({ message: (cause as Error)?.message ?? String(cause) }, 0, "could not reach the analysis service");
      setError(apiError);
      setStatus("error");
      push({
        tone: "error",
        title: `Analysis failed (${apiError.status})`,
        message: [apiError.message, apiError.hint].filter(Boolean).join(" — "),
        ttl: 0,
      });
    } finally {
      abortRef.current = null;
      setCancelling(false);
      setPending(null);
      void loadHealth(false);
    }
  }

  function startOver() {
    setStatus("idle");
    setError(null);
    setResponse(null);
  }

  function showSample() {
    if (!sample) return;
    setAnalysis(sample);
    setResponse(null);
    setStatus("success");
  }

  const isFresh = status === "idle" || status === "error";

  return (
    <div className="space-y-4">
      {status === "processing" && pending ? (
        <ProcessingPanel
          startedAt={startedAt}
          filename={pending.filename}
          bytes={pending.bytes}
          task={pending.task}
          apiBase={apiBase}
          onCancel={cancel}
          cancelling={cancelling}
        />
      ) : null}

      {isFresh ? (
        <div className="space-y-4">
          <UploadPanel
            health={health}
            healthError={healthError}
            probing={probing}
            busy={false}
            error={error}
            onSubmit={(selection) => void submit(selection)}
            onProbe={() => void loadHealth(true)}
            onOpenLast={analysis ? () => setStatus("success") : undefined}
            lastLabel={analysis ? "show last result" : undefined}
          />
          {sample && !initial ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 bg-card/40 px-4 py-3">
              <FlaskConical className="size-4 text-neon-violet" />
              <p className="min-w-0 flex-1 text-[13px] text-muted-foreground">
                Service down or no drawing to hand? The bundled sample sheet renders the whole console — findings,
                tables and the release gate — with nothing running.
              </p>
              <button
                type="button"
                onClick={showSample}
                className="inline-flex items-center gap-1.5 rounded-md border border-neon-violet/45 bg-neon-violet/10 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-neon-violet transition-colors hover:bg-neon-violet/20"
              >
                <SquareArrowUpRight className="size-3.5" />
                preview bundled sample
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {status === "success" && analysis ? (
        <>
          {response ? <PayloadSummary response={response} /> : null}
          <ReviewConsole
            analysis={analysis}
            toolbar={
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-card/40 px-3 py-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Badge variant={analysis.origin === "file" ? "ok" : "medium"} className="gap-1">
                    <ScanLine className="size-3" />
                    {analysis.origin === "file" ? "service result" : "bundled sample"}
                  </Badge>
                  <span className="truncate font-mono text-[11px] text-muted-foreground">{analysis.originLabel}</span>
                  {response?.timings ? (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {Object.entries(response.timings)
                        .map(([stage, seconds]) => `${stage} ${Number(seconds).toFixed(1)}s`)
                        .join(" · ")}
                    </span>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {rawAnalysis ? (
                    <button
                      type="button"
                      onClick={() => download(`${analysis.drawing ?? "analysis"}.json`, JSON.stringify(rawAnalysis, null, 2), "application/json")}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
                    >
                      <Download className="size-3.5" />
                      analysis.json
                    </button>
                  ) : null}
                  {response?.markdown ? (
                    <button
                      type="button"
                      onClick={() => download(`${analysis.drawing ?? "report"}.md`, response.markdown ?? "", "text/markdown")}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
                    >
                      <Download className="size-3.5" />
                      report.md
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={startOver}
                    className="rounded-md border border-primary/50 bg-primary/15 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-foreground transition-colors hover:bg-primary/25"
                  >
                    analyze another drawing
                  </button>
                </div>
              </div>
            }
          />
        </>
      ) : null}

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
