"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, Filter, RotateCcw, ScanSearch, Search, Terminal, Wrench, X } from "lucide-react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  BUCKET_LABELS,
  evidencePath,
  SEVERITY_ORDER,
  type Analysis,
  type Finding,
  type Severity,
} from "@/lib/analysis";
import { cn, truncate } from "@/lib/utils";

type SeverityFilter = Severity | "all";

const SEVERITY_SQUARE: Record<Severity, string> = {
  high: "bg-neon-red shadow-[0_0_10px_-1px_hsl(var(--neon-red)/0.9)]",
  medium: "bg-neon-amber",
  low: "bg-neon-cyan",
};

const SEVERITY_BADGE: Record<Severity, "high" | "medium" | "low"> = {
  high: "high",
  medium: "medium",
  low: "low",
};

function matches(finding: Finding, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    finding.id,
    finding.bucket,
    finding.title,
    finding.detail,
    finding.recommendation,
    ...finding.evidence,
  ]
    .join(" ")
    .toLowerCase();
  return needle
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term));
}

export function FindingsPanel({ analysis }: { analysis: Analysis }) {
  const [query, setQuery] = React.useState("");
  const [severity, setSeverity] = React.useState<SeverityFilter>("all");
  const [bucket, setBucket] = React.useState<string>("all");

  const buckets = React.useMemo(() => {
    const seen = new Map<string, number>();
    for (const finding of analysis.findings) {
      seen.set(finding.bucket, (seen.get(finding.bucket) ?? 0) + 1);
    }
    return [...seen.entries()].sort((a, b) => b[1] - a[1]);
  }, [analysis.findings]);

  const counts = React.useMemo(() => {
    const base: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
    for (const finding of analysis.findings) base[finding.severity] += 1;
    return base;
  }, [analysis.findings]);

  const visible = React.useMemo(() => {
    return analysis.findings
      .filter((finding) => (severity === "all" ? true : finding.severity === severity))
      .filter((finding) => (bucket === "all" ? true : finding.bucket === bucket))
      .filter((finding) => matches(finding, query))
      .sort((a, b) => {
        const bySeverity = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
        if (bySeverity !== 0) return bySeverity;
        return a.id.localeCompare(b.id, undefined, { numeric: true });
      });
  }, [analysis.findings, bucket, query, severity]);

  // Critical items arrive expanded so the reviewer sees the evidence without
  // clicking; the animation is what makes the panel read as "ingesting".
  const criticalIds = React.useMemo(
    () => visible.filter((finding) => finding.severity === "high").map((finding) => finding.id),
    [visible],
  );
  const [open, setOpen] = React.useState<string[]>(criticalIds);
  React.useEffect(() => {
    setOpen(criticalIds);
  }, [criticalIds]);

  const dirty = query !== "" || severity !== "all" || bucket !== "all";

  return (
    <section className="space-y-4">
      {/* controls */}
      <div className="flex flex-col gap-3 rounded-lg border border-border/60 bg-card/50 p-3 lg:flex-row lg:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search findings, evidence paths, recommendations…"
            className="pl-9 pr-9 font-mono text-[13px]"
            aria-label="Search findings"
            type="search"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Clear search"
            >
              <X className="size-3.5" />
            </button>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by severity">
          {(["all", "high", "medium", "low"] as const).map((option) => {
            const active = severity === option;
            const count = option === "all" ? analysis.findings.length : counts[option];
            return (
              <button
                key={option}
                type="button"
                onClick={() => setSeverity(option)}
                aria-pressed={active}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors",
                  active
                    ? "border-primary/60 bg-primary/12 text-foreground"
                    : "border-border/60 bg-muted/30 text-muted-foreground hover:border-primary/40 hover:text-foreground",
                )}
              >
                {option !== "all" ? <span className={cn("size-1.5 rounded-[1px]", SEVERITY_SQUARE[option])} /> : null}
                {option}
                <span className="tabular-nums text-foreground/80">{count}</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <Filter className="size-3.5 text-muted-foreground" />
          <select
            value={bucket}
            onChange={(event) => setBucket(event.target.value)}
            aria-label="Filter by bucket"
            className="h-9 rounded-md border border-input/70 bg-muted/40 px-2 font-mono text-[12px] text-foreground focus-visible:border-primary/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/60"
          >
            <option value="all">all buckets</option>
            {buckets.map(([name, count]) => (
              <option key={name} value={name}>
                {BUCKET_LABELS[name] ?? name} ({count})
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setSeverity("all");
              setBucket("all");
            }}
            disabled={!dirty}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
          >
            <RotateCcw className="size-3.5" />
            reset
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          showing <span className="text-foreground">{visible.length}</span> / {analysis.findings.length} findings
        </p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setOpen(visible.map((finding) => finding.id))}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            title="Expand all"
          >
            <ChevronRight className="size-4 rotate-90" />
          </button>
          <button
            type="button"
            onClick={() => setOpen([])}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            title="Collapse all"
          >
            <ChevronRight className="size-4 -rotate-90" />
          </button>
        </div>
      </div>

      {/* list */}
      {visible.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/70 bg-card/30 p-10 text-center">
          <ScanSearch className="mx-auto size-6 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">
            No findings match the current filters.
            {analysis.findings.length > 0 ? " Loosen the search or reset the filters." : " The analysis reported none."}
          </p>
        </div>
      ) : (
        <AnimatePresence mode="popLayout">
          <motion.div
            key={`${severity}-${bucket}-${query}`}
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.045 } } }}
          >
            <Accordion
              type="multiple"
              value={open}
              onValueChange={(value) => setOpen(Array.isArray(value) ? value : [value])}
              className="w-full space-y-2"
            >
              {visible.map((finding) => (
                <motion.div
                  key={finding.id}
                  variants={{
                    hidden: { opacity: 0, y: 10 },
                    show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] as const } },
                  }}
                >
                  <FindingRow finding={finding} />
                </motion.div>
              ))}
            </Accordion>
          </motion.div>
        </AnimatePresence>
      )}
    </section>
  );
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <AccordionItem value={finding.id} className="border-l-2 border-l-border/60 data-[state=open]:border-l-primary/70">
      <AccordionTrigger>
        <span className="flex min-w-0 flex-1 items-center gap-3">
          <span className={cn("size-2 shrink-0 rounded-[2px]", SEVERITY_SQUARE[finding.severity])} />
          <span className="font-mono text-[12px] text-muted-foreground">{finding.id}</span>
          <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-foreground">
            {truncate(finding.title === finding.detail ? finding.detail : `${finding.title} — ${finding.detail}`, 116)}
          </span>
        </span>
        <span className="hidden shrink-0 items-center gap-2 sm:flex">
          <Badge variant="outline" className="normal-case tracking-normal">
            {BUCKET_LABELS[finding.bucket] ?? finding.bucket}
          </Badge>
          <Badge variant={SEVERITY_BADGE[finding.severity]}>{finding.severity}</Badge>
        </span>
      </AccordionTrigger>

      <AccordionContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 sm:hidden">
          <Badge variant={SEVERITY_BADGE[finding.severity]}>{finding.severity}</Badge>
          <Badge variant="outline" className="normal-case tracking-normal">
            {BUCKET_LABELS[finding.bucket] ?? finding.bucket}
          </Badge>
        </div>

        <p className="max-w-4xl text-[13.5px] leading-relaxed text-foreground/90">{finding.detail}</p>

        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <Terminal className="size-3.5 text-primary" />
            <span className="hud-label">Evidence · read straight from the payload</span>
            <span className="font-mono text-[10px] text-muted-foreground">{finding.evidence.length} refs</span>
          </div>
          {finding.evidence.length > 0 ? (
            <div className="code-surface overflow-x-auto px-3 py-2.5">
              <ol className="space-y-1">
                {finding.evidence.map((entry, index) => {
                  const path = evidencePath(entry);
                  const value = path ? entry.slice(path.length + 1) : entry;
                  return (
                    <li key={`${finding.id}-ev-${index}`} className="flex gap-2 whitespace-pre-wrap">
                      <span className="select-none text-muted-foreground/70">
                        {String(index + 1).padStart(2, "0")}›
                      </span>
                      <span>
                        {path ? <span className="text-neon-cyan">{path}</span> : null}
                        {path ? <span className="text-muted-foreground">=</span> : null}
                        <span className="text-foreground/90">{value}</span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
          ) : (
            <p className="rounded-md border border-dashed border-border/70 px-3 py-2 font-mono text-[12px] text-muted-foreground">
              no evidence cited — treat this finding as unverified
            </p>
          )}
        </div>

        <div className="rounded-md border-l-2 border-primary/60 bg-primary/[0.06] p-3">
          <div className="mb-1 flex items-center gap-2">
            <Wrench className="size-3.5 text-primary" />
            <span className="hud-label text-primary/80">Recommendation</span>
          </div>
          <p className="text-[13.5px] leading-relaxed text-foreground/90">{finding.recommendation}</p>
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}
