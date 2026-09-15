"""Phase 2: discipline inference from layer names, linetypes and entity mix."""

from __future__ import annotations


from cad2ai.discipline import PROFILES, DisciplineProfile, infer_discipline, score_layers


def layer(name: str, entities: int = 10, linetype: str = "Continuous") -> dict:
    return {"name": name, "entities": entities, "linetype": linetype}


def test_architectural_layers_win():
    result = infer_discipline(
        [layer("A-WALL", 400), layer("A-DOOR", 40), layer("A-ANNO-DIMS", 20), layer("0", 5)],
        {"total": 500, "by_type": {"HATCH": 4}},
    )
    assert result["primary"] == "architectural"
    assert result["confidence"] > 0.6
    assert result["mixed"] is False
    assert result["standard_hint"] == "NIST/CAD layer naming (AIA), ISO 13567"


def test_mechanical_layers_win():
    result = infer_discipline(
        [layer("M-GEAR", 120), layer("M-TOL", 30), layer("M-BOLT", 60)],
        {"total": 210, "three_d": 40},
    )
    assert result["primary"] == "mechanical"
    assert any("3D/model entities" in signal for signal in result["signals"])


def test_mixed_discipline_is_flagged_not_forced():
    result = infer_discipline([layer("A-WALL", 100), layer("M-PART", 100)], {"total": 200})
    assert result["primary"] in {"architectural", "mechanical"}
    assert result["mixed"] is True
    assert len(result["candidates"]) >= 2
    # candidates stay ranked by score
    scores = [candidate["score"] for candidate in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_multi_discipline_project_set_ranks_the_dominant_discipline():
    result = infer_discipline(
        [
            layer("S-BEAM", 50),
            layer("S-COLS", 40),
            layer("E-PWR", 30),
            layer("P-EQ", 20),
            layer("H-DUCT", 15),
            layer("A-WALL", 60),
        ],
        {"total": 215},
    )
    names = {candidate["discipline"] for candidate in result["candidates"]}
    assert {"structural", "electrical", "plumbing", "hvac", "architectural"} <= names
    assert result["primary"] == "structural"  # two structural layers carry the most entities
    # ...but not by so much that the rest of the set is ignored: the runner-up
    # share (3.04/6.05 = 0.5) sits under the 0.6 "mixed" threshold.
    assert result["mixed"] is False


def test_entity_count_weights_the_evidence():
    empty_evidence = infer_discipline([layer("M-GEAR", 0), layer("A-WALL", 500)])
    assert empty_evidence["primary"] == "architectural"
    heavy_evidence = infer_discipline([layer("M-GEAR", 4000), layer("A-WALL", 5)])
    assert heavy_evidence["primary"] == "mechanical"


def test_unconventional_layer_names_are_undetermined():
    # "WALLS" still counts as architectural evidence (the word is the signal);
    # purely generic names carry no discipline information at all.
    result = infer_discipline([layer("L1"), layer("Layer0"), layer("ASDF"), layer("0")], {"total": 30})
    assert result["primary"] == "undetermined"
    assert result["confidence"] == 0.0
    assert result["signals"][0].startswith("no layer naming convention")


def test_empty_layer_table_does_not_raise():
    assert infer_discipline([])["primary"] == "undetermined"
    assert infer_discipline([])["confidence"] == 0.0


def test_linetypes_corroborate():
    base = [layer("PART-1", 20), layer("GEOM", 20)]
    without = infer_discipline(base, {"total": 40})
    with_center = infer_discipline(base, {"total": 40}, linetypes=[{"name": "CENTER"}, {"name": "HIDDEN"}])
    assert with_center["primary"] == "mechanical"
    assert any("linetype CENTER present" in signal for signal in with_center["signals"])
    assert without["primary"] in {"mechanical", "undetermined"}


def test_broken_entity_summary_is_tolerated():
    result = infer_discipline([layer("A-WALL", 10)], {"total": None, "three_d": "many"})  # type: ignore[dict-item]
    assert result["primary"] == "architectural"


def test_never_raises_on_junk_input():
    for junk in (["not-a-layer"], [None], [{"name": 7, "entities": "x"}], [DisciplineProfile()]):
        result = infer_discipline(junk, None)  # type: ignore[arg-type]
        assert "primary" in result and "confidence" in result


def test_score_layers_returns_weighted_buckets():
    scores = score_layers([layer("A-WALL", 0), layer("A-DOOR", 1000)])
    assert "architectural" in scores
    assert scores["architectural"]["score"] > 0
    assert "A-WALL" in scores["architectural"]["layers"]
    assert "mechanical" not in scores


def test_profile_regexes_compile_and_are_weighted():
    import re

    assert {"architectural", "structural", "mechanical", "electrical", "plumbing", "hvac"} <= set(PROFILES)
    for rules in PROFILES.values():
        for pattern, strength in rules:
            assert strength > 0
            re.compile(pattern)  # a broken pattern would silently disable a profile


def test_payload_records_the_decision(arch_doc):
    from cad2ai.structurer import build_cad_model

    model = build_cad_model(arch_doc)
    assert model.discipline["primary"] == "architectural"
    assert model.as_dict()["discipline"]["candidates"][0]["discipline"] == "architectural"
