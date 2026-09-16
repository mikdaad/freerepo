"""Phase 2 — Semantic Identification (DeepSeek).

The AI's *only* job here is semantic mapping: given the deterministic export
(entity ids, layer names, text labels, block definitions), decide which entity
ids form the BUILDING PERIMETER and which form the BOUNDARY WALL.

It never receives a question about distances, and anything distance-shaped it
might volunteer is ignored downstream. All math happens in Phase 3.
"""

from __future__ import annotations

import json
import re

from openai import OpenAI

from app.config import Settings

from .errors import PipelineError

PHASE = 2

MAX_ENTITIES_IN_PROMPT = 600
MAX_TEXTS_IN_PROMPT = 120

SYSTEM_PROMPT = """\
You are the semantic identification module of a municipality CAD compliance pipeline.

You receive a machine-extracted summary of a DWG drawing: geometry entities with
stable ids (Line, LwPolyline, Insert), text labels, block definitions and layer names.

Your ONLY task is semantic mapping:
decide which entity ids form the BUILDING PERIMETER (the footprint / outer walls of
the building) and which ids form the BOUNDARY WALL (site boundary / property line /
boundary wall / fence line).

Rules:
- Use ONLY ids that appear in the provided "entities" list. Never invent ids.
- Prefer entities on layers whose names suggest their role (e.g. A-BLDG, WALL,
  BOUNDARY, SITE, PROPERTY); use texts and block names as supporting evidence.
- Include every id needed to fully describe each role; the perimeter and the
  boundary may each consist of several lines/polylines.
- Do NOT attempt measurements, distances or geometry reasoning of any kind; a
  deterministic engine performs all mathematics downstream.
- Respond with a single JSON object and nothing else, matching exactly:
  {"building_lines": ["<id>", ...], "boundary_lines": ["<id>", ...], \
"rationale": "<one short paragraph>"}
"""


def identify_entities(geometry: dict, settings: Settings) -> dict:
    """Return {"building_lines": [...], "boundary_lines": [...], "rationale": str}."""
    if settings.ai_is_mocked:
        return _mock_identify(geometry)
    return _llm_identify(geometry, settings)


# --- DeepSeek ---------------------------------------------------------------


def _llm_identify(geometry: dict, settings: Settings) -> dict:
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )

    user_payload = json.dumps(_summarize(geometry), separators=(",", ":"))

    try:
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            temperature=0.0,
            max_tokens=1024,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
        )
    except Exception as exc:  # network / auth / rate-limit
        raise PipelineError(PHASE, f"DeepSeek API call failed: {exc}") from exc

    raw = (response.choices[0].message.content or "").strip()
    parsed = _loads_lenient(raw)
    if not isinstance(parsed, dict):
        raise PipelineError(
            PHASE, f"DeepSeek returned unparsable JSON. Raw output: {raw[:500]}"
        )

    return _validate(parsed, known_ids(geometry))


def _summarize(geometry: dict) -> dict:
    """Compact drawing summary for the prompt — ids + semantics, no raw math."""
    entities = geometry.get("entities", [])

    def sort_key(entity: dict):
        # Closed polylines first (perimeter candidates), then longest entities.
        return (0 if entity.get("closed") else 1, -float(entity.get("length") or 0))

    entities = sorted(
        (e for e in entities if e.get("type") in ("Line", "LwPolyline", "Insert")),
        key=sort_key,
    )[:MAX_ENTITIES_IN_PROMPT]

    slim_entities = [
        {
            "id": e.get("id"),
            "type": e.get("type"),
            "layer": e.get("layer"),
            **({"closed": True} if e.get("closed") else {}),
            **({"length": round(float(e["length"]), 2)} if e.get("length") else {}),
            **({"block_name": e["block_name"]} if e.get("block_name") else {}),
        }
        for e in entities
    ]

    texts = [
        {"layer": t.get("layer"), "value": str(t.get("value", ""))[:80]}
        for t in geometry.get("texts", [])[:MAX_TEXTS_IN_PROMPT]
    ]

    return {
        "layers": geometry.get("layers", []),
        "entities": slim_entities,
        "texts": texts,
        "blocks": geometry.get("blocks", []),
    }


def _loads_lenient(raw: str):
    """Parse JSON that may be wrapped in code fences or prose."""
    if not raw:
        return None
    candidates = [raw]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL)
    candidates.extend(fenced)
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _validate(parsed: dict, known: set[str]) -> dict:
    """Clamp the model output to real entity ids; fail loudly if unusable."""

    def clean(key: str) -> list[str]:
        values = parsed.get(key) or []
        if not isinstance(values, list):
            return []
        seen: list[str] = []
        for value in values:
            item = str(value).strip().upper()
            # Tolerate models echoing "0x1F2" or lowercase handles.
            item = item.removeprefix("0X")
            if item in known and item not in seen:
                seen.append(item)
        return seen

    building = clean("building_lines")
    boundary = [b for b in clean("boundary_lines") if b not in building]
    rationale = str(parsed.get("rationale") or "").strip()

    if not building:
        raise PipelineError(
            PHASE, "DeepSeek could not identify any Building Perimeter entities."
        )
    if not boundary:
        raise PipelineError(
            PHASE, "DeepSeek could not identify any Boundary Wall entities."
        )

    return {
        "building_lines": building,
        "boundary_lines": boundary,
        "rationale": rationale,
    }


def known_ids(geometry: dict) -> set[str]:
    return {str(e.get("id", "")).upper() for e in geometry.get("entities", [])}


# --- Offline mock (MOCK_AI=true or missing key) -------------------------------

_BUILDING_HINTS = ("building", "perim", "footprint", "bldg", "house", "struct")
_BOUNDARY_HINTS = ("boundary", "bound", "site", "lot", "property", "wall", "fence", "plot", "limit")


def _mock_identify(geometry: dict) -> dict:
    """Deterministic keyword heuristic so the pipeline runs without an API key."""
    entities = [
        e for e in geometry.get("entities", []) if e.get("type") in ("Line", "LwPolyline")
    ]

    def layer_hits(entity: dict, hints: tuple[str, ...]) -> bool:
        layer = str(entity.get("layer", "")).lower()
        return any(hint in layer for hint in hints)

    building = [e["id"] for e in entities if layer_hits(e, _BUILDING_HINTS)]
    boundary = [
        e["id"]
        for e in entities
        if layer_hits(e, _BOUNDARY_HINTS) and e["id"] not in building
    ]

    # Fallbacks: largest closed polyline ≈ building; longest remaining line work ≈ boundary.
    if not building:
        closed = [e for e in entities if e.get("closed") and e.get("vertices")]
        if closed:
            biggest = max(closed, key=lambda e: float(e.get("length") or 0))
            building = [biggest["id"]]
    if not boundary:
        rest = [e for e in entities if e["id"] not in building]
        if rest:
            longest = max(rest, key=lambda e: float(e.get("length") or 0))
            boundary = [longest["id"]]

    if not building or not boundary:
        raise PipelineError(
            PHASE, "Mock mode could not infer building/boundary entities from this drawing."
        )

    return {
        "building_lines": building,
        "boundary_lines": boundary,
        "rationale": "(MOCK MODE) Keyword heuristic on layer names — replace with "
        "DeepSeek by setting DEEPSEEK_API_KEY.",
    }
