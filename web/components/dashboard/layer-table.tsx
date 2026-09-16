"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Hash, Lock, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { LayerFinding, Severity } from "@/lib/analysis";
import { cn } from "@/lib/utils";

/** Discipline prefix, per common CAD layer-naming conventions (NAS/NBS style). */
const PREFIX_TONE: Record<string, string> = {
  A: "text-neon-cyan",
  S: "text-neon-violet",
  E: "text-neon-amber",
  M: "text-neon-green",
  P: "text-neon-red",
  F: "text-neon-red",
  C: "text-neon-cyan",
  I: "text-neon-violet",
};

const SEVERITY_DOT: Record<Severity, string> = {
  high: "bg-neon-red",
  medium: "bg-neon-amber",
  low: "bg-neon-cyan",
};

export function LayerTable({ rows }: { rows: LayerFinding[] }) {
  const [query, setQuery] = React.useState("");

  const visible = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => `${row.layer} ${row.issue} ${row.evidence}`.toLowerCase().includes(needle));
  }, [query, rows]);

  const highCount = rows.filter((row) => row.severity === "high").length;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2 text-base">
            <Hash className="size-4 text-primary" />
            Layer analysis
          </CardTitle>
          <CardDescription className="mt-1">
            {rows.length} layer {rows.length === 1 ? "discrepancy" : "discrepancies"} flagged ·{" "}
            <span className={highCount ? "text-neon-red" : "text-muted-foreground"}>{highCount} blocking</span>
          </CardDescription>
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter layers…"
            aria-label="Filter layer findings"
            className="h-8 pl-8 font-mono text-[12px]"
            type="search"
          />
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <EmptyRow count={rows.length} visible={visible.length} />
        {visible.length > 0 ? (
          <div className="max-h-[62vh] overflow-auto">
            <table className="w-full min-w-[720px] border-collapse text-left text-[13px]">
              <thead className="sticky top-0 z-10 bg-card/95 backdrop-blur">
                <tr className="border-y border-border/60 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Layer</th>
                  <th className="px-4 py-2 font-medium">Issue</th>
                  <th className="px-4 py-2 font-medium">Evidence</th>
                  <th className="px-4 py-2 text-right font-medium">Sev</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row, index) => {
                  const prefix = /^[A-Za-z]/.exec(row.layer)?.[0]?.toUpperCase() ?? "";
                  return (
                    <motion.tr
                      key={`${row.layer}-${index}`}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.28, delay: Math.min(index, 12) * 0.03, ease: "easeOut" }}
                      className="group border-b border-border/35 align-top transition-colors last:border-0 hover:bg-muted/40"
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <Lock
                            className={cn(
                              "size-3 shrink-0",
                              row.severity === "high" ? "text-neon-red" : "text-transparent",
                            )}
                            aria-label="blocking"
                          />
                          <span className="font-mono text-[12.5px] text-foreground">{row.layer}</span>
                          {prefix ? (
                            <span
                              className={cn(
                                "rounded border border-border/60 px-1 font-mono text-[10px]",
                                PREFIX_TONE[prefix] ?? "text-muted-foreground",
                              )}
                              title={`layer group ${prefix}`}
                            >
                              {prefix}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-foreground/90">{row.issue}</td>
                      <td className="px-4 py-2.5">
                        <code className="block whitespace-pre-wrap break-words font-mono text-[11.5px] text-muted-foreground group-hover:text-foreground/80">
                          {row.evidence}
                        </code>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <span className="inline-flex items-center justify-end gap-1.5">
                          <span className={cn("size-1.5 rounded-full", SEVERITY_DOT[row.severity])} />
                          <span className="font-mono text-[11px] uppercase text-muted-foreground">{row.severity}</span>
                        </span>
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function EmptyRow({ count, visible }: { count: number; visible: number }) {
  if (count > 0 && visible === 0) {
    return (
      <div className="px-4 py-10 text-center">
        <Badge variant="ghost">no layer matches the filter</Badge>
      </div>
    );
  }
  if (count === 0) {
    return (
      <div className="px-4 py-12 text-center text-sm text-muted-foreground">
        No layer findings in this analysis — either the sheet is clean, or the review task did not emit any.
      </div>
    );
  }
  return null;
}
