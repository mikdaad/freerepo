"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { MoveRight, Ruler } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { DimensionFinding } from "@/lib/analysis";
import { cn } from "@/lib/utils";

/**
 * Dimension findings are counts of a *class* of problem (overridden text,
 * non-measured dims, unused dimstyles…), so the bar is relative to the largest
 * class in this sheet — the point is "where do I start".
 */
export function DimensionTable({ rows }: { rows: DimensionFinding[] }) {
  const max = React.useMemo(() => {
    const values = rows.map((row) => row.count ?? 0);
    return Math.max(1, ...values);
  }, [rows]);
  const affected = rows.reduce((sum, row) => sum + (row.count ?? 0), 0);

  if (rows.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Ruler className="size-4 text-primary" />
            Dimension analysis
          </CardTitle>
          <CardDescription>
            No dimension findings were reported. Note that the Autodesk fallback path cannot see dimensions at all —
            check <code className="font-mono text-[12px]">source.lossless</code> in the payload before reading that as “clean”.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Ruler className="size-4 text-primary" />
          Dimension analysis
        </CardTitle>
        <CardDescription>
          {rows.length} dimension {rows.length === 1 ? "class" : "classes"} ·{" "}
          <span className="text-foreground">{affected}</span> dimension{affected === 1 ? "" : "s"} affected on this sheet
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-y border-border/60 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                <th className="px-4 py-2 font-medium">Class</th>
                <th className="px-4 py-2 font-medium w-40">Share</th>
                <th className="px-4 py-2 font-medium">Issue</th>
                <th className="px-4 py-2 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const share = (row.count ?? 0) / max;
                return (
                  <motion.tr
                    key={`${row.kind}-${index}`}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.28, delay: Math.min(index, 12) * 0.03, ease: "easeOut" }}
                    className="group border-b border-border/35 align-top last:border-0 hover:bg-muted/40"
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12.5px] text-neon-cyan">{row.kind}</span>
                        <span className="rounded border border-border/60 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-foreground">
                          {row.count === null ? "n/a" : row.count}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                        <motion.div
                          className={cn(
                            "h-full rounded-full",
                            share > 0.75 ? "bg-neon-red" : share > 0.4 ? "bg-neon-amber" : "bg-neon-cyan",
                          )}
                          initial={{ width: 0 }}
                          animate={{ width: `${Math.max(4, Math.round(share * 100))}%` }}
                          transition={{ duration: 0.7, delay: 0.1 + index * 0.05, ease: [0.22, 1, 0.36, 1] }}
                        />
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-foreground/90">{row.issue}</td>
                    <td className="px-4 py-2.5">
                      <code className="flex items-start gap-1 whitespace-pre-wrap break-words font-mono text-[11.5px] text-muted-foreground group-hover:text-foreground/80">
                        <MoveRight className="mt-0.5 size-3 shrink-0 text-muted-foreground/60" aria-hidden />
                        {row.evidence}
                      </code>
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
