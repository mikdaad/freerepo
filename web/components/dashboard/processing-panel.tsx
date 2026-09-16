"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { CircleCheck, Loader, Ban, Terminal } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Phase {
  /** fraction of the expected duration at which this phase starts */
  at: number;
  label: string;
  sub?: string;
}

/**
 * Expected durations are guesses, not measurements: a sheet review is
 * 60-90 s, most of it inside the model call. The bar therefore approaches 97 %
 * asymptotically instead of lying about being nearly done, and only reaches
 * 100 % when the response actually lands.
 */
const PHASES: Phase[] = [
  { at: 0.0, label: "Opening connection to the analysis service", sub: "POST /api/analyze (multipart/form-data)" },
  { at: 0.06, label: "Staging the upload", sub: "size guard, filename sanitisation, temp workspace" },
  { at: 0.14, label: "Parsing DWG binary", sub: "odafc → DXF AC1032 · bounded by ODA_TIMEOUT" },
  { at: 0.3, label: "Extracting metadata", sub: "layers · blocks · ATTRIBs · dimensions · audit" },
  { at: 0.44, label: "Minifying the payload", sub: "token budget · degradation ladder" },
  { at: 0.54, label: "Running DeepSeek analysis", sub: "json mode · this is the slow part" },
  { at: 0.9, label: "Validating the response", sub: "JSON repair · verdict and confidence normalisation" },
];

const EXPECTED_MS = 78_000;

function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export interface ProcessingPanelProps {
  startedAt: number;
  filename: string;
  bytes: number;
  task: string;
  apiBase: string;
  onCancel: () => void;
  cancelling: boolean;
}

export function ProcessingPanel({
  startedAt,
  filename,
  bytes,
  task,
  apiBase,
  onCancel,
  cancelling,
}: ProcessingPanelProps) {
  const [now, setNow] = React.useState(() => Date.now());
  const [log, setLog] = React.useState<{ at: string; line: string }[]>([
    { at: "00:00", line: `queued ${filename} (${(bytes / 1024).toFixed(0)} KiB) · task=${task}` },
  ]);

  React.useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 120);
    return () => clearInterval(timer);
  }, []);

  const elapsed = Math.max(0, now - startedAt);
  const fraction = 1 - Math.exp(-3.4 * (elapsed / EXPECTED_MS));
  const progress = Math.min(0.97, fraction);
  const index = PHASES.reduce((acc, phase, i) => (progress >= phase.at ? i : acc), 0);

  // Append a console line each time a phase starts (technical, and honest about
  // which stage we *think* we are in).
  React.useEffect(() => {
    const phase = PHASES[index];
    if (!phase) return;
    setLog((current) => {
      const line = phase.label;
      if (current.some((entry) => entry.line === line)) return current;
      return [...current, { at: clock(elapsed), line }];
    });
    // elapsed intentionally excluded: we only want a line per phase change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  const overThirties = elapsed > 30_000;

  return (
    <Card className="relative overflow-hidden border-primary/35 shadow-glow">
      <div aria-hidden className="pointer-events-none absolute inset-0 grid-panel opacity-70" />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-scan-sweep animate-sweep opacity-70"
      />
      <CardContent className="relative space-y-6 p-6 lg:p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Loader className="size-4 animate-spin text-primary" />
              <span className="hud-label">Analysis in flight</span>
              <span className="font-mono text-[11px] text-muted-foreground">{apiBase || "same-origin /api"}</span>
            </div>
            <h2 className="mt-2 truncate font-mono text-lg font-semibold text-foreground sm:text-2xl">{filename}</h2>
            <p className="mt-1 text-[13px] text-muted-foreground">
              A sheet review usually takes 60-90 s: the ODA conversion, the extraction, then one long model call.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="font-mono text-3xl font-semibold tabular-nums leading-none">{clock(elapsed)}</div>
              <div className="hud-label mt-1">elapsed</div>
            </div>
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling}
              className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-muted/40 px-3 py-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground transition-colors hover:border-neon-red/50 hover:text-neon-red disabled:opacity-50"
            >
              <Ban className="size-3.5" />
              {cancelling ? "aborting…" : "cancel"}
            </button>
          </div>
        </div>

        {/* progress */}
        <div>
          <div className="mb-2 flex items-baseline justify-between font-mono text-[11px] text-muted-foreground">
            <span>
              phase <span className="text-foreground">{index + 1}</span>/{PHASES.length}
            </span>
            <span className="tabular-nums">{(progress * 100).toFixed(1)}%</span>
          </div>
          <div className="relative h-2 overflow-hidden rounded-full border border-border/60 bg-muted/50">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full bg-primary/70 shadow-[0_0_18px_2px_hsl(var(--primary)/0.55)]"
              animate={{ width: `${progress * 100}%` }}
              transition={{ duration: 0.18, ease: "linear" }}
            />
            <div
              aria-hidden
              className="absolute inset-y-0 w-24 bg-gradient-to-r from-transparent via-white/25 to-transparent"
              style={{ transform: `translateX(${(progress * 100).toFixed(1)}%)`, transition: "transform 180ms linear" }}
            />
          </div>
          {overThirties ? (
            <p className="mt-2 font-mono text-[11px] text-neon-amber">
              still running — large sheet sets, a cold ODA converter or a thinking-mode call can push this past 2 min
            </p>
          ) : null}
        </div>

        {/* phases */}
        <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {PHASES.map((phase, i) => {
            const done = i < index;
            const active = i === index;
            return (
              <li
                key={phase.label}
                className={cn(
                  "flex items-start gap-2 rounded-md border px-3 py-2 transition-colors",
                  done && "border-neon-green/35 bg-neon-green/[0.06]",
                  active && "border-primary/55 bg-primary/[0.08] shadow-glow",
                  !done && !active && "border-border/50 bg-muted/20 opacity-60",
                )}
              >
                {done ? (
                  <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-neon-green" />
                ) : (
                  <span
                    className={cn(
                      "mt-1 size-2 shrink-0 rounded-[2px]",
                      active ? "animate-pulse bg-primary" : "bg-border",
                    )}
                  />
                )}
                <div className="min-w-0">
                  <p className={cn("text-[12.5px] font-medium leading-tight", active ? "text-foreground" : "text-foreground/80")}>
                    {phase.label}
                  </p>
                  {phase.sub ? <p className="mt-0.5 truncate font-mono text-[10.5px] text-muted-foreground">{phase.sub}</p> : null}
                </div>
              </li>
            );
          })}
        </ol>

        {/* console */}
        <div className="code-surface max-h-40 overflow-y-auto px-3 py-2">
          {log.map((entry, i) => (
            <div key={`${entry.at}-${i}`} className="flex gap-2 whitespace-pre-wrap">
              <span className="select-none text-muted-foreground/70">{entry.at}</span>
              <Terminal className="size-3 shrink-0 translate-y-0.5 text-primary/70" aria-hidden />
              <span className="text-foreground/85">{entry.line}</span>
            </div>
          ))}
          <div className="flex gap-2">
            <span className="select-none text-muted-foreground/70">{clock(elapsed)}</span>
            <span className="text-primary">›</span>
            <span className="animate-blink-caret">_</span>
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground">
          Cancelling detaches this browser only; the pipeline run continues server-side and its artifacts (if any) stay
          in the run directory.
        </p>
      </CardContent>
    </Card>
  );
}
