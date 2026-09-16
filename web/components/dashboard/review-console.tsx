import type { ReactNode } from "react";
import { Boxes, ScanSearch } from "lucide-react";
import { DataGaps } from "@/components/dashboard/data-gaps";
import { DimensionTable } from "@/components/dashboard/dimension-table";
import { FindingsPanel } from "@/components/dashboard/findings-panel";
import { LayerTable } from "@/components/dashboard/layer-table";
import { MetricHud } from "@/components/dashboard/metric-hud";
import { StatusHeader } from "@/components/dashboard/status-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { analysisStats, type Analysis } from "@/lib/analysis";

/**
 * The dashboard itself: status bar, severity HUD and the three analysis tabs.
 *
 * It is a pure function of `analysis`, which is what lets the same component
 * render a file loaded on the server (`app/page.tsx`) and a response received
 * from `POST /api/analyze` without a reload.
 */
export function ReviewConsole({ analysis, toolbar }: { analysis: Analysis; toolbar?: ReactNode }) {
  const stats = analysisStats(analysis);

  return (
    <div className="space-y-4">
      {toolbar}

      <StatusHeader analysis={analysis} />
      <MetricHud analysis={analysis} />

      <Tabs defaultValue="critical" className="flex-col gap-0">
        <TabsList className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="critical" count={stats.total} tone="high">
            <ScanSearch className="size-3.5" />
            Critical Findings
          </TabsTrigger>
          <TabsTrigger value="layers" count={analysis.layerFindings.length}>
            <Boxes className="size-3.5" />
            Layer Analysis
          </TabsTrigger>
          <TabsTrigger value="dimensions" count={analysis.dimensionFindings.length}>
            <Boxes className="size-3.5" />
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
    </div>
  );
}
