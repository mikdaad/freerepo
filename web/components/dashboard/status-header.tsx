"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  CalendarClock,
  Database,
  ScanLine,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  TriangleAlert,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ConfidenceRing } from "@/components/dashboard/confidence-ring";
import type { Analysis, ReleaseVerdict } from "@/lib/analysis";
import { cn } from "@/lib/utils";

const VERDICTS: Record<
  ReleaseVerdict,
  { label: string; note: string; className: string; pulse: boolean; Icon: React.ComponentType<{ className?: string }> }
> = {
  hold: {
    label: "Hold",
    note: "do not issue until the high-severity findings are closed",
    className: "border-neon-red/60 bg-neon-red/12 text-neon-red",
    pulse: true,
    Icon: ShieldAlert,
  },
  release_with_comments: {
    label: "Release with comments",
    note: "issue with the listed comments attached to the transmittal",
    className: "border-neon-amber/55 bg-neon-amber/12 text-neon-amber",
    pulse: false,
    Icon: ShieldQuestion,
  },
  release: {
    label: "Cleared to release",
    note: "no blocking findings detected in the extracted data",
    className: "border-neon-green/55 bg-neon-green/12 text-neon-green",
    pulse: false,
    Icon: ShieldCheck,
  },
  unknown: {
    label: "No verdict",
    note: "the analysis did not return a release recommendation",
    className: "border-border/70 bg-muted/40 text-muted-foreground",
    pulse: false,
    Icon: ShieldQuestion,
  },
};

export function StatusHeader({ analysis }: { analysis: Analysis }) {
  const verdict = VERDICTS[analysis.releaseRecommendation];
  const { Icon } = verdict;
  const discipline = analysis.discipline;

  return (
    <motion.header
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
    >
      <Card className="overflow-hidden">
        <CardContent className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center lg:p-6">
          {/* identity */}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <ScanLine className="size-3.5 text-primary" />
              <span className="hud-label">Sheet under review</span>
            </div>
            <h1 className="mt-2 truncate font-mono text-xl font-semibold tracking-tight text-foreground sm:text-2xl lg:text-3xl">
              {analysis.drawing ?? "unnamed drawing"}
            </h1>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="normal-case tracking-normal">
                discipline:
                <span className="ml-1 font-mono text-foreground">{discipline.assigned ?? "undetermined"}</span>
              </Badge>
              {discipline.confirmed === true ? (
                <Badge variant="ok">confirmed</Badge>
              ) : discipline.confirmed === false ? (
                <Badge variant="medium">disputed</Badge>
              ) : (
                <Badge variant="ghost">not verified</Badge>
              )}
              <Badge variant="ghost" className="gap-1 normal-case tracking-normal">
                <Database className="size-3" />
                <span className="max-w-[42ch] truncate font-mono">{analysis.originLabel || "in-memory sample"}</span>
              </Badge>
              {analysis.warnings.length > 0 ? (
                <Badge variant="medium" className="gap-1">
                  <TriangleAlert className="size-3" />
                  {analysis.warnings.length} ingest note{analysis.warnings.length === 1 ? "" : "s"}
                </Badge>
              ) : null}
            </div>

            {discipline.comment ? (
              <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-muted-foreground">{discipline.comment}</p>
            ) : null}
          </div>

          {/* gate + metrics */}
          <div className="flex flex-wrap items-center gap-5 sm:gap-7">
            <div
              className={cn(
                "flex items-center gap-3 rounded-lg border px-4 py-3",
                verdict.className,
                verdict.pulse && "animate-glow-pulse",
              )}
              title={analysis.releaseRecommendationRaw ?? undefined}
            >
              <Icon className="size-6" />
              <div className="leading-tight">
                <div className="text-[10px] uppercase tracking-[0.2em] opacity-80">Release gate</div>
                <div className="text-base font-semibold">{verdict.label}</div>
              </div>
            </div>

            <div className="h-14 w-px rule-fade hidden sm:block" />

            <ConfidenceRing value={analysis.confidence} />

            <div className="min-w-[7rem] rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
              <div className="flex items-center gap-1.5">
                <CalendarClock className="size-3 text-muted-foreground" />
                <span className="hud-label">Rework estimate</span>
              </div>
              <div className="mt-1 font-mono text-2xl font-semibold tabular-nums leading-none">
                {analysis.effortHours === null ? "n/a" : analysis.effortHours}
                {analysis.effortHours === null ? null : <span className="ml-1 text-sm text-muted-foreground">h</span>}
              </div>
            </div>
          </div>

          <p className="lg:col-span-2 text-[12px] text-muted-foreground">
            <span className="font-mono text-foreground/80">{verdict.note}</span>
            {analysis.releaseRecommendationRaw &&
            analysis.releaseRecommendationRaw !== analysis.releaseRecommendation ? (
              <>
                {" · "}
                model said <span className="font-mono">“{analysis.releaseRecommendationRaw}”</span>
              </>
            ) : null}
          </p>
        </CardContent>
      </Card>
    </motion.header>
  );
}
