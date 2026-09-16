"""Phase 3 — Mathematical Verification (deterministic).

Pure Shapely math: build geometries from the exact coordinates exported by the
C# engine, compute the true minimum distance between the AI-identified
building perimeter and boundary wall, and compare it against the municipality
rule. The PASS/FAIL verdict is produced here and ONLY here — the LLM never
participates in this decision.
"""

from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from .errors import PipelineError

PHASE = 3

# INSUNITS header value -> meters (AutoCAD standard unit names).
_UNIT_TO_METERS: dict[str, float] = {
    "millimeter": 0.001,
    "centimeter": 0.01,
    "decimeter": 0.1,
    "meter": 1.0,
    "kilometer": 1000.0,
    "inch": 0.0254,
    "foot": 0.3048,
    "yard": 0.9144,
}


def _unit_factor(units: str | None, warnings: list[str]) -> float:
    key = str(units or "").strip().lower().removesuffix("s")
    factor = _UNIT_TO_METERS.get(key)
    if factor is None:
        warnings.append(
            f"Unknown drawing units '{units}' — assuming meters. "
            "Check the DWG INSUNITS setting if results look wrong."
        )
        return 1.0
    return factor


def _to_shapely(entity: dict, warnings: list[str]):
    """Convert one extracted entity into a Shapely geometry (or None)."""
    etype = entity.get("type")

    if etype == "Line":
        start, end = entity.get("start"), entity.get("end")
        if start and end:
            return LineString([tuple(start[:2]), tuple(end[:2])])

    elif etype == "LwPolyline":
        vertices = entity.get("vertices") or []
        points = [tuple(v[:2]) for v in vertices if isinstance(v, list) and len(v) >= 2]
        if len(points) >= 3 and entity.get("closed"):
            return Polygon(points)
        if len(points) >= 2:
            return LineString(points)

    elif etype == "Insert":
        position = entity.get("position")
        if position:
            warnings.append(
                f"Entity {entity.get('id')} is a block Insert "
                f"('{entity.get('block_name')}') — measured from its insertion "
                "point only; explode the block for exact geometry."
            )
            return Point(tuple(position[:2]))

    return None


def _collect(geometry: dict, ids: list[str], role: str, warnings: list[str]):
    by_id = {str(e.get("id", "")).upper(): e for e in geometry.get("entities", [])}
    shapes, used, skipped = [], [], []

    for raw_id in ids:
        entity_id = str(raw_id).strip().upper().removeprefix("0X")
        entity = by_id.get(entity_id)
        if entity is None:
            warnings.append(f"{role}: entity id '{raw_id}' not found in the drawing.")
            skipped.append(str(raw_id))
            continue
        shape = _to_shapely(entity, warnings)
        if shape is None or shape.is_empty:
            warnings.append(
                f"{role}: entity '{entity_id}' ({entity.get('type')}) has no "
                "usable geometry and was skipped."
            )
            skipped.append(entity_id)
            continue
        shapes.append(shape)
        used.append(entity_id)

    if not shapes:
        raise PipelineError(
            PHASE, f"No usable geometry for the {role}. Check the semantic mapping."
        )
    return unary_union(shapes), used, skipped


def verify_setback(geometry: dict, mapping: dict, min_setback_meters: float) -> dict:
    """Compute the exact minimum setback and compare it against the rule."""
    warnings: list[str] = []

    building, building_ids, skipped_b = _collect(
        geometry, mapping.get("building_lines", []), "Building Perimeter", warnings
    )
    boundary, boundary_ids, skipped_w = _collect(
        geometry, mapping.get("boundary_lines", []), "Boundary Wall", warnings
    )

    distance_units = float(building.distance(boundary))
    closest_building, closest_boundary = nearest_points(building, boundary)

    units_name = (geometry.get("metadata") or {}).get("units", "Unknown")
    factor = _unit_factor(units_name, warnings)
    distance_m = distance_units * factor
    margin = distance_m - min_setback_meters

    return {
        "verdict": "PASS" if distance_m >= min_setback_meters else "FAIL",
        "min_distance_m": round(distance_m, 4),
        "required_distance_m": min_setback_meters,
        "margin_m": round(margin, 4),
        "drawing_units": units_name,
        "unit_factor_to_meters": factor,
        "distance_in_drawing_units": round(distance_units, 6),
        "closest_point_building": [
            round(closest_building.x, 4),
            round(closest_building.y, 4),
        ],
        "closest_point_boundary": [
            round(closest_boundary.x, 4),
            round(closest_boundary.y, 4),
        ],
        "building_entity_ids": building_ids,
        "boundary_entity_ids": boundary_ids,
        "skipped_entity_ids": sorted(set(skipped_b) | set(skipped_w)),
        "warnings": warnings,
    }
