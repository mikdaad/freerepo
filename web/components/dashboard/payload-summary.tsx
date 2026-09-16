"use client";

import { motion } from "framer-motion";
import { Boxes, FileJson, Layers3, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { AnalyzeResponse } from "@/lib/api";
import { thousands } from "@/lib/utils";

/**
 * What the model was actually shown.
 *
 * The distinction matters for a review: an empty `findings` list means something
 * different when the payload was degraded than when the sheet is clean. This strip
 * is the answer to "did the model see my door schedule?", without opening payload.json.
 */
export function PayloadSummary({ response }: { response: AnalyzeResponse }) {
  const payload = response.payload ?? {};
  const truncations = Object.entries(payload.truncations ?? {});
  const degraded = payload.degraded ?? [];
  const counts = payload.counts ?? {};
  const budget = payload.token_budget ?? null;
  const estimate = payload.token_estimate ?? null;
  const share = budget && estimate ? Math.min(1, estimate / budget) : null;

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <Card className="border-border/60">
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
          <div className="flex items-center gap-2">
            <Boxes className="size-4 text-primary" />
            <span className="hud-label">Payload handed to the model</span>
          </div>

          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[12px]">
            <span className="text-foreground">{thousands(payload.chars ?? 0)} chars</span>
            <span className="text-muted-foreground">
              ~<span className="text-foreground">{thousands(estimate ?? 0)}</span> tokens
              {budget ? <span className="text-muted-foreground"> / {thousands(budget)} budget</span> : null}
            </span>
            {share !== null ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-muted/70">
                  <motion.span
                    className="block h-full rounded-full bg-primary/70"
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.round(share * 100)}%` }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                  />
                </span>
                <span className="text-muted-foreground">{(share * 100).toFixed(0)}%</span>
              </span>
            ) : null}
            {payload.prompt_tokens_actual ? (
              <span className="text-muted-foreground">actual prompt {thousands(payload.prompt_tokens_actual)}</span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {Object.entries(counts).map(([key, value]) => (
              <Badge key={key} variant="outline" className="normal-case tracking-normal">
                {key} <span className="ml-1 font-mono text-foreground">{value}</span>
              </Badge>
            ))}
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            {response.mode ? (
              <Badge variant="ghost" className="gap-1 normal-case">
                <Layers3 className="size-3" />
                {response.mode}
              </Badge>
            ) : null}
            {degraded.length > 0 ? (
              <Badge variant="medium" className="gap-1 normal-case" title={degraded.join(", ")}>
                <TriangleAlert className="size-3" />
                degraded ×{degraded.length}
              </Badge>
            ) : null}
            {truncations.length > 0 ? (
              <Badge variant="high" className="gap-1 normal-case" title={truncations.map(([k, v]) => `${k}: ${v} dropped`).join(", ")}>
                <FileJson className="size-3" />
                {truncations.map(([k, v]) => `${k} −${v}`).join(" · ")}
              </Badge>
            ) : null}
            {typeof payload.budget_exceeded_by === "number" && payload.budget_exceeded_by > 0 ? (
              <Badge variant="high">over budget by {thousands(payload.budget_exceeded_by)} tokens</Badge>
            ) : null}
            {response.artifact_dir ? (
              <span className="font-mono text-[11px] text-muted-foreground">artifacts: {response.artifact_dir}</span>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
