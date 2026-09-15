"""DXF attribute access helpers -- the code that keeps ezdxf from exploding."""

from __future__ import annotations

import ezdxf
import pytest

from cad2ai import dxfutils
from cad2ai.dxfutils import Warnings, dxf_attr, point, round_float, safe, strip_mtext_markup, truncate_text


@pytest.fixture
def doc():
    document = ezdxf.new("R2018", setup=True)
    document.layers.new("L1", dxfattribs={"color": 3, "linetype": "DASHED"})
    return document


def test_dxf_attr_reads_present_attribute(doc):
    line = doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "L1", "thickness": 2.5})
    assert dxf_attr(line, "layer") == "L1"
    assert dxf_attr(line, "thickness") == 2.5
    assert dxf_attr(line, "color") == 256  # BYLAYER schema default, not an exception


def test_dxf_attr_returns_default_for_garbage_names(doc):
    line = doc.modelspace().add_line((0, 0), (1, 1))
    assert dxf_attr(line, "not_a_real_attribute") is None
    assert dxf_attr(line, "not_a_real_attribute", "fallback") == "fallback"
    # TEXT-only attributes must not blow up when read from a LINE
    assert dxf_attr(line, "text", "<none>") == "<none>"


def test_has_dxf_attr(doc):
    line = doc.modelspace().add_line((0, 0), (1, 1))
    text = doc.modelspace().add_text("hi", dxfattribs={"height": 2.0})
    assert dxfutils.has_dxf_attr(line, "start") is True
    assert dxfutils.has_dxf_attr(line, "text") is False
    assert dxfutils.has_dxf_attr(text, "text") is True
    assert dxfutils.has_dxf_attr(object(), "text") is False


def test_safe_swallows_dxf_and_value_errors(doc):
    assert safe(lambda: int("not a number"), default="n/a", context="demo") == "n/a"
    # programming errors are deliberately NOT swallowed
    with pytest.raises(ZeroDivisionError):
        safe(lambda: 1 / 0, default="n/a")
    warnings = Warnings()
    assert safe(lambda: doc.header["$NOPE"], None, context="header", warnings=warnings) is None


def test_round_float_is_sane():
    assert round_float(1.23456, 3) == 1.235
    assert round_float(1.0, 3) == 1
    assert round_float(-0.0004, 3) == 0
    assert round_float(None) is None
    assert round_float("abc") == "abc"
    assert round_float([1.0004999, 2.0000001], 3) == [1, 2]  # integers when exact
    assert round_float(float("nan")) is None
    assert round_float(True) is True


def test_point_handles_vec3_and_junk():
    from ezdxf.math import Vec3

    assert point(Vec3(1.0004, 2, 3), 3) == [1.0, 2.0, 3.0]
    assert point(Vec3(1, 2, 0)) == [1, 2]  # z dropped when flat
    assert point((1, 2), 1) == [1.0, 2.0]
    assert point(None) is None
    assert point("nope") is None


def test_degrees_rounds_and_rejects_junk():
    assert dxfutils.degrees(90.0) == 90.0
    assert dxfutils.degrees("nope") is None
    assert dxfutils.degrees(0.0) == 0.0
    assert dxfutils.degrees(None) is None


def test_text_helpers(doc):
    assert truncate_text("abcdefghij", 5) == "abcd\u2026"
    assert truncate_text("short", 100) == "short"
    assert truncate_text(None, 10) is None
    assert strip_mtext_markup(r"Line one\PLine two") == "Line one Line two"
    assert strip_mtext_markup(r"{\fArial|b0|i0;bold} text") == "bold text"
    assert strip_mtext_markup(r"\C5;red \H2x;big") == "red big"
    assert strip_mtext_markup(r"100 \S+0.1^-0.2; mm") == "100 +0.1 mm"
    assert strip_mtext_markup("no markup at all") == "no markup at all"


def test_warnings_dedupe_and_cap():
    warnings = Warnings()
    warnings.add("boom")
    warnings.add("boom")
    warnings.add("bang")
    assert warnings.items == ["boom", "bang"]
    assert len(warnings) == 3  # repeats are counted even though they are not repeated
    assert warnings.as_list()[-1].startswith("repeat_counts=boom:2")
    for index in range(400):
        warnings.add(f"unique {index}")
    assert len(warnings.items) == warnings.max_unique


def test_iter_layout_entities_covers_paper_space(doc):
    doc.modelspace().add_line((0, 0), (1, 1))
    layout = doc.new_layout("Sheet")
    layout.add_line((0, 0), (2, 2))
    pairs = list(dxfutils.iter_layout_entities(doc))
    names = {name for name, _ in pairs}
    assert "Model" in names
    assert "Sheet" in names
    assert len(pairs) == 2
    assert dxfutils.iter_layout_names(doc) == ["Model", "Layout1", "Sheet"]


def test_sha256_prefix(tmp_path):
    target = tmp_path / "a.dxf"
    target.write_bytes(b"hello")
    digest = dxfutils.sha256_prefix(target)
    assert digest and len(digest) == 12
    assert dxfutils.sha256_prefix(tmp_path / "missing") is None
