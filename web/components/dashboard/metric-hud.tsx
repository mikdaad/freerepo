"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { AlertCircle, Info, ListChecks, TriangleAlert } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { analysisStats, BUCKET_LABELS, type Analysis, type Severity } from "@/lib/analysis";
import { cn } from "@/lib/utils";

const TONE: Record<
  Severity,
  { label: string; text: string; ring: string; bar: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  high: {
    label: "High severity",
    text: "text-neon-red",
    ring: "border-neon-red/45 shadow-glow-red",
    bar: "bg-neon-red",
    Icon: TriangleAlert,
  },
  medium: {
    label: "Medium severity",
    text: "text-neon-amber",
    ring: "border-neon-amber/40",
    bar: "bg-neon-amber",
    Icon: AlertCircle,
  },
  low: {
    label: "Low severity",
    text: "text-neon-cyan",
    ring: "border-neon-cyan/40",
    bar: "bg-neon-cyan",
    Icon: Info,
  },
};

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.1 } },
};

const item = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] as const } },
};

export function MetricHud({ analysis }: { analysis: Analysis }) {
  const stats = analysisStats(analysis);
  const total = Math.max(stats.total, 1);

  return (
    <motion.section
      variants={container}
      initial="hidden"
      animate="show"
      aria-label="Finding counts by severity"
      className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
    >
      {(Object.keys(TONE) as Severity[]).map((severity) => {
        const tone = TONE[severity];
        const value = stats.bySeverity[severity];
        const share = value / total;
        return (
          <motion.div key={severity} variants={item}>
            <Card className={cn("relative overflow-hidden transition-colors", value > 0 ? tone.ring : "border-border/60")}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <tone.Icon className={cn("size-3.5", tone.text)} />
                      <span className="hud-label">{tone.label}</span>
                    </div>
                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="hud-value">{value}</span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {(share * 100).toFixed(0)}% of findings
                      </span>
                    </div>
                  </div>
                  {severity === "high" && value > 0 ? (
                    <span className="mt-1 inline-flex items-center gap-1 rounded-md border border-neon-red/50 bg-neon-red/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-neon-red">
                      blocking
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 h-1 w-full overflow-hidden rounded-full bg-muted/60">
                  <motion.div
                    className={cn("h-full rounded-full", tone.bar)}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.round(share * 100)}%` }}
                    transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.25 }}
                  />
                </div>
              </CardContent>
            </Card>
          </motion.div>
        );
      })}

      <motion.div variants={item}>
        <Card className="h-full overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center gap-1.5">
              <ListChecks className="size-3.5 text-muted-foreground" />
              <span className="hud-label">Total findings</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="hud-value">{stats.total}</span>
              <span className="font-mono text-[11px] text-muted-foreground">
                {stats.evidenceLines} evidence {stats.evidenceLines === 1 ? "line" : "lines"}
              </span>
            </div>
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(stats.byBucket).map(([bucket, count]) => (
                <li
                  key={bucket}
                  className="rounded-md border border-border/60 bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
                  title={bucket}
                >
                  {BUCKET_LABELS[bucket] ?? bucket} <span className="text-foreground">{count}</span>
                </li>
              ))}
              {stats.total === 0 ? (
                <li className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  no findings reported
                </li>
              ) : null}
            </ul>
          </CardContent>
        </Card>
      </motion.div>
    </motion.section>
  );
}
