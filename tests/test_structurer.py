"""Phase 2: DWG object model -> CadModel."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from cad2ai.config import Settings
from cad2ai.dxfutils import Warnings
from cad2ai.parser import load_drawing
from cad2ai.structurer import (
    ExtractionLimits,
    build_cad_model,
    extract_blocks,
    scan_layouts,
)


@pytest.fixture
def model(arch_doc):
    return build_cad_model(arch_doc)


# ---------------------------------------------------------------------------
# document level
# ---------------------------------------------------------------------------


def test_document_metadata(model):
    assert model.document["units"] == {"insunits": 4, "name": "Millimeters", "metric": True}
    assert model.document["dxf_version"] == "AC1032"
    assert model.document["acad_release"] == "R2018"
    assert model.document["header"]["$INSUNITS"] == 4
    assert model.document["header"]["$LTSCALE"] == 1.0
    assert model.document["tables"]["layers"] == 10
    assert model.source == {
        "name": "in-memory-document",
        "backend": "ezdxf.document",
        "lossless": True,
        "provenance": "local",
    }
    # generated_at is a real timestamp
    assert datetime.fromisoformat(model.generated_at).tzinfo is not None


def test_unknown_units_are_reported_not_guessed():
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 0  # unspecific
    model = build_cad_model(doc)
    assert model.document["units"]["insunits"] == 0


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------


def test_layers_carry_naming_colour_and_linetype(model):
    by_name = {layer.name: layer for layer in model.layers}
    assert {"A-WALL", "A-DOOR", "S-COLS", "E-PWR", "P-EQ", "A-DEAD"} <= set(by_name)
    wall = by_name["A-WALL"]
    assert (wall.color_aci, wall.linetype, wall.lineweight) == (7, "Continuous", 35)
    assert (wall.on, wall.frozen, wall.locked, wall.plotted) == (True, False, False, True)
    assert wall.entities == 12
    assert by_name["S-COLS"].linetype == "HIDDEN" and by_name["S-COLS"].locked is True
    assert by_name["P-EQ"].on is False
    assert by_name["A-DEAD"].frozen is True and by_name["A-DEAD"].entities == 0


def test_annotation_counts_per_layer(model):
    by_name = {layer.name: layer for layer in model.layers}
    dims = by_name["A-ANNO-DIM"]
    assert dims.dimensions == 4 and dims.annotations == 4 and dims.text == 0
    assert by_name["A-ANNO-TEXT"].text == 3
    assert by_name["A-WALL"].annotations == 0


def test_layer_stats(model):
    stats = model.layer_stats
    assert stats["count"] == 10
    assert stats["off"] == 1 and stats["frozen"] == 1 and stats["locked"] == 1
    assert stats["empty"] >= 1 and stats["used"] == 6
    assert stats["with_dimensions"] == 1
    assert stats["top_by_entities"][0] == {"name": "A-WALL", "entities": 12}
    assert 0 < stats["annotation_ratio"] < 1
    assert stats["referenced_but_undefined"] == []  # every layer used is defined


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------


def test_entities_are_counted_by_type_and_layout(model):
    entities = model.entities
    assert entities["total"] == 27
    assert entities["by_type"] == {
        "LINE": 12,
        "INSERT": 7,
        "DIMENSION": 4,
        "TEXT": 2,
        "MTEXT": 1,
        "CIRCLE": 1,
    }
    assert entities["distinct_types"] == 6
    assert entities["geometry"] == 13
    assert entities["annotations"] == 7  # dimensions + text
    assert entities["inserts"] == 7
    assert entities["attribs"] == 15  # ATTRIB values are not layout entities
    assert entities["text_entities"] == 18  # 3 + 15
    assert entities["three_d"] == 0
    assert entities["layout_breakdown"]["Model"]["LINE"] == 12


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------


def test_blocks_profile_complexity_and_find_reusable_components(model):
    blocks = {block.name: block for block in model.blocks}
    door = blocks["DOOR_STD"]
    assert door.references == 4
    assert door.entities == 4  # 1 LINE + 3 ATTDEF
    assert door.attribute_tags == ["FIRE_RATING", "TYPE", "WIDTH"]
    assert door.entity_types == {"ATTDEF": 3, "LINE": 1}
    assert door.leverage == door.entities * door.references == 16
    assert door.anonymous is False and door.external is False
    assert blocks["UNUSED_BLOCK"].references == 0
    stats = model.block_stats
    assert stats["definitions"] == 10  # includes ezdxf template blocks
    assert stats["used"] == 2 and stats["unused"] >= 1
    assert stats["with_attributes"] == 2
    assert stats["insert_entities"] == 7
    assert stats["distinct_insert_names"] == 2
    assert stats["reusable"][0] == {"name": "DOOR_STD", "references": 4, "entities": 4}


# ---------------------------------------------------------------------------
# text (incl. ATTRIB) and dimensions
# ---------------------------------------------------------------------------


def test_text_attrib_and_mtext_extraction(model):
    by_kind = {}
    for item in model.text:
        by_kind.setdefault(item.kind, []).append(item)
    assert set(by_kind) == {"text", "mtext", "attrib"}
    assert {item.text for item in by_kind["text"]} == {
        "ALL DIMENSIONS TO FACE OF STUD UNLESS NOTED",
        "GRID A",
    }
    assert "\\P" not in by_kind["mtext"][0].text
    assert "Tolerances per ACI 117." in by_kind["mtext"][0].text
    attribs = by_kind["attrib"]
    assert len(attribs) == 15
    assert {(item.tag, item.text) for item in attribs} >= {
        ("TYPE", "SINGLE"),
        ("WIDTH", "36"),
        ("FIRE_RATING", "45"),
        ("LOAD_KN", "200"),
    }
    stats = model.text_stats
    assert stats["total"] == 18 and stats["attribs"] == 15
    assert stats["by_kind"] == {"attrib": 15, "text": 2, "mtext": 1}
    assert stats["truncated"] is False and stats["cap"] == 800


def test_dimensions_measure_and_flag_overrides(model):
    assert len(model.dimensions) == 4
    assert [dimension.value for dimension in model.dimensions] == [2, 2, 2, 2]
    assert all(dimension.kind == "linear" for dimension in model.dimensions)
    assert all(dimension.layer == "A-ANNO-DIM" for dimension in model.dimensions)
    assert all(dimension.unit == "Millimeters" for dimension in model.dimensions)
    assert all(dimension.dimstyle == "EZDXF" for dimension in model.dimensions)
    plain = [dimension for dimension in model.dimensions if dimension.text is None]
    overridden = [dimension for dimension in model.dimensions if dimension.text == "3000 TYP"]
    assert len(plain) == 3 and all(dimension.flags == [] for dimension in plain)
    assert len(overridden) == 1 and overridden[0].flags == ["text_override"]
    stats = model.dimension_stats
    assert stats["total"] == 4 and stats["with_text_override"] == 1
    assert stats["unmeasured"] == 0 and stats["user_positioned_text"] == 0
    assert stats["measured"] == {"count": 4, "min": 2, "max": 2, "median": 2.0, "unit": "Millimeters"}


def test_linear_factor_is_reported_for_dimstyles(arch_doc):
    model = build_cad_model(arch_doc)
    ezdxf_style = next(item for item in model.dimension_styles if item["name"] == "EZDXF")
    assert ezdxf_style["linear_factor"] == 100  # ezdxf's default template value
    assert ezdxf_style["decimal_places"] == 2


# ---------------------------------------------------------------------------
# tables, layouts, discipline
# ---------------------------------------------------------------------------


def test_linetype_table_flags_undefined_linetypes(model):
    # The fixture puts S-COLS on HIDDEN, which ezdxf's template does not define.
    dashed = next(item for item in model.linetypes if item["name"] == "DASHED")
    assert dashed["segments"] == 2
    assert model.layer_stats["linetypes_undefined"] == ["HIDDEN"]
    assert any("not defined in the LTYPE table" in warning for warning in model.warnings)


def test_linetypes_and_text_styles(model):
    names = {item["name"] for item in model.linetypes}
    assert {"ByBlock", "ByLayer", "Continuous", "DASHED", "CENTER"} <= names
    dashed = next(item for item in model.linetypes if item["name"] == "DASHED")
    assert dashed["segments"] == 2
    assert dashed["description"]
    styles = {item["name"]: item for item in model.text_styles}
    assert "Standard" in styles
    assert set(styles["Standard"]) >= {"name", "font", "width_factor"}


def test_layouts_and_extents(model):
    layouts = {item["name"]: item for item in model.layouts}
    # every layout of the document is listed, empty sheets included
    assert set(layouts) >= {"Model", "Layout1"}
    assert layouts["Model"]["is_modelspace"] is True
    assert layouts["Model"]["entities"] == 27
    assert layouts["Layout1"]["entities"] == 0
    assert model.layouts[0]["name"] == "Model"
    extents = model.document["extents"]
    assert extents["min"][0] == pytest.approx(0.0, abs=1.0)
    assert extents["max"][0] >= 10


def test_discipline_is_inferred_and_attached(model, mech_doc):
    assert model.discipline["primary"] == "architectural"
    # share of total evidence: mechanical picks up CENTER/HIDDEN linetype signals
    assert 0.5 < model.discipline["confidence"] <= 1.0
    assert model.discipline["mixed"] is False
    assert model.discipline["candidates"][0]["discipline"] == "architectural"
    assert build_cad_model(mech_doc).discipline["primary"] == "mechanical"


def test_no_extraction_failures_are_reported(model):
    # the only warning is the intentional QC finding (undefined HIDDEN linetype)
    assert model.warnings == ["1 layer linetype(s) are not defined in the LTYPE table: HIDDEN"]
    assert model.proxies == {"count": 0, "by_type": {}}
    assert model.extraction["entities_seen"] == 27
    assert model.extraction["limits"] == {"max_text_items": 800, "max_dimensions": 400, "max_blocks": 120, "max_layers": 200}


# ---------------------------------------------------------------------------
# limits, compaction, parsed input
# ---------------------------------------------------------------------------


def test_caps_limit_collected_items(arch_doc):
    limits = ExtractionLimits(max_text_items=3, max_dimensions=2, max_blocks=2, max_layers=3)
    warnings = Warnings()
    scan = scan_layouts(arch_doc, limits=limits, warnings=warnings)
    assert len(scan.texts) == 3
    assert scan.text_truncated is True
    assert len(scan.dimensions) == 2
    assert scan.dim_truncated is True
    blocks, stats = extract_blocks(arch_doc, scan, limits=limits, warnings=warnings)
    # stats always describe the whole table; the *list* is what gets capped
    assert stats["definitions"] == len(blocks) == 10

    model = build_cad_model(arch_doc, settings=Settings.from_env(environ={"CAD2AI_MAX_TEXT_ITEMS": "4"}))
    assert len(model.text) == 4
    assert model.text_stats["truncated"] is True


def test_handles_are_opt_in(arch_doc):
    with_handles = scan_layouts(arch_doc, limits=ExtractionLimits(include_handles=True), warnings=Warnings())
    assert any(text.handle for text in with_handles.texts)
    without = scan_layouts(arch_doc, limits=ExtractionLimits(), warnings=Warnings())
    assert all(text.handle is None for text in without.texts)


def test_model_is_json_serialisable(model):
    data = model.as_dict()
    restored = json.loads(json.dumps(data))
    assert restored["schema"] == "1.0"
    assert {layer["name"] for layer in restored["layers"]} == {layer.name for layer in model.layers}
    assert restored["entities"]["by_type"]["INSERT"] == 7


def test_compact_drops_empty_fields(model):
    dumped = model.as_dict()
    dead = next(item for item in dumped["layers"] if item["name"] == "A-DEAD")
    assert dead["frozen"] is True
    assert dead.get("entities", 0) == 0
    wall = next(item for item in dumped["layers"] if item["name"] == "A-WALL")
    assert wall["entities"] == 12
    text = next(item for item in dumped["text"] if item["kind"] == "text")
    assert "tag" not in text  # dropped: TEXT has no attribute tag


def test_build_from_parsed_drawing(arch_dxf):
    parsed = load_drawing(arch_dxf)
    model = build_cad_model(parsed)
    assert model.source["file"] == "demo.dxf"
    assert model.source["backend"] == "ezdxf.readfile"
    assert model.source["size_bytes"] == parsed.size_bytes
    assert model.source["sha256"] == parsed.sha256
    summary = model.summary()
    assert summary == {
        "source": "demo.dxf",
        "backend": "ezdxf.readfile",
        "units": "Millimeters",
        "layers": 10,
        "blocks": 10,
        "entities": 27,
        "text_items": 18,
        "dimensions": 4,
        "discipline": "architectural",
        "warnings": 0,
    }
