"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Cable,
  CircleCheck,
  CircleX,
  FileUp,
  Gauge,
  KeyRound,
  SquareDashed,
  TriangleAlert,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { isAcceptedFile, type ApiError, type HealthPayload } from "@/lib/api";
import { cn } from "@/lib/utils";

const TASK_FALLBACK = ["sheet_review", "bom", "complexity_metrics", "standards_compliance", "discipline_summary", "custom"];

export interface UploadSelection {
  file: File;
  task: string;
  brief: string;
  dryRun: boolean;
  keep: boolean;
}

export interface UploadPanelProps {
  health: HealthPayload | null;
  healthError: string | null;
  probing: boolean;
  busy: boolean;
  error: ApiError | null;
  onSubmit: (selection: UploadSelection) => void;
  onProbe: () => void;
  onOpenLast?: () => void;
  lastLabel?: string;
}

function bytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}

export function UploadPanel({
  health,
  healthError,
  probing,
  busy,
  error,
  onSubmit,
  onProbe,
  onOpenLast,
  lastLabel,
}: UploadPanelProps) {
  const [file, setFile] = React.useState<File | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const [localError, setLocalError] = React.useState<string | null>(null);
  const [task, setTask] = React.useState("sheet_review");
  const [brief, setBrief] = React.useState("");
  const [dryRun, setDryRun] = React.useState(false);
  const [keep, setKeep] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const maxMb = health?.limits?.max_upload_mb ?? null;
  const tasks = health?.tasks?.length ? health.tasks : TASK_FALLBACK;
  const tooBig = Boolean(file && maxMb && file.size > maxMb * 1024 * 1024);
  const dwgNeedsConverter = Boolean(file && file.name.toLowerCase().endsWith(".dwg") && health && health.readiness?.accepts_dwg === false);
  const needsKey = Boolean(file && !dryRun && health && health.readiness?.full_pipeline === false);
  const blocked = !file || tooBig || busy;

  function accept(candidate: File | undefined | null) {
    if (!candidate) return;
    if (!isAcceptedFile(candidate.name)) {
      setLocalError(`${candidate.name} is not a .dwg or .dxf file`);
      return;
    }
    setLocalError(null);
    setFile(candidate);
    if (candidate.name.toLowerCase().endsWith(".dxf") && health?.readiness) setDryRun(dryRun);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (blocked || !file) return;
    onSubmit({ file, task, brief, dryRun, keep });
  }

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
      <Card className="relative overflow-hidden border-primary/25">
        <div aria-hidden className="pointer-events-none absolute inset-0 grid-panel opacity-60" />
        <CardHeader className="relative">
          <CardTitle className="flex items-center gap-2 text-base">
            <SquareDashed className="size-4 text-primary" />
            New sheet review
          </CardTitle>
          <CardDescription>
            Drop a drawing on the service to parse it with <span className="font-mono text-foreground">ezdxf + odafc</span>,
            structure the metadata and have DeepSeek review it. Nothing is uploaded anywhere else.
          </CardDescription>
        </CardHeader>

        <CardContent className="relative space-y-4">
          {/* health strip */}
          <div className="flex flex-wrap items-center gap-2">
            {healthError ? (
              <Badge variant="high" className="gap-1">
                <CircleX className="size-3" />
                service unreachable
              </Badge>
            ) : health ? (
              <>
                <Badge variant="ok" className="gap-1">
                  <CircleCheck className="size-3" />
                  service online
                </Badge>
                <Badge variant={health.readiness?.accepts_dwg ? "ok" : "medium"} className="gap-1 normal-case">
                  <Gauge className="size-3" />
                  DWG: {health.readiness?.accepts_dwg ? "local converter" : "needs APS fallback"}
                </Badge>
                <Badge variant={health.readiness?.full_pipeline ? "ok" : "medium"} className="gap-1 normal-case">
                  <KeyRound className="size-3" />
                  DeepSeek: {health.readiness?.full_pipeline ? "configured" : "no API key"}
                </Badge>
                {health.limits?.active !== undefined ? (
                  <Badge variant="ghost" className="normal-case">
                    jobs {health.limits.active}/{health.limits.concurrency}
                  </Badge>
                ) : null}
              </>
            ) : (
              <Badge variant="ghost">checking service…</Badge>
            )}
            <button
              type="button"
              onClick={onProbe}
              disabled={probing}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              title="Ping the service (adds a small DeepSeek completion when a key is configured)"
            >
              <Cable className="size-3.5" />
              {probing ? "probing…" : "check connection"}
            </button>
          </div>

          {healthError ? (
            <div className="rounded-md border border-neon-red/40 bg-neon-red/[0.07] p-3">
              <p className="flex items-center gap-2 text-[13px] font-medium text-neon-red">
                <TriangleAlert className="size-4" />
                {healthError}
              </p>
              <p className="mt-1 font-mono text-[11.5px] leading-relaxed text-muted-foreground">
                start it with: uvicorn server:app --host 0.0.0.0 --port 8000
              </p>
            </div>
          ) : null}

          {/* dropzone */}
          <form onSubmit={submit} className="space-y-4">
            <div
              onDragOver={(event) => {
                event.preventDefault();
                if (!busy) setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                if (!busy) accept(event.dataTransfer.files?.[0]);
              }}
              className={cn(
                "relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-all duration-200",
                dragging
                  ? "border-primary bg-primary/10 shadow-glow"
                  : "border-border/70 bg-muted/20 hover:border-primary/50 hover:bg-muted/30",
                busy && "pointer-events-none opacity-50",
              )}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".dwg,.dxf"
                className="sr-only"
                onChange={(event) => accept(event.target.files?.[0])}
                aria-label="Choose a DWG or DXF file"
              />
              <motion.span
                animate={dragging ? { scale: 1.12, rotate: -6 } : { scale: 1, rotate: 0 }}
                transition={{ type: "spring", stiffness: 260, damping: 18 }}
                className="mb-3 grid size-12 place-items-center rounded-lg border border-primary/40 bg-primary/10 text-primary"
              >
                <FileUp className="size-6" />
              </motion.span>
              {file ? (
                <>
                  <p className="max-w-full truncate font-mono text-[14px] text-foreground">{file.name}</p>
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                    {bytes(file.size)} · {file.type || "application/octet-stream"}
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setFile(null);
                      setLocalError(null);
                      if (inputRef.current) inputRef.current.value = "";
                    }}
                    className="mt-3 inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-3" />
                    remove
                  </button>
                </>
              ) : (
                <>
                  <p className="text-[14px] font-medium">Drop a drawing here, or</p>
                  <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    className="mt-2 rounded-md border border-primary/50 bg-primary/15 px-3 py-1.5 font-mono text-[12px] uppercase tracking-wider text-foreground transition-colors hover:bg-primary/25"
                  >
                    select .dwg / .dxf
                  </button>
                  <p className="mt-3 font-mono text-[11px] text-muted-foreground">
                    max {maxMb ?? "?"} MB per file · nothing is stored unless you tick “keep artifacts”
                  </p>
                </>
              )}
            </div>

            {localError ? (
              <p className="flex items-center gap-2 rounded-md border border-neon-amber/45 bg-neon-amber/[0.07] px-3 py-2 text-[12.5px] text-neon-amber">
                <TriangleAlert className="size-4 shrink-0" />
                {localError}
              </p>
            ) : null}
            {tooBig ? (
              <p className="rounded-md border border-neon-red/45 bg-neon-red/[0.07] px-3 py-2 font-mono text-[12px] text-neon-red">
                {bytes(file!.size)} exceeds the service limit of {maxMb} MB — split the sheet set, or raise
                CAD2AI_API_MAX_UPLOAD_MB
              </p>
            ) : null}
            {dwgNeedsConverter ? (
              <p className="rounded-md border border-neon-amber/45 bg-neon-amber/[0.07] px-3 py-2 text-[12.5px] text-neon-amber">
                This service has no ODA File Converter, so a <span className="font-mono">.dwg</span> needs the Autodesk
                fallback (APS) — a <span className="font-mono">.dxf</span> will parse locally.
              </p>
            ) : null}
            {needsKey ? (
              <p className="rounded-md border border-neon-amber/45 bg-neon-amber/[0.07] px-3 py-2 text-[12.5px] text-neon-amber">
                No <span className="font-mono">DEEPSEEK_API_KEY</span> on the server: the run will fail at phase 3. Tick
                “build payload only” to inspect the extraction instead.
              </p>
            ) : null}

            {/* options */}
            <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
              <label className="block">
                <span className="hud-label">Review task</span>
                <select
                  value={task}
                  onChange={(event) => setTask(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-input/70 bg-muted/40 px-2 font-mono text-[12.5px] text-foreground focus-visible:border-primary/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/60"
                >
                  {tasks.map((entry) => (
                    <option key={entry} value={entry}>
                      {entry}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="hud-label">
                  Brief for the model <span className="normal-case tracking-normal">({brief.length}/400)</span>
                </span>
                <Input
                  value={brief}
                  maxLength={400}
                  onChange={(event) => setBrief(event.target.value)}
                  placeholder="e.g. permit-issue set — flag anything that blocks issue"
                  className="mt-1"
                />
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-4">
              <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(event) => setDryRun(event.target.checked)}
                  className="size-3.5 accent-[hsl(var(--primary))]"
                />
                build payload only (no DeepSeek call)
              </label>
              <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={keep}
                  onChange={(event) => setKeep(event.target.checked)}
                  className="size-3.5 accent-[hsl(var(--primary))]"
                />
                keep artifacts on the server
              </label>

              <div className="ml-auto flex items-center gap-2">
                {onOpenLast ? (
                  <button
                    type="button"
                    onClick={onOpenLast}
                    className="rounded-md border border-border/60 px-3 py-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
                  >
                    {lastLabel ?? "show last result"}
                  </button>
                ) : null}
                <motion.button
                  type="submit"
                  disabled={blocked}
                  whileTap={blocked ? undefined : { scale: 0.98 }}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md border px-4 py-2 font-mono text-[12px] uppercase tracking-wider transition-all",
                    blocked
                      ? "cursor-not-allowed border-border/50 bg-muted/30 text-muted-foreground"
                      : "border-primary/60 bg-primary/20 text-foreground shadow-glow hover:bg-primary/30",
                  )}
                >
                  {busy ? "running…" : dryRun ? "extract payload" : "run review"}
                  <ArrowRight className="size-3.5" />
                </motion.button>
              </div>
            </div>
          </form>

          {error ? (
            <div className="rounded-md border border-neon-red/45 bg-neon-red/[0.07] p-3">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-neon-red">
                <CircleX className="size-4" />
                {error.message}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
                <Badge variant="high">{error.status}</Badge>
                {error.code ? <Badge variant="ghost">{error.code}</Badge> : null}
                {error.retryable ? <Badge variant="medium">retryable</Badge> : null}
              </div>
              {error.hint ? (
                <p className="mt-2 text-[12.5px] leading-relaxed text-foreground/85">
                  <span className="hud-label mr-2">hint</span>
                  {error.hint}
                </p>
              ) : null}
              {Object.keys(error.details).length > 0 ? (
                <pre className="code-surface mt-2 overflow-x-auto px-2 py-1.5 text-[11px] text-muted-foreground">
                  {JSON.stringify(error.details, null, 1)}
                </pre>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
