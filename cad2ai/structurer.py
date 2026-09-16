"""Phase 2 -- turn an ezdxf document into a structured, AI-ready model.

What is extracted and why (each item maps to a question a model can then
answer about the drawing):

``layers``
    name, ACI colour, linetype, lineweight, on/frozen/locked/plot state and
    per-layer entity counts.  Layer naming conventions are the single strongest
    signal for a drawing's discipline and for separating geometry from
    annotation.
``entities``
    type histogram per layout plus totals -- the complexity profile (how many
    lines vs. hatches vs. proxies) and how much 3D content exists.
``blocks``
    block name, definition size, reference count and attribute tags.  Reusable
    components with attributes are what a BOM-style analysis is built from.
``text`` / ``dimensions``
    the actual content: TEXT/MTEXT/ATTRIB strings with layer + position, and
    dimension measurements with their style overrides (text height, decimal
    places, linear factor) -- the values a reviewer checks against a spec.
``document``
    units, measurement flag, header variables and extents.  Without units a
    "12.5" dimension is meaningless to the model.

Every read is defensive: third-party DWG files contain entities that raise from
inside ``ezdxf``, and one bad ``MTEXT`` must not lose the other 40,000
entities.  Failures are counted into ``warnings`` instead.
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any

from cad2ai import discipline as discipline_module
from cad2ai.dxfutils import (
    Warnings,
    dxf_attr,
    iter_layout_entities,
    iter_layout_names,
    point,
    round_float,
    safe,
    strip_mtext_markup,
    truncate_text,
)

logger = logging.getLogger("cad2ai.structurer")

__all__ = [
    "CadModel",
    "ExtractionLimits",
    "build_cad_model",
    "extract_blocks",
    "extract_dimension_styles",
    "extract_document_info",
    "extract_layers",
    "extract_linetypes",
    "extract_text_styles",
    "scan_layouts",
]

SCHEMA_VERSION = "1.0"

#: DIMENSION group 70 -- the low nibble encodes the geometry type.
DIMTYPE_NAMES: dict[int, str] = {
    0: "linear",
    1: "aligned",
    2: "angular_2line",
    3: "angular_3point",
    4: "diameter",
    5: "radius",
    6: "center",
    7: "ordinate",
}
#: DIMENSION group 70 -- the high bits are flags.
#: DIMENSION group 70 carries the type in the low nibble plus bit flags.  The
#: names below follow the DXF reference (see ezdxf.entities.dimension): 32 only
#: says the dimension owns its block, which is not informative, so it is not
#: reported; a *text override* is detected from group 1 instead.
DIMTYPE_FLAGS: tuple[tuple[int, str], ...] = (
    (64, "ordinate_x"),
    (128, "text_user_positioned"),
)

TEXT_ENTITY_TYPES = ("TEXT", "MTEXT", "ATTRIB", "ATTDEF")
DIMENSION_ENTITY_TYPES = ("DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION")
GEOMETRY_TYPES = frozenset(
    {
        "LINE",
        "LWPOLYLINE",
        "POLYLINE",
        "SPLINE",
        "ARC",
        "CIRCLE",
        "ELLIPSE",
        "SOLID",
        "TRACE",
        "FACE3D",
        "POLYFACE",
        "MESH",
        "REGION",
        "3DSOLID",
        "HATCH",
        "WIPEOUT",
        "IMAGE",
    }
)
ANNOTATION_TYPES = frozenset(
    {
        "DIMENSION",
        "ARC_DIMENSION",
        "LARGE_RADIAL_DIMENSION",
        "TEXT",
        "MTEXT",
        "MULTILEADER",
        "LEADER",
        "TOLERANCE",
        "IDENTIFIER",
        "WIPEOUT",
    }
)
REPRESENTATION_TYPES = frozenset({"INSERT", "MULTIBLOCK", "XREF"})
PROXY_TYPES = frozenset({"ACAD_PROXY_ENTITY", "DXFTagStorage"})
THREE_D_TYPES = frozenset({"3DSOLID", "REGION", "SURFACE", "MESH", "POLYFACE", "FACE3D", "ACIS"})

#: Header variables worth spending tokens on.
INTERESTING_HEADER_VARS: tuple[str, ...] = (
    "$ACADVER",
    "$INSUNITS",
    "$MEASUREMENT",
    "$LUNITS",
    "$LUPREC",
    "$AUPREC",
    "$LTSCALE",
    "$CELTSCALE",
    "$PSLTSCALE",
    "$MSLTSCALE",
    "$DIMASSOC",
    "$TEXTSIZE",
    "$CLAYER",
    "$TDUCREATE",
    "$TDCREATE",
)

#: $INSUNITS -> name, used when ezdxf's own mapping is unavailable.
INSUNITS_FALLBACK: dict[int, str] = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimeters",
    5: "centimeters",
    6: "meters",
    7: "kilometers",
    8: "microinches",
    9: "mil",
    10: "yards",
    11: "angstrom",
    12: "nanometer",
    13: "micron",
    14: "decimeter",
    15: "decameter",
    16: "hectometer",
    17: "gigameter",
    18: "astronomical_unit",
    19: "lightyear",
    20: "parsec",
}


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------


@dataclass
class LayerRecord:
    name: str
    color_aci: int | None = None
    color_hex: str | None = None
    linetype: str | None = None
    lineweight: int | None = None
    on: bool = True
    frozen: bool = False
    locked: bool = False
    plotted: bool = True
    entities: int = 0
    annotations: int = 0
    text: int = 0
    dimensions: int = 0
    xrefs: int = 0
    proxy: int = 0


@dataclass
class BlockRecord:
    name: str
    entities: int = 0
    references: int = 0
    base_point: list[float] | None = None
    anonymous: bool = False
    external: bool = False
    attribute_tags: list[str] = field(default_factory=list)
    entity_types: dict[str, int] = field(default_factory=dict)
    #: entities * references -- "leverage" heuristic for reusable content
    leverage: int = 0


@dataclass
class TextRecord:
    layer: str | None
    kind: str
    text: str
    #: ATTRIB/ATTDEF tag name (e.g. "FIRE_RATING"); None for TEXT/MTEXT
    tag: str | None = None
    at: list[float] | None = None
    height: float | None = None
    rotation: float | None = None
    handle: str | None = None


@dataclass
class DimensionRecord:
    layer: str | None
    kind: str
    value: float | None = None
    unit: str | None = None
    text: str | None = None
    dimstyle: str | None = None
    flags: list[str] = field(default_factory=list)
    handle: str | None = None


@dataclass
class CadModel:
    """Complete Phase 2 output; :meth:`as_dict` feeds :mod:`cad2ai.payload`."""

    schema_version: str = SCHEMA_VERSION
    generated_at: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    document: dict[str, Any] = field(default_factory=dict)
    layers: list[LayerRecord] = field(default_factory=list)
    linetypes: list[dict[str, Any]] = field(default_factory=list)
    text_styles: list[dict[str, Any]] = field(default_factory=list)
    dimension_styles: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[BlockRecord] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    layouts: list[dict[str, Any]] = field(default_factory=list)
    text: list[TextRecord] = field(default_factory=list)
    text_stats: dict[str, Any] = field(default_factory=dict)
    dimensions: list[DimensionRecord] = field(default_factory=list)
    dimension_stats: dict[str, Any] = field(default_factory=dict)
    layer_stats: dict[str, Any] = field(default_factory=dict)
    block_stats: dict[str, Any] = field(default_factory=dict)
    proxies: dict[str, Any] = field(default_factory=dict)
    discipline: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extraction: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-serialisable ``dict`` (dataclasses flattened)."""
        return {
            "schema": self.schema_version,
            "generated_at": self.generated_at,
            "source": self.source,
            "document": self.document,
            "layers": [_compact(layer) for layer in self.layers],
            "linetypes": self.linetypes,
            "text_styles": self.text_styles,
            "dimension_styles": self.dimension_styles,
            "blocks": [_compact(block) for block in self.blocks],
            "entities": self.entities,
            "layouts": self.layouts,
            "text": [_compact(item) for item in self.text],
            "text_stats": self.text_stats,
            "dimensions": [_compact(item) for item in self.dimensions],
            "dimension_stats": self.dimension_stats,
            "layer_stats": self.layer_stats,
            "block_stats": self.block_stats,
            "proxies": self.proxies,
            "discipline": self.discipline,
            "warnings": self.warnings,
            "extraction": self.extraction,
        }

    def summary(self) -> dict[str, Any]:
        """Small overview for CLI output/logs (never contains geometry)."""
        return {
            "source": self.source.get("file") or self.source.get("name"),
            "backend": self.source.get("backend"),
            "units": (self.document.get("units") or {}).get("name"),
            "layers": len(self.layers),
            "blocks": len(self.blocks),
            "entities": (self.entities or {}).get("total"),
            "text_items": (self.text_stats or {}).get("included"),
            "dimensions": (self.dimension_stats or {}).get("included"),
            "discipline": (self.discipline or {}).get("primary"),
            "warnings": len(self.warnings),
        }


def _compact(record: Any) -> dict[str, Any]:
    """Drop empty fields -- pure token economy.

    ``0`` counts are kept (they are the information in a histogram), so only
    ``None``/empty containers are removed.  Plain mappings are accepted so that
    partial models (e.g. the APS fallback) can reuse the same dataclass lists.
    """
    data = dict(record) if isinstance(record, Mapping) else asdict(record)
    return {key: value for key, value in data.items() if value is not None and value != [] and value != {}}


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionLimits:
    """Caps applied during extraction (before token budgeting).

    These bound memory for pathological drawings; :mod:`cad2ai.payload` then
    decides what actually reaches the model.
    """

    max_text_items: int = 800
    max_dimensions: int = 400
    max_blocks: int = 120
    max_layers: int = 200
    max_block_entity_types: int = 6
    text_sample_chars: int = 160
    float_precision: int = 3
    include_handles: bool = False
    scan_block_internals: bool = True

    @classmethod
    def from_settings(cls, settings: Any | None) -> "ExtractionLimits":
        if settings is None:
            return cls()
        return cls(
            max_text_items=settings.max_text_items,
            max_dimensions=settings.max_dimensions,
            max_blocks=settings.max_blocks,
            max_layers=settings.max_layers,
            float_precision=settings.float_precision,
            include_handles=settings.include_handles,
        )


# ---------------------------------------------------------------------------
# layout scan -- one traversal, many counters
# ---------------------------------------------------------------------------


@dataclass
class LayoutScan:
    """Accumulated statistics from a single pass over all layout entities."""

    types: Counter[str] = field(default_factory=Counter)
    per_layout: dict[str, Counter[str]] = field(default_factory=dict)
    layers: Counter[str] = field(default_factory=Counter)
    layer_annotations: Counter[str] = field(default_factory=Counter)
    layer_text: Counter[str] = field(default_factory=Counter)
    layer_dims: Counter[str] = field(default_factory=Counter)
    layer_xref: Counter[str] = field(default_factory=Counter)
    layer_proxy: Counter[str] = field(default_factory=Counter)
    block_usage: Counter[str] = field(default_factory=Counter)
    block_scales: dict[str, set[float]] = field(default_factory=dict)
    xrefs: Counter[str] = field(default_factory=Counter)
    proxy_types: Counter[str] = field(default_factory=Counter)
    texts: list[TextRecord] = field(default_factory=list)
    dimensions: list[DimensionRecord] = field(default_factory=list)
    extents_min: list[float] | None = None
    extents_max: list[float] | None = None
    attribs: int = 0
    text_truncated: bool = False
    dim_truncated: bool = False
    geometry: int = 0
    annotation: int = 0
    representation: int = 0
    entity_count: int = 0

    @property
    def insert_total(self) -> int:
        return sum(self.block_usage.values())


def _min_point(current: list[float] | None, candidate: list[float]) -> list[float]:
    return list(candidate) if current is None else [min(a, b) for a, b in zip(current, candidate)]


def _max_point(current: list[float] | None, candidate: list[float]) -> list[float]:
    return list(candidate) if current is None else [max(a, b) for a, b in zip(current, candidate)]


def _accumulate_point(scan: LayoutScan, entity: Any, precision: int) -> None:
    """Best-effort extents accumulation (no geometry evaluation, cheap)."""
    for attribute in ("insert", "start_point", "location", "center", "text_midpoint"):
        coords = point(dxf_attr(entity, attribute), precision)
        if coords is None or len(coords) < 2:
            continue
        scan.extents_min = _min_point(scan.extents_min, coords)
        scan.extents_max = _max_point(scan.extents_max, coords)
        return


def scan_layouts(doc: Any, *, limits: ExtractionLimits, warnings: Warnings) -> LayoutScan:
    """Single traversal of every layout, collecting all layout-level statistics."""
    scan = LayoutScan()
    for layout_name, entity in iter_layout_entities(doc):
        scan.entity_count += 1
        kind = str(safe(lambda e=entity: e.dxftype(), "UNKNOWN", context="dxftype", warnings=warnings))
        scan.per_layout.setdefault(layout_name, Counter())[kind] += 1
        scan.types[kind] += 1

        layer = str(dxf_attr(entity, "layer") or "0")
        scan.layers[layer] += 1
        if kind in ANNOTATION_TYPES:
            scan.layer_annotations[layer] += 1
            scan.annotation += 1
        if kind in GEOMETRY_TYPES:
            scan.geometry += 1
        if kind in REPRESENTATION_TYPES:
            scan.representation += 1
        if kind in PROXY_TYPES or "PROXY" in kind:
            scan.proxy_types[kind] += 1
            scan.layer_proxy[layer] += 1

        if kind in REPRESENTATION_TYPES:
            name = str(dxf_attr(entity, "name") or "?")
            scan.block_usage[name] += 1
            if name.startswith("|"):  # AutoCAD names external references |DWGPNAME
                scan.xrefs[name] += 1
                scan.layer_xref[layer] += 1
            scale = dxf_attr(entity, "xscale", 1.0)
            try:
                scan.block_scales.setdefault(name, set()).add(round(float(scale), 3))
            except (TypeError, ValueError):
                pass
            # ATTRIB values live on the block reference, never in the layout, yet
            # they are where schedules actually store data (door type, panel ID,
            # column load).  Collect them as text so Phase 3 can build takeoffs.
            for attrib in safe(lambda e=entity: list(e.attribs), [], context="INSERT.attribs", warnings=warnings) or []:
                scan.attribs += 1
                attrib_layer = str(dxf_attr(attrib, "layer") or layer)
                scan.layer_text[attrib_layer] += 1
                if len(scan.texts) < limits.max_text_items:
                    record = _text_record(attrib, kind="ATTRIB", limits=limits)
                    if record is not None:
                        scan.texts.append(record)
                else:
                    scan.text_truncated = True

        if kind in TEXT_ENTITY_TYPES:
            scan.layer_text[layer] += 1
            if len(scan.texts) < limits.max_text_items:
                record = _text_record(entity, kind=kind, limits=limits)
                if record is not None:
                    scan.texts.append(record)
            else:
                scan.text_truncated = True

        if kind in DIMENSION_ENTITY_TYPES:
            scan.layer_dims[layer] += 1
            if len(scan.dimensions) < limits.max_dimensions:
                record = _dimension_record(entity, kind=kind, limits=limits)
                if record is not None:
                    scan.dimensions.append(record)
            else:
                scan.dim_truncated = True

        _accumulate_point(scan, entity, limits.float_precision)
    return scan


def _text_record(entity: Any, *, kind: str, limits: ExtractionLimits) -> TextRecord | None:
    precision = limits.float_precision
    raw = dxf_attr(entity, "text", "")
    if kind == "MTEXT":
        text = safe(lambda: entity.plain_text(newlines=False), "", context="MTEXT.plain_text") or raw
    else:
        text = raw
    text = truncate_text(strip_mtext_markup(text), limits.text_sample_chars)
    if not text:
        return None
    tag = None
    if kind in ("ATTRIB", "ATTDEF"):
        tag = truncate_text(dxf_attr(entity, "tag", ""), 40)
    return TextRecord(
        layer=dxf_attr(entity, "layer"),
        kind={"TEXT": "text", "MTEXT": "mtext", "ATTRIB": "attrib", "ATTDEF": "attdef"}.get(kind, kind.lower()),
        text=text,
        tag=tag,
        at=point(dxf_attr(entity, "insert"), precision) or point(dxf_attr(entity, "location"), precision),
        height=round_float(dxf_attr(entity, "height") or dxf_attr(entity, "char_height"), precision),
        rotation=round_float(dxf_attr(entity, "rotation"), 1),
        handle=dxf_attr(entity, "handle") if limits.include_handles else None,
    )


def _dimension_record(entity: Any, *, kind: str, limits: ExtractionLimits) -> DimensionRecord | None:
    raw_type = dxf_attr(entity, "dimtype", 0)
    try:
        bits = int(raw_type or 0)
    except (TypeError, ValueError):
        bits = 0
    flags = [name for bit, name in DIMTYPE_FLAGS if bits & bit]
    if kind == "ARC_DIMENSION":
        name = "arc_length"
    elif kind == "LARGE_RADIAL_DIMENSION":
        name = "large_radius"
    else:
        name = DIMTYPE_NAMES.get(bits & 0x0F, "linear")

    measured = safe(lambda: entity.get_measurement(), None, context=f"{kind}.get_measurement")
    if measured is None:
        measured = dxf_attr(entity, "actual_measurement")
    if isinstance(measured, (int, float)) and not math.isfinite(measured):
        measured = None
    value = round_float(measured, max(limits.float_precision, 3))

    # "<>" is the "use the measurement" placeholder, not a text override.
    raw_text = str(dxf_attr(entity, "text", "") or "").strip()
    text = None if raw_text in ("", "<>") else truncate_text(raw_text, 60)
    if text is not None:
        flags = [*flags, "text_override"]
    if value is None:
        flags = [*flags, "unmeasured"]

    return DimensionRecord(
        layer=dxf_attr(entity, "layer"),
        kind=name,
        value=value if isinstance(value, (int, float)) else None,
        text=text,
        dimstyle=dxf_attr(entity, "dimstyle"),
        flags=flags,
        handle=dxf_attr(entity, "handle") if limits.include_handles else None,
    )


# ---------------------------------------------------------------------------
# table extractions
# ---------------------------------------------------------------------------


def extract_layers(
    doc: Any,
    scan: LayoutScan,
    *,
    limits: ExtractionLimits,
    warnings: Warnings,
) -> list[LayerRecord]:
    """Layer table: names, colours, linetypes, states and usage counters."""
    table = getattr(doc, "layers", None)
    if table is None:
        warnings.add("document exposes no layer table")
        return []
    records: list[LayerRecord] = []
    for layer in table:
        name = str(dxf_attr(layer, "name", "?"))
        aci = dxf_attr(layer, "color", 7)
        try:
            aci_int: int | None = int(aci)
        except (TypeError, ValueError):
            aci_int = None
        # A negative ACI encodes "layer off", not a colour: report the colour
        # index and the state separately so the model never sees "-3 = red".
        true_color = dxf_attr(layer, "true_color")
        color_hex = f"#{true_color:06X}" if isinstance(true_color, int) and 0 <= true_color <= 0xFFFFFF else None
        lineweight = dxf_attr(layer, "lineweight")
        plotted = dxf_attr(layer, "plot", 1)
        records.append(
            LayerRecord(
                name=name,
                color_aci=abs(aci_int) if aci_int is not None else None,
                color_hex=color_hex,
                linetype=str(dxf_attr(layer, "linetype", "Continuous") or "Continuous"),
                lineweight=_as_lineweight(lineweight),
                on=bool(safe(lambda: layer.is_on(), True, context="layer.is_on")),
                frozen=bool(safe(lambda: layer.is_frozen(), False, context="layer.is_frozen")),
                locked=bool(safe(lambda: layer.is_locked(), False, context="layer.is_locked")),
                plotted=bool(plotted) if plotted is not None else True,
                entities=int(scan.layers.get(name, 0)),
                annotations=int(scan.layer_annotations.get(name, 0)),
                text=int(scan.layer_text.get(name, 0)),
                dimensions=int(scan.layer_dims.get(name, 0)),
                xrefs=int(scan.layer_xref.get(name, 0)),
                proxy=int(scan.layer_proxy.get(name, 0)),
            )
        )
    records.sort(key=lambda item: (-item.entities, item.name))
    return records


def _as_lineweight(value: Any) -> int | None:
    """Lineweight in 1/100 mm; BYLAYER/BYBLOCK/DEFAULT sentinels become None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        weight = int(value)
    except (TypeError, ValueError):
        return None
    return weight if weight >= 0 else None


def extract_linetypes(doc: Any, *, limits: ExtractionLimits, warnings: Warnings) -> list[dict[str, Any]]:
    """Linetype table -- dash patterns encode conventions (CENTER, HIDDEN, ...)."""
    table = getattr(doc, "linetypes", None)
    if table is None:
        return []
    out: list[dict[str, Any]] = []
    for line_type in table:
        pattern = safe(
            lambda t=line_type: list(t.simplified_line_pattern() if callable(t.simplified_line_pattern) else t.simplified_line_pattern),
            None,
            context="linetype pattern",
        )
        out.append(
            {
                "name": str(dxf_attr(line_type, "name", "?")),
                "description": truncate_text(dxf_attr(line_type, "description", ""), 60),
                "segments": len([value for value in pattern if value]) if isinstance(pattern, list) else None,
            }
        )
    out.sort(key=lambda item: item["name"])
    return out


def extract_text_styles(doc: Any, *, limits: ExtractionLimits, warnings: Warnings) -> list[dict[str, Any]]:
    """Text style table: fonts and fixed heights reflect the plot template."""
    table = getattr(doc, "styles", None)
    if table is None:
        return []
    out: list[dict[str, Any]] = []
    for style in table:
        out.append(
            {
                "name": str(dxf_attr(style, "name", "?")),
                "font": truncate_text(dxf_attr(style, "font", ""), 40),
                "big_font": truncate_text(dxf_attr(style, "bigfont", ""), 40),
                "fixed_height": round_float(dxf_attr(style, "height", 0), limits.float_precision) or None,
                "width_factor": round_float(dxf_attr(style, "width", 1.0), 2),
            }
        )
    out.sort(key=lambda item: item["name"])
    return out


#: payload label -> DXF dimension-style attribute (group codes in comments)
DIMENSION_STYLE_ATTRIBUTES: dict[str, str] = {
    "text_height": "dimtxt",  # 40
    "decimal_places": "dimdec",  # 72
    "linear_factor": "dimlfac",  # 41
    "rounding": "dimrnd",  # 28
    "text_gap": "dimgap",  # 41 of AcdbDimensionClass
    "text_above_line": "dimtad",  # 71
    "zero_suppression": "dimzin",  # 78
    "angle_precision": "dimaunit",  # 270/75
    "scale": "dimscale",  # 40
    "text_style": "dimtxsty",  # 5
    "dimension_line_color": "dimclrd",  # 6
}


def extract_dimension_styles(doc: Any, *, limits: ExtractionLimits, warnings: Warnings) -> list[dict[str, Any]]:
    """Dimension style table -- the precision/tolerance contract for measurements."""
    table = getattr(doc, "dimstyles", None)
    if table is None:
        return []
    out: list[dict[str, Any]] = []
    for entry in table:
        style: dict[str, Any] = {"name": str(dxf_attr(entry, "name", "?"))}
        for label, attribute in DIMENSION_STYLE_ATTRIBUTES.items():
            value = dxf_attr(entry, attribute)
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                style[label] = value
            elif isinstance(value, (int, float)):
                style[label] = round_float(value, max(limits.float_precision, 3))
            else:
                style[label] = truncate_text(value, 40)
        out.append(style)
    out.sort(key=lambda item: item["name"])
    return out


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------


def extract_blocks(
    doc: Any,
    scan: LayoutScan,
    *,
    limits: ExtractionLimits,
    warnings: Warnings,
) -> tuple[list[BlockRecord], dict[str, Any]]:
    """Block definitions + INSERT usage -> reusable-component profile."""
    table = getattr(doc, "blocks", None)
    if table is None:
        return [], {}
    layout_holders = ("*Model_Space",)
    records: list[BlockRecord] = []
    for block in table:
        name = str(getattr(block, "name", "?"))
        entity_count = int(safe(lambda b=block: len(b), 0, context=f"len(block {name})") or 0)
        references = int(scan.block_usage.get(name, 0))
        is_paperspace_holder = name.startswith("*Paper_Space")
        if name in layout_holders or is_paperspace_holder:
            continue  # layout containers are not reusable content
        if entity_count == 0 and references == 0:
            continue
        record_entry = getattr(block, "block_record", None)
        external = bool(getattr(record_entry, "is_xref", False))
        types: Counter[str] = Counter()
        tags: list[str] = []
        if limits.scan_block_internals and entity_count:
            for entity in safe(lambda b=block: list(b), [], context=f"iter block {name}", warnings=warnings) or []:
                kind = str(safe(lambda e=entity: e.dxftype(), "?", context="block entity type"))
                types[kind] += 1
                if kind in ("ATTDEF", "ATTRIB"):
                    tag = truncate_text(dxf_attr(entity, "tag", ""), 40)
                    if tag and tag not in tags:
                        tags.append(tag)
        records.append(
            BlockRecord(
                name=name,
                entities=entity_count,
                references=references,
                base_point=point(
                    safe(lambda b=block: b.base_point, None, context="block base_point"), limits.float_precision
                ),
                anonymous=name.startswith("*"),
                external=external,
                attribute_tags=sorted(tags)[:20],
                entity_types=dict(types.most_common(limits.max_block_entity_types)),
                leverage=entity_count * references,
            )
        )
    records.sort(key=lambda item: (-item.references, -item.entities, item.name))
    used = [item for item in records if item.references > 0]
    stats = {
        "definitions": len(records),
        "used": len(used),
        "unused": len(records) - len(used),
        "repeated": sum(1 for item in used if item.references > 1),
        "anonymous": sum(1 for item in records if item.anonymous),
        "external": sum(1 for item in records if item.external),
        "with_attributes": sum(1 for item in records if item.attribute_tags),
        "insert_entities": scan.insert_total,
        "distinct_insert_names": len(scan.block_usage),
        "missing_definitions": sorted(
            name for name in scan.block_usage if name not in {item.name for item in records} and not name.startswith("*")
        )[:20],
        "reusable": [
            {"name": item.name, "references": item.references, "entities": item.entities}
            for item in sorted(used, key=lambda b: -b.leverage)[:12]
            if item.references > 1
        ],
    }
    return records, stats


# ---------------------------------------------------------------------------
# document metadata
# ---------------------------------------------------------------------------


def extract_document_info(doc: Any, parsed: Any | None, scan: LayoutScan, warnings: Warnings) -> dict[str, Any]:
    """Header/units/extents plus table sizes."""
    info: dict[str, Any] = {}
    header = getattr(doc, "header", None)

    variables: dict[str, Any] = {}
    if header is not None:
        for name in INTERESTING_HEADER_VARS:
            value = safe(lambda n=name: header.get(n), None, context=f"header {name}", warnings=warnings)
            if value is None:
                continue
            if isinstance(value, float):
                rounded = round(value, 4)
                if math.isfinite(rounded):
                    variables[name] = rounded
            elif isinstance(value, int):
                variables[name] = value
            elif isinstance(value, str):
                text = truncate_text(value, 40)
                if text:
                    variables[name] = text
            else:  # Vec3-ish or ezdxf wrappers: keep a compact string form
                rendered = truncate_text(value, 40)
                if rendered:
                    variables[name] = rendered
    if variables:
        info["header"] = variables

    units_code = safe(lambda: int(doc.units), None, context="doc.units")  # type: ignore[arg-type]
    units_name: str | None = None
    if units_code is not None:
        try:
            from ezdxf.units import unit_name  # type: ignore

            units_name = unit_name(units_code)
        except Exception:  # pragma: no cover - ezdxf API drift
            units_name = None
    metric_flag = safe(
        lambda: int(header.get("$MEASUREMENT")) if header is not None else None,
        None,
        context="header $MEASUREMENT",
    )
    info["units"] = {
        "insunits": units_code,
        "name": units_name or INSUNITS_FALLBACK.get(int(units_code or 0), "unknown"),
        "metric": bool(metric_flag == 1) if metric_flag is not None else None,
    }

    extents = _extract_extents(doc, scan)
    if extents:
        info["extents"] = extents

    info["dxf_version"] = getattr(doc, "dxfversion", None)
    info["acad_release"] = getattr(doc, "acad_release", None)
    dwg = getattr(parsed, "dwg", None)
    if dwg is not None:
        info["dwg"] = dwg.as_dict()
    info["tables"] = {
        "layers": _table_len(doc, "layers"),
        "linetypes": _table_len(doc, "linetypes"),
        "text_styles": _table_len(doc, "styles"),
        "dimension_styles": _table_len(doc, "dimstyles"),
        "blocks": _table_len(doc, "blocks"),
        "views": _table_len(doc, "views"),
        "ucs": _table_len(doc, "ucs"),
        "viewports": _table_len(doc, "vports"),
        "applications": _table_len(doc, "appids"),
    }
    return info


def _table_len(doc: Any, attribute: str) -> int | None:
    table = getattr(doc, attribute, None)
    if table is None:
        return None
    try:
        return len(table)
    except TypeError:
        try:
            return sum(1 for _ in table)
        except Exception:  # pragma: no cover - defensive
            return None


def _extract_extents(doc: Any, scan: LayoutScan) -> dict[str, Any] | None:
    """Extents from the header when present, otherwise from scanned anchors."""
    header = getattr(doc, "header", None)
    minimum = maximum = None
    source = "entity_scan"

    def _usable(value: list[float] | None) -> bool:
        # AutoCAD stores 1e20/-1e20 while the extents are unset (never saved/regen'd)
        return bool(value) and all(abs(float(v)) < 1e100 for v in value)

    if header is not None:
        minimum = safe(lambda: point(header.get("$EXTMIN"), 3), None, context="header $EXTMIN")
        maximum = safe(lambda: point(header.get("$EXTMAX"), 3), None, context="header $EXTMAX")
        if _usable(minimum) and _usable(maximum) and all(b >= a for a, b in zip(minimum, maximum)):
            source = "header"
        else:
            minimum = maximum = None
    if minimum is None or maximum is None:
        minimum, maximum = scan.extents_min, scan.extents_max
    if minimum is None or maximum is None:
        return None
    size = [round(b - a, 3) for a, b in zip(minimum, maximum)]
    if any(value < 0 for value in size):
        return None
    return {
        "min": minimum,
        "max": maximum,
        "size": size,
        "area": round(size[0] * size[1], 2) if len(size) >= 2 else None,
        "source": source,
    }


# ---------------------------------------------------------------------------
# derived statistics
# ---------------------------------------------------------------------------


def _entity_summary(scan: LayoutScan, limits: ExtractionLimits) -> dict[str, Any]:
    types = dict(scan.types.most_common(60))
    return {
        "total": scan.entity_count,
        "by_type": types,
        "distinct_types": len(scan.types),
        "geometry": scan.geometry,
        "annotations": scan.annotation,
        "representations": scan.representation,
        "text_entities": sum(scan.types.get(kind, 0) for kind in TEXT_ENTITY_TYPES) + scan.attribs,
        "dimensions": sum(scan.types.get(kind, 0) for kind in DIMENSION_ENTITY_TYPES),
        "inserts": scan.insert_total,
        "attribs": scan.attribs,
        "three_d": sum(count for kind, count in scan.types.items() if kind in THREE_D_TYPES),
        "layout_breakdown": {name: dict(counter.most_common(20)) for name, counter in scan.per_layout.items()},
    }


def _layout_summaries(doc: Any, scan: LayoutScan) -> list[dict[str, Any]]:
    # Every layout is reported, not only the non-empty ones: the sheet count of a
    # drawing set is itself information (an empty paper-space layout is a finding).
    names = list(dict.fromkeys([*iter_layout_names(doc), *scan.per_layout]))
    out: list[dict[str, Any]] = []
    for name in names:
        counter = scan.per_layout.get(name, Counter())
        entry: dict[str, Any] = {
            "name": name,
            "entities": int(sum(counter.values())),
            "is_modelspace": name in ("Model", "*Model_Space"),
            "top_types": dict(counter.most_common(8)),
        }
        layout = safe(lambda n=name: doc.layout(n), None, context=f"doc.layout({name})")
        if layout is not None:
            base = dxf_attr(layout, "base_point")
            if base is not None:
                entry["base_point"] = point(base, 3)
            for attribute, label in (
                ("vp_height", "paper_height"),
                ("view_scale", "view_scale"),
                ("standard_scale", "standard_scale"),
                ("tab_order", "tab_order"),
            ):
                value = dxf_attr(layout, attribute)
                if value in (None, 0):
                    continue
                entry[label] = round_float(value, 3) if isinstance(value, (int, float)) else value
        out.append(entry)
    out.sort(key=lambda item: (not item["is_modelspace"], -item["entities"], str(item["name"])))
    return out


def _layer_stats(layers: list[LayerRecord], scan: LayoutScan) -> dict[str, Any]:
    total_entities = sum(layer.entities for layer in layers) or 1
    known = {layer.name for layer in layers}
    return {
        "count": len(layers),
        "off": sum(1 for layer in layers if not layer.on),
        "frozen": sum(1 for layer in layers if layer.frozen),
        "locked": sum(1 for layer in layers if layer.locked),
        "not_plotted": sum(1 for layer in layers if not layer.plotted),
        "empty": sum(1 for layer in layers if layer.entities == 0),
        "used": sum(1 for layer in layers if layer.entities > 0),
        "with_dimensions": sum(1 for layer in layers if layer.dimensions),
        "annotation_ratio": round(sum(layer.annotations for layer in layers) / total_entities, 3),
        "referenced_but_undefined": sorted(name for name in scan.layers if name not in known)[:20],
        "top_by_entities": [
            {"name": layer.name, "entities": layer.entities}
            for layer in sorted(layers, key=lambda item: -item.entities)[:10]
            if layer.entities
        ],
    }


def _text_stats(scan: LayoutScan, limits: ExtractionLimits) -> dict[str, Any]:
    lengths = [len(item.text) for item in scan.texts]
    return {
        "total": sum(scan.types.get(kind, 0) for kind in TEXT_ENTITY_TYPES) + scan.attribs,
        "attribs": scan.attribs,
        "included": len(scan.texts),
        "cap": limits.max_text_items,
        "truncated": scan.text_truncated,
        "by_kind": dict(Counter(item.kind for item in scan.texts)),
        "characters": sum(lengths),
        "longest": max(lengths) if lengths else 0,
        "layers": dict(Counter(item.layer or "0" for item in scan.texts).most_common(10)),
    }


def _dimension_stats(scan: LayoutScan, limits: ExtractionLimits) -> dict[str, Any]:
    values = [item.value for item in scan.dimensions if isinstance(item.value, (int, float))]
    unit = next((item.unit for item in scan.dimensions if item.unit), None)
    stats: dict[str, Any] = {
        "total": sum(scan.types.get(kind, 0) for kind in DIMENSION_ENTITY_TYPES),
        "included": len(scan.dimensions),
        "cap": limits.max_dimensions,
        "truncated": scan.dim_truncated,
        "by_kind": dict(Counter(item.kind for item in scan.dimensions)),
        "with_text_override": sum(1 for item in scan.dimensions if item.text),
        "user_positioned_text": sum(1 for item in scan.dimensions if "text_user_positioned" in item.flags),
        "unmeasured": sum(1 for item in scan.dimensions if item.value is None),
        "styles": dict(Counter(item.dimstyle or "Standard" for item in scan.dimensions).most_common(10)),
        "unit": unit,
    }
    if values:
        stats["measured"] = {
            "count": len(values),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "median": round(statistics.median(values), 3),
            "unit": unit,
        }
    return stats


def _proxy_stats(scan: LayoutScan) -> dict[str, Any]:
    total = sum(scan.proxy_types.values())
    stats: dict[str, Any] = {"count": int(total), "by_type": dict(scan.proxy_types.most_common(10))}
    if total:
        stats["note"] = (
            "proxy objects carry vertical-application data (Civil 3D, Plant 3D, Mechanical); "
            "ezdxf preserves them, but their geometry is opaque to this extraction"
        )
    return stats


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_cad_model(parsed: Any, *, settings: Any | None = None) -> CadModel:
    """Build a :class:`CadModel` from a :class:`~cad2ai.parser.ParsedDrawing`.

    ``parsed`` may also be a bare ``ezdxf`` document (handy in tests and when
    the caller already holds one).
    """
    doc = getattr(parsed, "doc", parsed)
    limits = ExtractionLimits.from_settings(settings)
    warnings = Warnings()

    started = time.perf_counter()
    scan = scan_layouts(doc, limits=limits, warnings=warnings)
    scan_seconds = time.perf_counter() - started

    started = time.perf_counter()
    linetypes = extract_linetypes(doc, limits=limits, warnings=warnings)
    known_linetypes = {str(item.get("name")) for item in linetypes}
    layers = extract_layers(doc, scan, limits=limits, warnings=warnings)
    undefined_linetypes = sorted(
        {layer.linetype for layer in layers if layer.linetype and layer.linetype not in known_linetypes}
    )
    if undefined_linetypes:
        # A real defect class: the layer asks for a linetype the table does not
        # define, so dashed/centre lines silently print as continuous.
        warnings.add(
            f"{len(undefined_linetypes)} layer linetype(s) are not defined in the LTYPE table: "
            f"{', '.join(undefined_linetypes[:8])}"
        )
    blocks, block_stats = extract_blocks(doc, scan, limits=limits, warnings=warnings)
    document = extract_document_info(doc, parsed, scan, warnings)
    table_seconds = time.perf_counter() - started

    unit_name = (document.get("units") or {}).get("name")
    for dimension in scan.dimensions:
        dimension.unit = unit_name

    parse_warnings = list(getattr(parsed, "warnings", None) or [])
    model = CadModel(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=_source_info(parsed),
        document=document,
        layers=layers[: limits.max_layers],
        linetypes=linetypes,
        text_styles=extract_text_styles(doc, limits=limits, warnings=warnings),
        dimension_styles=extract_dimension_styles(doc, limits=limits, warnings=warnings),
        blocks=blocks[: limits.max_blocks],
        entities=_entity_summary(scan, limits),
        layouts=_layout_summaries(doc, scan),
        text=scan.texts,
        text_stats=_text_stats(scan, limits),
        dimensions=scan.dimensions,
        dimension_stats=_dimension_stats(scan, limits),
        layer_stats={
            **_layer_stats(layers, scan),
            **({"linetypes_undefined": undefined_linetypes} if undefined_linetypes else {}),
        },
        block_stats=block_stats,
        proxies=_proxy_stats(scan),
        warnings=[*parse_warnings, *warnings.as_list()],
        extraction={
            "layout_scan_seconds": round(scan_seconds, 3),
            "table_extract_seconds": round(table_seconds, 3),
            "entities_seen": scan.entity_count,
            "limits": {
                "max_text_items": limits.max_text_items,
                "max_dimensions": limits.max_dimensions,
                "max_blocks": limits.max_blocks,
                "max_layers": limits.max_layers,
            },
        },
    )
    model.discipline = discipline_module.infer_discipline(model.layers, model.entities, warnings=warnings)
    return model


def _source_info(parsed: Any) -> dict[str, Any]:
    source = getattr(parsed, "source", None)
    if source is None:  # a bare ezdxf document
        return {
            "name": getattr(parsed, "filename", None) or "in-memory-document",
            "backend": "ezdxf.document",
            "lossless": True,
            "provenance": "local",
        }
    backend = getattr(parsed, "backend", None)
    return {
        "name": str(source),
        "file": str(getattr(source, "name", source)),
        "size_bytes": getattr(parsed, "size_bytes", None),
        "sha256": getattr(parsed, "sha256", None),
        "backend": getattr(backend, "value", str(backend)) if backend is not None else None,
        "lossless": bool(getattr(backend, "lossless", True)),
        "provenance": getattr(parsed, "provenance", "local"),
    }
