"""Pydantic models describing the pipeline's data contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Verdict = Literal["PASS", "FAIL"]


class PipelinePhase(BaseModel):
    phase: int
    name: str
    engine: str
    description: str


class SemanticMapping(BaseModel):
    """Output of Phase 2 — DeepSeek's semantic identification.

    The AI never measures anything; it only maps deterministic entity ids
    (DWG handles produced by the C# engine) to semantic roles.
    """

    building_lines: list[str] = Field(default_factory=list)
    boundary_lines: list[str] = Field(default_factory=list)
    rationale: str = ""


class VerificationResult(BaseModel):
    """Output of Phase 3 — deterministic Shapely math. The single source of
    truth for the PASS/FAIL verdict."""

    verdict: Verdict
    min_distance_m: float
    required_distance_m: float
    margin_m: float
    drawing_units: str
    unit_factor_to_meters: float
    distance_in_drawing_units: float
    closest_point_building: list[float] | None = None
    closest_point_boundary: list[float] | None = None
    building_entity_ids: list[str] = Field(default_factory=list)
    boundary_entity_ids: list[str] = Field(default_factory=list)
    skipped_entity_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComplianceReport(BaseModel):
    """Final payload streamed to the Next.js dashboard (event: `result`)."""

    report_id: str
    verdict: Verdict
    source_file: str
    created_at: str
    verification: VerificationResult
    mapping: SemanticMapping
    report_markdown: str
    persisted_to_database: bool = False
    cad_metadata: dict[str, Any] = Field(default_factory=dict)
