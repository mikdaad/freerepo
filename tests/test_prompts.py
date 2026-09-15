"""Phase 3 prompt construction (system brief, tasks, messages)."""

from __future__ import annotations

import json

import pytest

from cad2ai.prompts import (
    ACI_COLORS,
    GROUNDING_RULES,
    SCHEMA_BRIEF,
    TASKS,
    TaskSpec,
    build_messages,
    build_system_prompt,
    build_task_message,
    resolve_task,
)


def test_system_prompt_teaches_the_payload_schema():
    prompt = build_system_prompt()
    for key in ("layers", "blocks", "dimensions", "text", "document.units", "discipline", "degraded", "truncations"):
        assert key in prompt, f"{key} is not explained to the model"
    assert "ACI" in prompt or "color" in prompt
    assert "json" in prompt.lower(), "DeepSeek JSON mode requires the word 'json' in the prompt"
    # every rule is present and numbered
    for marker in ("1.", "5.", "10."):
        assert marker in prompt


def test_schema_brief_documents_units_and_overrides():
    assert "dimension" in SCHEMA_BRIEF.lower()
    assert "text_override" in SCHEMA_BRIEF or "override" in SCHEMA_BRIEF
    assert "lossless" in SCHEMA_BRIEF


def test_grounding_rules_forbid_invention():
    assert "Never invent" in GROUNDING_RULES
    assert "evidence" in GROUNDING_RULES
    assert "data_gaps" in GROUNDING_RULES


def test_extra_instructions_take_priority():
    prompt = build_system_prompt(extra_instructions="Only report mechanical findings.")
    assert "OPERATOR INSTRUCTIONS (highest priority)" in prompt
    assert "Only report mechanical findings." in prompt
    assert prompt.index("OPERATOR INSTRUCTIONS") > prompt.index("RULES (mandatory)")


def test_markdown_output_mode_is_announced():
    prompt = build_system_prompt(output_mode="markdown")
    assert "markdown prose is allowed" in prompt
    assert "OUTPUT SCHEMA" not in prompt or "single valid JSON object" not in prompt


def test_audience_is_included():
    assert "contractor" in build_system_prompt(audience="site contractor")


def test_all_tasks_are_well_formed():
    assert len(TASKS) >= 5
    for key, spec in TASKS.items():
        assert isinstance(spec, TaskSpec)
        assert spec.key == key
        assert spec.title and len(spec.title) > 3
        assert spec.output_schema, f"{key} has no output schema"
        schema = json.dumps(spec.output_schema)
        if spec.key == "custom":
            assert "summary" in schema and "data_gaps" in schema  # deliberately minimal
        else:
            assert "drawing" in schema and "confidence" in schema  # shared answer header
        # focus names payload sections the model should read first; the custom
        # task deliberately leaves it empty, which renders as "all".
        assert spec.focus or spec.key == "custom"
        for section in spec.focus:
            assert section in SCHEMA_BRIEF or section.endswith("s"), section
        rendered = spec.render_instructions()
        assert f"TASK: {spec.title}" in rendered
        assert spec.schema_text() in rendered
        json.loads(spec.schema_text())  # the schema must be valid JSON


def test_bom_task_asks_for_block_attributes():
    spec = TASKS["bom"]
    text = spec.render_instructions()
    assert "attribute" in text.lower()
    assert "units" in text.lower()
    schema = json.dumps(spec.output_schema)
    assert "quantity" in schema and "attributes" in schema and "fill_rate" in schema
    assert "units" in spec.output_schema
    assert spec.focus == ("blocks", "text", "document.units")


def test_sheet_review_triages_and_recommends_release():
    schema = json.dumps(TASKS["sheet_review"].output_schema)
    assert "severity" in schema and "recommendation" in schema
    assert "checks_not_possible_from_data" in schema  # honesty about visual checks


def test_task_aliases_and_fallbacks():
    assert resolve_task("qa").key == "sheet_review"
    assert resolve_task("materials").key == "bom"
    assert resolve_task("METRICS").key == "complexity_metrics"
    assert resolve_task("compliance").key == "standards_compliance"
    assert resolve_task("summary").key == "discipline_summary"
    assert resolve_task("  Sheet-Review ").key == "sheet_review"
    assert resolve_task("whatever the client asked").key == "custom"
    assert resolve_task(None).key == "discipline_summary"
    assert resolve_task("").key == "discipline_summary"


def test_task_message_embeds_the_payload_and_brief():
    payload = json.dumps({"layers": [{"name": "A-WALL", "entities": 12}]}, separators=(",", ":"))
    message = build_task_message("bom", payload_json=payload, brief="Cost per line item", context={"file": "A-101.dwg"})
    assert "CLIENT BRIEF" in message and "Cost per line item" in message
    assert "RUN CONTEXT" in message and "A-101.dwg" in message
    assert "DWG PAYLOAD (minified JSON):" in message
    assert payload in message
    assert "Respond with the JSON object only." in message
    assert "TASK: " in message


@pytest.fixture
def config_payload():
    from cad2ai.payload import build_payload
    from cad2ai.structurer import build_cad_model
    from conftest import build_architecture_doc

    return build_payload(build_cad_model(build_architecture_doc())).json


def test_messages_are_a_system_user_pair(config_payload):
    messages = build_messages(config_payload, task="sheet_review", brief="focus on fire doors")
    assert [message["role"] for message in messages] == ["system", "user"]
    assert config_payload in messages[1]["content"]
    assert "PAYLOAD STRUCTURE" in messages[0]["content"]
    # the schema is anchored in the system prompt too (JSON mode reliability)
    assert "single valid JSON object" in messages[0]["content"]
    assert "release_recommendation" in messages[0]["content"]  # the task schema is anchored
    assert "TASK:" in messages[1]["content"]


def test_markdown_mode_does_not_anchor_a_schema():
    messages = build_messages("{}", task="bom", output_mode="markdown")
    assert "matching this schema exactly" not in messages[0]["content"]
    assert "markdown prose is allowed" in messages[0]["content"]


def test_task_object_can_be_passed_directly():
    spec = TaskSpec(key="x", title="Custom job", instructions="Do the thing.", output_schema={"a": "string"})
    messages = build_messages("{}", task=spec)
    assert "Custom job" in messages[1]["content"]
    assert "Do the thing." in messages[1]["content"]


def test_aci_colors_cover_the_standard_first_two_eights():
    assert ACI_COLORS[1] == "red"
    assert ACI_COLORS[7].startswith("white/black")  # background dependent, documented as such
    assert set(ACI_COLORS) >= {1, 2, 3, 4, 5, 6, 7, 9}


def test_prompt_size_is_bounded():
    system = build_system_prompt()
    assert len(system) < 12_000, "the schema brief must stay small enough to amortise over one payload"
    assert len(system) > 2_000, "if the brief shrank to nothing the model cannot read the payload"
