"""Phase 4 — Compliance Reporting (DeepSeek).

The exact mathematical result from Phase 3 is fed back into DeepSeek, whose
only job now is prose: drafting a formal, human-readable municipality
compliance report. The model is explicitly forbidden from recomputing or
altering any number; the PASS/FAIL verdict was already decided by Shapely.
"""

from __future__ import annotations

import json

from openai import OpenAI

from app.config import Settings

from .errors import PipelineError

PHASE = 4

SYSTEM_PROMPT = """\
You are a senior building-code compliance officer drafting a formal report for a
municipality. You are given the EXACT, deterministic results of a setback
verification between a building perimeter and a boundary wall.

Write a formal compliance report in Markdown with these sections:
1. Title and reference line (use the report id and source file).
2. Executive Summary — one paragraph stating the verdict up front.
3. Methodology — explain the hybrid pipeline: deterministic CAD extraction (C#/ACadSharp),
   AI semantic identification (DeepSeek), deterministic measurement (Shapely),
   and emphasize that all mathematics was computed, never estimated by AI.
4. Findings — the measured minimum distance, the required minimum, the margin,
   drawing units, and the entity ids used (quote them verbatim).
5. Determination — PASS or FAIL and what it means for the permit application.
6. Notes / Limitations — include any provided warnings verbatim.

HARD RULES:
- NEVER recompute, alter, round differently, or invent numbers. Use the provided
  figures verbatim.
- Keep a neutral, administrative tone. No emojis. Maximum ~450 words.
"""


def generate_report(
    *,
    report_id: str,
    source_file: str,
    mapping: dict,
    verification: dict,
    settings: Settings,
) -> str:
    if settings.ai_is_mocked:
        return _mock_report(report_id, source_file, mapping, verification)

    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )

    facts = {
        "report_id": report_id,
        "source_file": source_file,
        "municipality_rule": {
            "type": "minimum_setback",
            "required_meters": verification["required_distance_m"],
        },
        "deterministic_result": verification,
        "ai_semantic_mapping": mapping,
    }

    try:
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            temperature=0.2,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Draft the report from these facts:\n"
                    + json.dumps(facts, indent=2),
                },
            ],
        )
    except Exception as exc:
        raise PipelineError(PHASE, f"DeepSeek report generation failed: {exc}") from exc

    markdown = (response.choices[0].message.content or "").strip()
    if not markdown:
        raise PipelineError(PHASE, "DeepSeek returned an empty report.")
    return markdown


# --- Offline mock -------------------------------------------------------------


def _mock_report(report_id: str, source_file: str, mapping: dict, verification: dict) -> str:
    verdict = verification["verdict"]
    distance = verification["min_distance_m"]
    required = verification["required_distance_m"]
    margin = verification["margin_m"]
    outcome = (
        "meets the required minimum setback"
        if verdict == "PASS"
        else "does NOT meet the required minimum setback"
    )
    warnings = "\n".join(f"- {w}" for w in verification.get("warnings", [])) or "- None."

    return f"""# Municipality Compliance Report

**Report ID:** `{report_id}`
**Source drawing:** `{source_file}`
**Rule:** Minimum setback {required} m between building perimeter and boundary wall

## Executive Summary

The deterministic verification of the submitted drawing determined a minimum
distance of **{distance} m** between the building perimeter and the boundary
wall. The submission **{verdict}s** the municipal requirement: it {outcome}.

> *(MOCK MODE — this report was generated from a local template. Set
> `DEEPSEEK_API_KEY` to have DeepSeek draft the formal report.)*

## Methodology

1. **Deterministic extraction** — the C# engine (ACadSharp) parsed the DWG and
   exported exact coordinates to `cad_geometry.json`.
2. **Semantic identification** — entity ids were mapped to the Building
   Perimeter and Boundary Wall roles (AI performs no measurements).
3. **Mathematical verification** — Shapely computed the exact minimum distance
   and compared it against the rule. The verdict comes from this step only.
4. **Reporting** — the narrative you are reading was drafted from the exact
   figures above.

## Findings

| Measure | Value |
| --- | --- |
| Minimum distance | {distance} m |
| Required minimum | {required} m |
| Margin | {margin:+} m |
| Drawing units | {verification.get('drawing_units')} |
| Building entities | {', '.join(verification.get('building_entity_ids', []))} |
| Boundary entities | {', '.join(verification.get('boundary_entity_ids', []))} |

## Determination

**{verdict}** — {"the permit application may proceed to the next review stage." if verdict == "PASS" else "the plan must be revised to restore the required setback before resubmission."}

## Notes / Limitations

{warnings}
"""
