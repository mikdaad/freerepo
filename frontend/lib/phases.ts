import type { PhaseState } from "./api";

/** Static mirror of the backend's PIPELINE_PHASES, shown before a run starts. */
export const DEFAULT_PHASES: PhaseState[] = [
  {
    phase: 1,
    name: "Deterministic Extraction",
    engine: "C# · ACadSharp",
    description:
      "Parse the DWG and export exact coordinates, layers and block attributes to cad_geometry.json.",
    status: "pending",
  },
  {
    phase: 2,
    name: "Semantic Identification",
    engine: "DeepSeek",
    description:
      "Map entity ids to the Building Perimeter and the Boundary Wall. No measurements.",
    status: "pending",
  },
  {
    phase: 3,
    name: "Mathematical Verification",
    engine: "Python · Shapely",
    description:
      "Compute the exact minimum setback distance and compare it to the municipal rule.",
    status: "pending",
  },
  {
    phase: 4,
    name: "Compliance Reporting",
    engine: "DeepSeek",
    description:
      "Draft the formal municipality compliance report from the exact figures.",
    status: "pending",
  },
];

export function freshPhases(): PhaseState[] {
  return DEFAULT_PHASES.map((phase) => ({ ...phase }));
}
