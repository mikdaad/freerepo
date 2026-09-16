import { EyeOff, FileWarning, ShieldHalf } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Analysis } from "@/lib/analysis";

/**
 * What the reviewer must NOT read as “clean”.
 *
 * `checks_not_possible_from_data` and `data_gaps` are part of the prompt contract:
 * the model is required to list what it could not verify from the extracted JSON.
 * Surfacing them next to the findings is the difference between a decision tool
 * and a false sense of security.
 */
export function DataGaps({ analysis }: { analysis: Analysis }) {
  const { checksNotPossible, dataGaps, warnings } = analysis;
  if (checksNotPossible.length === 0 && dataGaps.length === 0 && warnings.length === 0) return null;

  return (
    <section className="grid gap-3 lg:grid-cols-3" aria-label="Review limitations">
      {checksNotPossible.length > 0 ? (
        <Card className="border-neon-amber/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <EyeOff className="size-4 text-neon-amber" />
              Not checkable from CAD data
            </CardTitle>
            <CardDescription>
              Requires eyes on the plot, the model, or the site — no JSON extraction can confirm these.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <ul className="space-y-1.5">
              {checksNotPossible.map((entry, index) => (
                <li key={`check-${index}`} className="flex gap-2 text-[13px] leading-relaxed text-foreground/85">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-neon-amber" />
                  <span>{entry}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {dataGaps.length > 0 ? (
        <Card className="border-neon-cyan/25">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <FileWarning className="size-4 text-neon-cyan" />
              Data gaps in the payload
            </CardTitle>
            <CardDescription>
              Inputs the analysis asked for but did not receive; often a budget or capture-scope issue.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <ul className="space-y-1.5">
              {dataGaps.map((entry, index) => (
                <li key={`gap-${index}`} className="flex gap-2 text-[13px] leading-relaxed text-foreground/85">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-neon-cyan" />
                  <span>{entry}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {warnings.length > 0 ? (
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <ShieldHalf className="size-4 text-muted-foreground" />
              Ingest notes
            </CardTitle>
            <CardDescription>
              Normaliser observations about this file: malformed fields, rescaled values, skipped entries.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <ul className="space-y-1.5">
              {warnings.map((entry, index) => (
                <li key={`warn-${index}`} className="text-[13px] leading-relaxed text-muted-foreground">
                  <Badge variant="ghost" className="mr-2 align-middle">
                    note
                  </Badge>
                  {entry}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
