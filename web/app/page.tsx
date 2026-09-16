import { Activity, Boxes, CircleDot, Layers, Ruler, ScanSearch } from "lucide-react";
import { BlueprintBackground } from "@/components/dashboard/blueprint-bg";
import { DataGaps } from "@/components/dashboard/data-gaps";
import { DimensionTable } from "@/components/dashboard/dimension-table";
import { FindingsPanel } from "@/components/dashboard/findings-panel";
import { LayerTable } from "@/components/dashboard/layer-table";
import { MetricHud } from "@/components/dashboard/metric-hud";
import { StatusHeader } from "@/components/dashboard/status-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { analysisStats, normalizeAnalysis, type Analysis } from "@/lib/analysis";
import { loadAnalysisSource } from "@/lib/analysis-source";

/**
 * Sample payload, exactly the shape `analysis.json` has when the pipeline is run with
 * `--task sheet_review` (see `cad2ai/prompts.py` → TASKS["sheet_review"]).
 *
 * The content is a typical architectural sheet: overridden dimension text, a locked
 * structural layer on an undefined linetype, missing door fire ratings, template baggage.
 * Delete nothing here — the dashboard is meant to render from a real file; this object
 * only exists so the UI is testable without API keys or a DWG.
 */
const SAMPLE_ANALYSIS = {
  drawing: "A-101-FLOOR-PLAN-R2018.dwg",
  discipline: {
    assigned: "architectural",
    confirmed: false,
    comment:
      "Layer prefixes are architectural (A-/S-) with 3/32 annotation sizing, but two M- layers carry real geometry; confirm this is not a mixed trade sheet before judging annotation standards.",
  },
  confidence: 0.78,
  findings: [
    {
      id: "F1",
      bucket: "missing_information",
      severity: "high",
      title: "Fire rating missing on 3 of 12 door references",
      detail:
        "The DOOR_STD block definition declares a FIRE_RATING attribute, yet 3 of its 12 references leave it empty, so a door schedule cannot be generated from this sheet and fire-separation intent cannot be verified. Handles were not captured (include-handles is off), so the exact inserts cannot be named from this payload.",
      evidence: [
        "blocks.items[0].name=DOOR_STD",
        "blocks.items[0].refs=12",
        "blocks.items[0].attribute_fill.FIRE_RATING=0.75",
        "text_stats.attribs=37",
      ],
      recommendation:
        "Populate FIRE_RATING on the three doors from the door schedule, then re-run with --include-handles so the next review can point at the specific INSERT entities.",
    },
    {
      id: "F2",
      bucket: "data_quality",
      severity: "high",
      title: "Nine dimensions are typed labels, not measurements",
      detail:
        "Nine dimension objects carry overridden text, which hides the measured value behind typed text. Two of them disagree with their own measurement, so the sheet looks fully dimensioned while those lengths are unverifiable.",
      evidence: [
        "dimension_stats.total=146",
        "dimension_stats.with_text_override=9",
        "dimensions[14].text=12000 TYP",
        "dimensions[14].value=11875",
      ],
      recommendation:
        "Remove the overrides (DIMU → re-measure), and express true typicals with a note or a leader instead of dimension text. Re-issue only when with_text_override is 0 or explicitly accepted.",
    },
    {
      id: "F3",
      bucket: "standards_issues",
      severity: "medium",
      title: "S-COLS references an undefined linetype",
      detail:
        "Layer S-COLS is assigned linetype HIDDEN, which does not exist in the LTYPE table. Plotters silently fall back to CONTINUOUS, so hidden linework inside the column schedule prints as visible geometry.",
      evidence: [
        "layers[6].name=S-COLS",
        "layers[6].linetype=HIDDEN",
        "layer_stats.linetypes_undefined=[\"HIDDEN\"]",
        "layers[6].locked=true",
      ],
      recommendation:
        "Load the office linetype definition (or acadiso.lin) into the drawing, redefine HIDDEN, then unlock and re-assign. Add the linetype to the template so it cannot drift again.",
    },
    {
      id: "F4",
      bucket: "standards_issues",
      severity: "medium",
      title: "Two annotation text heights against a 3.2 mm standard",
      detail:
        "Annotation text mixes 2.5 mm and 3.2 mm heights on the same sheet. At the plotted scale the 2.5 mm group falls below the office minimum, so roughly a quarter of the notes will be hard to read on site.",
      evidence: [
        "text_stats.heights={\"2.5\":21,\"3.2\":63}",
        "layers[3].name=A-ANNO-TEXT",
        "text_styles[1].name=STANDARD",
      ],
      recommendation:
        "Batch-set the 21 short notes to the 3.2 mm style, then lock the default height for A-ANNO-TEXT in the template and re-plot a check sheet.",
    },
    {
      id: "F5",
      bucket: "complexity",
      severity: "low",
      title: "Template baggage: 4 unused layers, 1 unused block, 12 empty layouts",
      detail:
        "Unused content inflates the file, the layer manager and every downstream count, but nothing of it plots. It is a hygiene issue, not a construction risk, and it is safe to purge before issue.",
      evidence: [
        "layers[11].name=A-DEAD",
        "layers[11].entities=0",
        "block_stats.unused=1",
        "layouts_total=14",
      ],
      recommendation:
        "PURGE (include zero-object layers and empty layouts), AUDIT, and keep the protected template layers on the do-not-purge list.",
    },
    {
      id: "F6",
      bucket: "missing_information",
      severity: "medium",
      title: "No plotted-scale annotation on the sheet layout",
      detail:
        "Units are millimetres and a paper-space layout exists, but no scale text was captured on it, so the declared print scale cannot be cross-checked against the dimension values.",
      evidence: [
        "document.units.name=Millimeters",
        "layouts[1].name=Sheet-101",
        "layouts[1].text_count=0",
      ],
      recommendation:
        "Add a SCALE attribute to the title block (driven from the viewport scale) so sheet-level QA can compare declared scale with measured lengths.",
    },
  ],
  layer_findings: [
    {
      layer: "A-DEAD",
      issue: "Frozen layer with 0 entities — template carry-over",
      evidence: "layers[11].entities=0 · frozen=true · plotted=true",
    },
    {
      layer: "P-EQ",
      issue: "Layer is OFF but contains 14 entities, including 3 dimensions that will not plot",
      evidence: "layers[8].on=false · layers[8].entities=14 · layers[8].dimensions=3",
    },
    {
      layer: "S-COLS",
      issue: "Locked layer references linetype HIDDEN, which is not defined in the LTYPE table",
      evidence: "layers[6].linetype=HIDDEN · layer_stats.linetypes_undefined=[\"HIDDEN\"]",
    },
    {
      layer: "E-PWR",
      issue: "22 power objects drawn on A-WALL instead of E-PWR (layer mismatch)",
      evidence: "layers[5].entities=6 · layers[2].entities=312 · entities.by_type.LINE=312",
    },
    {
      layer: "M-GEOM",
      issue: "Mechanical geometry on a sheet classified architectural",
      evidence: "layers[9].name=M-GEOM · layers[9].entities=26 · discipline.candidates.mechanical=0.31",
    },
    {
      layer: "X-TEMPLATE-UNUSED",
      issue: "No geometry, no annotations; purge candidate",
      evidence: "layers[13].entities=0 · layers[13].annotations=0",
    },
  ],
  dimension_findings: [
    {
      kind: "text_override",
      count: 9,
      issue: "Dimension text typed over the measured value",
      evidence: "dimension_stats.with_text_override=9",
    },
    {
      kind: "unused_dimstyle",
      count: 3,
      issue: "Dimension styles defined but referenced by no dimension",
      evidence: "dimension_styles[2].used_by=0 · dimension_styles_total=7",
    },
    {
      kind: "unmeasured",
      count: 2,
      issue: "Dimensions that do not measure their own extension lines",
      evidence: "dimension_stats.unmeasured=2",
    },
    {
      kind: "proxy_in_dimblock",
      count: 1,
      issue: "Dimension block contains proxy entities; geometry not interpretable",
      evidence: "stats.proxies.count=1",
    },
    {
      kind: "decimal_inconsistency",
      count: 4,
      issue: "dimdec alternates between 0 and 2 decimals within the same wall run",
      evidence: "dimensions[22].text≠dimensions[23].text",
    },
  ],
  checks_not_possible_from_data: [
    "Overlapping or double-drawn linework (needs geometry, not counts)",
    "Plot style table (CTB/STB) colour-to-weight mapping",
    "Title block legibility at the plotted paper size",
    "Coordination with the linked structural model (xref freshness is not exposed)",
  ],
  data_gaps: [
    "Handles were excluded from the payload (include_handles=false): findings cannot name the exact entities",
    "Text list was capped: 41 of 103 text items are not represented",
    "No block definitions for the M- layers; the mechanical overlay was drawn, not inserted",
  ],
  release_recommendation: "hold",
  effort_hours_estimate: 6,
};

/**
 * Read from disk at request time (no cache) so dropping a new `analysis.json`
 * into `out/<run>/` and refreshing is enough — useful while iterating.
 */
export const dynamic = "force-dynamic";

export default function SheetReviewPage() {
  const source = loadAnalysisSource();
  const normalized = normalizeAnalysis(source.raw ?? SAMPLE_ANALYSIS);
  // The origin/label/warnings are ingest metadata, not model output: they are
  // attached here so every panel can say where its data came from.
  const analysis: Analysis = {
    ...normalized,
    origin: source.origin === "file" ? "file" : "mock",
    originLabel: source.origin === "file" ? source.label : "bundled sample payload (no analysis.json found)",
    warnings: [...source.notes, ...normalized.warnings],
  };

  const stats = analysisStats(analysis);

  return (
    <main className="relative min-h-screen">
      <BlueprintBackground />

      <div className="mx-auto w-full max-w-[1680px] space-y-4 px-3 py-4 sm:px-5 sm:py-6 lg:px-8">
        {/* utility strip: what am I looking at, and is it real data? */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-[11px]">
          <div className="flex items-center gap-2 font-mono uppercase tracking-[0.22em] text-muted-foreground">
            <Activity className="size-3.5 text-primary" />
            cad2ai
            <span className="text-border">/</span>
            sheet review console
          </div>
          <div className="flex flex-wrap items-center gap-3 font-mono text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2 py-1">
              <CircleDot
                className={
                  analysis.origin === "file" ? "size-3 text-neon-green" : "size-3 text-neon-amber"
                }
              />
              {analysis.origin === "file" ? "live analysis.json" : "sample data"}
            </span>
            <span className="hidden sm:inline">
              {stats.total} findings · {stats.blockers} blocking · {stats.evidenceLines} evidence refs
            </span>
          </div>
        </div>

        <StatusHeader analysis={analysis} />
        <MetricHud analysis={analysis} />

        <Tabs defaultValue="critical" className="flex-col gap-0">
          <TabsList className="w-full justify-start overflow-x-auto">
            <TabsTrigger value="critical" count={stats.total} tone="high">
              <ScanSearch className="size-3.5" />
              Critical Findings
            </TabsTrigger>
            <TabsTrigger value="layers" count={analysis.layerFindings.length}>
              <Layers className="size-3.5" />
              Layer Analysis
            </TabsTrigger>
            <TabsTrigger value="dimensions" count={analysis.dimensionFindings.length}>
              <Ruler className="size-3.5" />
              Dimension Analysis
            </TabsTrigger>
          </TabsList>

          <TabsContent value="critical">
            <FindingsPanel analysis={analysis} />
          </TabsContent>
          <TabsContent value="layers">
            <LayerTable rows={analysis.layerFindings} />
          </TabsContent>
          <TabsContent value="dimensions">
            <DimensionTable rows={analysis.dimensionFindings} />
          </TabsContent>
        </Tabs>

        <DataGaps analysis={analysis} />

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/40 pt-4 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5 font-mono">
            <Boxes className="size-3.5" />
            every finding cites a payload path; expand a finding to see the evidence block
          </span>
          <span className="font-mono">{analysis.drawing ?? "—"}</span>
        </footer>
      </div>
    </main>
  );
}
