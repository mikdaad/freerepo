"""Heuristic discipline classification (architectural vs. mechanical vs. ...).

There is no flag in a DWG that says "this is a mechanical drawing".  What *is*
reliable is convention: layer naming standards (``A-WALL``, ``M-GEAR``,
``S-BEAM``), the linetypes in use (``CENTER``/``HIDDEN`` are mechanical,
``HIDDEN``/``DASH`` appear in architectural sections), and whether the drawing
holds 3D solids or 2D sheet geometry.

The classifier is deliberately transparent: it returns the *signals* it used and
a normalised confidence, so the model can disagree with it and so a reviewer can
see why a drawing was labelled the way it was.  It never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = ["DisciplineProfile", "PROFILES", "infer_discipline", "score_layers"]

#: discipline -> (regexes matched against the upper-cased layer name, weight)
PROFILES: dict[str, tuple[tuple[str, float], ...]] = {
    "architectural": (
        (r"^A[-_]", 3.0),
        (r"^AR[-_]", 3.0),
        (r"\bWALL", 2.0),
        (r"\b(DOOR|WINDOW|GLAZ|CASework|CASEWORK)", 2.0),
        (r"\b(ROOM|SPACE|AREA)\b", 1.5),
        (r"\b(GRID|AXIS|ELEV|SECTION|DETAIL|PLAN|CALL| anno|ANNO|TEXT|TITLE)", 1.5),
        (r"\b(CEIL|ROOF|FLOOR|FINISH|TRIM|STAIR|RAIL)\b", 2.0),
        (r"^(\d?[A-Z]?[-_])?(FL|POC|RCP|REF|SCT|ELEV)[-_]", 1.5),
    ),
    "structural": (
        (r"^S[-_]", 3.0),
        (r"^ST(R|-)?", 2.5),
        (r"\b(FOUND|FOOT|PILE|GRADE|SLAB|DECK|BEAM|COLU?MN|GIRDER)\b", 2.5),
        (r"\b(REINF|REBAR|BARS?|TENDON|STEEL|CONCRETE|EMBED)\b", 2.5),
        (r"\b(STRUCT|SHEAR|LATERAL|RETAIN|ANCHOR)\b", 2.5),
        (r"^S-(BFND|COL|FRM|OPNG|ROOF|SLAB|STEEL)", 3.0),
    ),
    "mechanical": (
        (r"^M[-_]", 3.0),
        (r"\b(MACH|MECH|PART|ASSEMBL|DETAIL|GEAR|SHAFT|BEARING|BOLT|NUT|SCREW|WELD)\b", 2.5),
        (r"\b(TOL|GD&T|GDT|FIT|SURFACE FINISH|CHAMFER|THREAD|HOLE|PROFILE)\b", 2.5),
        (r"\b(SHEET METAL|SHTMET|FLANGE|BRAKE|Laser|LASER|WATERJET)\b", 2.0),
        (r"\b(EXPLOS|BOM|ITEM|BALLOON|CALL OUT|CALLOUT)\b", 2.0),
        (r"\b(3D|MODEL|SOLID)\b", 1.0),
    ),
    "electrical": (
        (r"^E[-_]", 3.0),
        (r"\b(ELEC|PANEL|CIRCUIT|WIRE|CONDUIT|LIGHT|LUM|RECEPT|SWITCH|BREAKER|POWER|BUSBAR)\b", 2.5),
        (r"\b(CTRL|INSTR|LV|MCCV|TRAY)\b", 2.0),
    ),
    "plumbing": (
        (r"^P[-_]", 2.5),
        (r"\b(PLM|PLUMB|PIPE|DRAIN|VENT|FIXTURE|WATER|SANIT|SEWER|SUMP|COLD|HOT|BP|RW)\b", 2.5),
        (r"\b(ISO|AXON|RISER)\b", 1.0),
    ),
    "hvac": (
        (r"^H[-_]", 2.5),
        (r"\b(HVAC|DUCT|DIFFUSER|AIR|MEP|SPRINK|FIRE|SMOKE|EXHAUST|UNIT|AHU|FCU)\b", 2.5),
    ),
    "civil": (
        (r"^C[-_]", 2.5),
        (r"\b(CIVIL|ROAD|PAVE|LOT|PROP|SURVEY|TOPO|CONTOUR|ALIGN|PROF|CUT|FILL|EROS|UTIL|STORM|CURB|SIDEWALK)\b", 2.5),
        (r"\b(EXIST|NEW|DEMO)\b", 1.5),
        (r"\b(BENCH|MONU|CONTROL POINT)\b", 2.0),
    ),
    "process": (
        (r"\b(P&ID|PID|EQUIP|VESSEL|TANK|NOZZLE|TAG|LINE|FLOW|VALVE)\b", 2.5),
        (r"^(PP|PROC|E&I)\b", 2.0),
    ),
    "interiors": (
        (r"\b(I-|INT|FF&E|FURN|DK| millwork|SIGNAGE|SPEC|FINISH SCHEDULE)\b", 2.5),
        (r"^ID[-_]", 2.5),
    ),
    "survey": (
        (r"\b(SURVEY|BOUNDARY|METES|PARCEL|RIGHT-OF-WAY|TAX LOT|DEED)\b", 2.5),
    ),
}

#: linetype names that corroborate a discipline
LINETYPE_SIGNALS: tuple[tuple[str, str, float], ...] = (
    ("CENTER", "mechanical", 1.5),
    ("HIDDEN", "mechanical", 0.8),
    ("PHANTOM", "structural", 0.6),
    ("DASH", "architectural", 0.4),
    ("GAS_LEADER", "plumbing", 1.0),
    ("HVAC_LEADER", "hvac", 1.0),
)


@dataclass
class DisciplineProfile:
    """Result of :func:`infer_discipline` (serialised straight into the payload)."""

    primary: str = "unknown"
    confidence: float = 0.0
    mixed: bool = False
    method: str = "layer-name patterns weighted by entity counts + corroborating table signals"
    candidates: list[dict[str, Any]] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    standard_hint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "primary": self.primary,
            "confidence": self.confidence,
            "mixed": self.mixed,
            "method": self.method,
            "candidates": self.candidates,
            "signals": self.signals,
        }
        if self.standard_hint:
            payload["standard_hint"] = self.standard_hint
        return payload


#: National/international layer-naming standards to point the model at.
STANDARDS_BY_DISCIPLINE: dict[str, str] = {
    "architectural": "NIST/CAD layer naming (AIA), ISO 13567",
    "structural": "NIST structural layer naming, EN 10035 for reinforcement",
    "mechanical": "ASME Y14.5 (GD&T) / ISO 1101, ISO 13567",
    "electrical": "NFPA 72 / IEC 61082 symbology",
    "plumbing": "ASME A112 / ISO 10631",
    "hvac": "ASHRAE/SMACNA duct symbology, ISO 11091",
    "civil": "ASTM/ANSI CAD layer naming, state DOT standards",
    "process": "ISA 5.1 (P&ID symbology)",
    "interiors": "NIST interiors, ISO 13567",
    "survey": "ALTA/NSPS land title survey standards",
}


def _norm(text: Any) -> str:
    """Upper-case a name and collapse punctuation to a single separator.

    ``-`` is used (not a space) because the profile regexes encode the CAD
    discipline prefixes as ``^A-`` / ``^S-`` / ``^M-``, which is how real layer
    tables spell them (A-WALL, S-COLS, M-GEAR, E-PWR).
    """
    return re.sub(r"[^A-Z0-9&+]+", "-", str(text or "").upper()).strip("-")


def _as_int(value: Any) -> int:
    """Tolerant int() -- optional corroboration must never break classification."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def score_layers(layers: Sequence[Any]) -> dict[str, dict[str, float]]:
    """Score each discipline, weighted by the number of entities per layer.

    A layer named ``M-GEAR`` carrying 40,000 entities is evidence; an empty
    ``M-GEAR`` layer in a template is not.
    """
    scores: dict[str, dict[str, float]] = {}
    for layer in layers:
        name = _norm(getattr(layer, "name", None) or (layer.get("name") if isinstance(layer, Mapping) else ""))
        entities = _as_int(
        getattr(layer, "entities", 0) or (layer.get("entities", 0) if isinstance(layer, Mapping) else 0) or 0
    )
        if not name:
            continue
        weight = 1.0 + min(entities, 5000) / 5000.0  # 1x .. 2x, saturating
        for discipline, rules in PROFILES.items():
            for pattern, strength in rules:
                if strength <= 0:
                    continue
                try:
                    matched = re.search(pattern, name)
                except re.error:  # pragma: no cover - guards hand-edited tables
                    continue
                if matched:
                    bucket = scores.setdefault(discipline, {"score": 0.0})
                    bucket["score"] = float(bucket["score"]) + strength * weight
                    evidence = bucket.setdefault("layers", [])
                    if name not in evidence:
                        evidence.append(name)
                    break
    return scores


def _layer_names(layers: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for layer in layers:
        name = getattr(layer, "name", None) or (layer.get("name") if isinstance(layer, Mapping) else None)
        if name:
            out.append(str(name))
    return out


def infer_discipline(
    layers: Sequence[Any],
    entities: Mapping[str, Any] | None = None,
    *,
    linetypes: Sequence[Any] | None = None,
    warnings: Any = None,
) -> dict[str, Any]:
    """Classify the drawing's discipline.  Never raises.

    Args:
        layers: :class:`~cad2ai.structurer.LayerRecord` objects (or dicts).
        entities: the ``entities`` summary dict from Phase 2 (3D/hatch counts).
        linetypes: optional linetype records for corroboration.
    """
    try:
        scores = score_layers(layers)
        signals: list[str] = []

        # Corroborating table signals.
        if linetypes:
            names = _layer_names(linetypes)
            for name, discipline, weight in LINETYPE_SIGNALS:
                if any(name in _norm(entry) for entry in names):
                    scores.setdefault(discipline, {"score": 0.0, "layers": []})["score"] = (
                        float(scores[discipline].get("score", 0.0)) + weight
                    )
                    signals.append(f"linetype {name} present -> +{weight} {discipline}")

        summary = dict(entities or {})
        three_d = _as_int(summary.get("three_d"))
        total = _as_int(summary.get("total")) or 1
        if three_d and total and three_d / total > 0.02:
            scores.setdefault("mechanical", {"score": 0.0, "layers": []})["score"] = float(
                scores.get("mechanical", {}).get("score", 0.0)
            ) + 2.0
            signals.append(f"{three_d} 3D/model entities ({three_d / total:.1%} of total) -> +2.0 mechanical")
        hatches = _as_int((summary.get("by_type") or {}).get("HATCH"))
        if hatches:
            scores.setdefault("architectural", {"score": 0.0, "layers": []})["score"] = float(
                scores.get("architectural", {}).get("score", 0.0)
            ) + min(hatches / 100.0, 2.0)
            signals.append(f"{hatches} HATCH entities -> architectural/floor-plan filler")
        dimensions = _as_int(summary.get("dimensions"))
        if dimensions > 200:
            scores.setdefault("mechanical", {"score": 0.0, "layers": []})["score"] = float(
                scores.get("mechanical", {}).get("score", 0.0)
            ) + 1.0
            signals.append(f"{dimensions} dimensions -> dimension-dense sheet -> +1.0 mechanical")

        ranked = sorted(
            ((name, float(data.get("score", 0.0)), list(data.get("layers", [])[:5])) for name, data in scores.items()),
            key=lambda item: -item[1],
        )
        if not ranked or ranked[0][1] <= 0:
            return DisciplineProfile(
                primary="undetermined",
                confidence=0.0,
                signals=["no layer naming convention recognised; ask for the template/standard"],
            ).as_dict()

        total_score = sum(score for _, score, _ in ranked) or 1.0
        top_name, top_score, top_layers = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = round(top_score / total_score, 3)
        mixed = bool(runner / top_score >= 0.6) if top_score else False
        candidates = [
            {"discipline": name, "score": round(score, 2), "share": round(score / total_score, 3), "layers": layer_names}
            for name, score, layer_names in ranked[:6]
            if score > 0
        ]
        if top_layers:
            signals.insert(0, "layer evidence: " + ", ".join(top_layers[:5]))
        return DisciplineProfile(
            primary=top_name,
            confidence=confidence,
            mixed=mixed,
            candidates=candidates,
            signals=signals,
            standard_hint=STANDARDS_BY_DISCIPLINE.get(top_name),
        ).as_dict()
    except Exception as exc:  # noqa: BLE001 - classification must never break a run
        if warnings is not None:
            warnings.add(f"discipline inference failed: {type(exc).__name__}: {exc}")
        return DisciplineProfile(primary="undetermined", signals=[f"inference failed: {exc}"]).as_dict()
