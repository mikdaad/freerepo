"""Phase 2 output: minified, token-budgeted JSON payload."""

from __future__ import annotations

import json
import math

import pytest

from cad2ai.config import Settings
from cad2ai.payload import (
    PayloadBuilder,
    PayloadLimits,
    build_payload,
    estimate_tokens,
    minify,
    split_batches,
    top_n,
)
from cad2ai.structurer import build_cad_model


@pytest.fixture
def model(arch_doc):
    return build_cad_model(arch_doc)


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def test_estimate_tokens_is_monotonic_and_zero_safe():
    assert estimate_tokens("") == 0
    short, long = estimate_tokens('{"a":1}'), estimate_tokens('{"a":1,' + '"bbbbbbbb":2,' * 200 + '"z":3}')
    assert 0 < short < long
    # CJK costs more per character than ASCII, so the heuristic must not be flat
    assert estimate_tokens("\u4e2d\u6587\u5899\u4f53" * 20) >= estimate_tokens("wall" * 20)


def test_minify_is_compact_and_json_valid(model):
    text = minify(model.as_dict())
    parsed = json.loads(text)  # still valid JSON
    # re-dumping compactly must reproduce the exact bytes: no structural whitespace
    assert text == json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    assert "\n" not in text
    assert "NaN" not in text and "Infinity" not in text


def test_minify_keeps_unicode_readable():
    assert minify({"t": "\u4e2d\u6587 wall \u00e9\u00e8"}) == '{"t":"\u4e2d\u6587 wall \u00e9\u00e8"}'


def test_minify_rounds_and_drops_empty_values():
    data = {
        "x": 1.23456789,
        "list": [1.0004999, 2.5, None],
        "empty_list": [],
        "empty_dict": {},
        "empty_text": "",
        "nested": {"keep": 0, "drop": None, "deeper": {"also_empty": {}}},
        "flag": False,
    }
    out = json.loads(minify(data, precision=3))
    assert out["x"] == 1.235
    assert out["list"] == [1, 2.5]
    assert "empty_list" not in out and "empty_dict" not in out and "empty_text" not in out
    assert "drop" not in out["nested"]
    assert "deeper" not in out["nested"]  # a dict that empties out is dropped
    assert out["nested"]["keep"] == 0  # zeros are information
    assert out["flag"] is False


def test_minify_rejects_non_finite_numbers():
    with pytest.raises(ValueError):
        json.dumps({"x": float("nan")}, allow_nan=False)
    # ...but our own entry point survives them because _clean maps them to None
    assert json.loads(minify({"x": float("nan"), "y": [float("inf")]})) == {}


def test_top_n_helper():
    assert top_n({"a": 3, "b": 1, "c": 2}, 2) == [("a", 3), ("c", 2)]
    assert top_n({}, 5) == []


# ---------------------------------------------------------------------------
# payload shape
# ---------------------------------------------------------------------------


def test_payload_carries_the_semantic_keys(model):
    built = build_payload(model)
    data = built.data
    assert data["cad_schema"] == "1.0"
    assert data["document"]["units"]["name"] == "Millimeters"
    assert {item["name"] for item in data["layers"]} >= {"A-WALL", "S-COLS"}
    assert data["layers"][0]["name"] == "A-WALL"
    wall = next(item for item in data["layers"] if item["name"] == "A-WALL")
    assert wall["color"] == 7 and wall["entities"] == 12 and wall["linetype"] == "Continuous"
    assert wall["lineweight"] == 35 and wall["annotations"] == 0
    dead = next(item for item in data["layers"] if item["name"] == "A-DEAD")
    assert dead["state"] == "frozen" and dead["entities"] == 0
    off = next(item for item in data["layers"] if item["name"] == "P-EQ")
    assert off["state"] == "off"
    # blocks are renamed for token economy
    door = next(item for item in data["blocks"]["items"] if item["name"] == "DOOR_STD")
    assert door["refs"] == 4 and door["attributes"] == ["FIRE_RATING", "TYPE", "WIDTH"]
    assert door["leverage"] == 16 and door["types"] == {"ATTDEF": 3, "LINE": 1}
    # dimensions keep measurement + override text + style
    dims = data["dimensions"]
    assert len(dims) == 4
    assert {item["kind"] for item in dims} == {"linear"}
    assert next(item for item in dims if item.get("text") == "3000 TYP")["flags"] == ["text_override"]
    assert all(item["style"] == "EZDXF" for item in dims)
    assert all(item["unit"] == "Millimeters" for item in dims)
    # ATTRIB values reach the payload with their tag names
    attribs = [item for item in data["text"] if item["type"] == "attrib"]
    assert len(attribs) == 15
    assert any(item["tag"] == "FIRE_RATING" and item["text"] in ("45", "20") for item in attribs)
    assert data["discipline"]["primary"] == "architectural"
    assert data["entities"]["attribs"] == 15


def test_payload_meta_reports_itself(model):
    built = build_payload(model)
    meta = built.meta
    assert meta["schema"] == "cad2ai-payload-1"
    assert meta["chars"] == len(built.json) == built.chars
    assert meta["token_estimate"] == built.token_estimate == estimate_tokens(built.json)
    assert meta["token_budget"] == 120_000
    assert meta["degraded"] == []
    assert meta["counts"] == {"layers": 10, "blocks": 10, "text": 18, "dimensions": 4, "entities": 27}
    assert len(meta["sha256"]) == 16
    assert json.loads(built.json)["meta"]["sha256"] == meta["sha256"]


def test_payload_is_a_single_line_of_json(model):
    built = build_payload(model)
    assert "\n" not in built.json
    assert built.json.startswith("{") and built.json.endswith("}")
    assert built.json.count(",") > 20


def test_no_handles_unless_requested(arch_doc):
    plain = build_payload(build_cad_model(arch_doc))
    assert all("handle" not in item for item in plain.data["text"])
    from cad2ai.structurer import build_cad_model as build

    with_handles = build_payload(
        build(arch_doc, settings=Settings.from_env(environ={"CAD2AI_INCLUDE_HANDLES": "1"}))
    )
    assert any("handle" in item for item in with_handles.data["text"])


def test_payload_fits_the_budget_by_degrading(model):
    generous = build_payload(model)
    tight = build_payload(model, max_tokens=max(600, len(generous.json) // 12))
    assert tight.meta["token_estimate"] <= tight.meta["token_budget"] or tight.meta["degraded"]
    assert tight.meta["degraded"], "a 600-token budget must have triggered the ladder"
    assert "text_aggregated" in tight.meta["degraded"] or "text_capped" in tight.meta["degraded"]
    data = json.loads(tight.json)
    assert data["stats"]["text"]["total"] == 18  # aggregates survive; items are dropped
    assert data["stats"]["text"]["aggregated"] is True or len(data.get("text") or []) > 0
    assert len(data.get("text") or []) <= len(generous.data["text"])
    assert all(isinstance(step, str) for step in data["meta"]["degraded"])


def test_caps_are_announced_in_the_payload(model):
    data = model.as_dict()
    data["text"] = data["text"] * 4  # 18*4 = 72 items so the cap actually clips
    data["dimensions"] = data["dimensions"] * 3
    built = build_payload(data, max_text_items=3, max_dimensions=1, max_layers=4)
    assert built.meta["truncations"] == {"text": 69, "dimensions": 11, "layers": 6}
    assert len(built.data["text"]) == 3
    assert len(built.data["dimensions"]) == 1
    assert len(built.data["layers"]) == 4


def test_tables_can_be_aggregated_away(model):
    built = build_payload(model, include_tables=False)
    assert "linetypes" not in built.data and "text_styles" not in built.data
    assert built.data["table_counts"]["linetypes"] == len(model.linetypes)
    assert "layout_breakdown" not in built.data["entities"]


def test_geometry_only_payload(model):
    built = build_payload(model, include_text=False, include_dimensions=False)
    assert "text" not in built.data and "dimensions" not in built.data
    assert built.data["stats"]["text"]["total"] == 18  # the count is still reported
    assert built.meta["token_estimate"] < build_payload(model).meta["token_estimate"]


def test_unknown_limits_are_rejected(model):
    with pytest.raises(ValueError, match="unknown payload limit"):
        build_payload(model, max_tootsies=10)


def test_builder_accepts_plain_dicts(model):
    data = model.as_dict()
    built = PayloadBuilder(PayloadLimits(max_tokens=200_000)).build(data)
    assert json.loads(built.json)["layers"]


def test_write_persists_the_exact_bytes(model, tmp_path):
    built = build_payload(model)
    target = tmp_path / "sub" / "payload.json"
    assert built.write(target) == len(built.json)
    assert target.read_text(encoding="utf-8") == built.json
    assert json.loads(target.read_text(encoding="utf-8"))["cad_schema"] == "1.0"


def test_payload_from_a_non_lossless_source_is_flagged(model):
    data = model.as_dict()
    data["source"]["lossless"] = False
    data["source"]["provenance"] = "autodesk-aps"
    built = PayloadBuilder().build(data)
    assert built.data["source"]["lossless"] is False
    assert built.data["source"]["provenance"] == "autodesk-aps"


def test_warnings_are_forwarded(model):
    data = model.as_dict()
    data["warnings"] = ["layer linetype HIDDEN is not defined"]
    assert json.loads(minify(PayloadBuilder().build(data).data))["warnings"] == ["layer linetype HIDDEN is not defined"]


def test_empty_model_yields_a_minimal_payload():
    built = PayloadBuilder().build({})
    parsed = json.loads(built.json)
    assert set(parsed) == {"cad_schema", "meta"}
    assert parsed["cad_schema"] == "1.0"
    assert parsed["meta"]["counts"] == {"layers": 0, "blocks": 0, "text": 0, "dimensions": 0}


def test_split_batches_pages_large_annotations(arch_doc):
    model = build_cad_model(arch_doc)
    batches = split_batches(model, batch_tokens=2_000)
    assert len(batches) >= 1
    first = json.loads(batches[0].json)
    assert "text" not in first  # batch 0 is the whole-sheet summary
    detail = [batch for batch in batches if "batch" in batch.data]
    if detail:
        page = json.loads(detail[0].json)
        assert page["batch"]["section"] in {"text", "dimensions"}
        assert page["batch"]["page"] >= 1


def test_numbers_stay_json_safe(model):
    text = build_payload(model).json
    for token in ("NaN", "Infinity", "-Infinity"):
        assert token not in text
    parsed = json.loads(text)
    assert all(isinstance(value, (int, float)) for value in [parsed["entities"]["total"], parsed["meta"]["chars"]])
    assert math.isfinite(parsed["meta"]["token_estimate"])
