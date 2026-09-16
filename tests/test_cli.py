"""CLI surface: argument parsing, exit codes and stream discipline.

No network is used: ``analyze`` runs with ``--dry-run``, and the commands that
would call Autodesk/DeepSeek are only exercised on their argument validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad2ai.cli import build_parser, main
from cad2ai.errors import EXIT_CONFIG, EXIT_PARSE, EXIT_UNEXPECTED

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Scratch CWD + a private copy of the environment.

    ``load_dotenv`` writes into ``os.environ``, so a ``.env`` read by one test
    would otherwise leak into the next one (and into subprocesses).  Swapping the
    mapping wholesale keeps every test in this file hermetic.
    """
    import os

    monkeypatch.chdir(tmp_path)
    clean = {key: value for key, value in os.environ.items() if not key.startswith(("DEEPSEEK_", "APS_", "CAD2AI_", "ODA_"))}
    monkeypatch.setattr(os, "environ", clean)
    yield tmp_path


def run(argv: list[str]):
    return main(argv)


def parse_json_output(captured: str) -> dict:
    return json.loads(captured)


# ---------------------------------------------------------------------------
# parser shape
# ---------------------------------------------------------------------------


def test_parser_exposes_every_command():
    parser = build_parser()
    text = parser.format_help()
    for command in ("doctor", "extract", "analyze", "payload", "prompt", "aps"):
        assert command in text
    assert "ezdxf+odafc" in text


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "usage: cad2ai" in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "cad2ai" in capsys.readouterr().out


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_unknown_command(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["nope", "file.dwg"])
    assert excinfo.value.code == 2


def test_task_choices_are_validated():
    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", "x.dwg", "--task", "make_me_a_coffee"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_reports_availability(capsys):
    assert run(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "DeepSeek" in out and "APS fallback" in out and "Payload budget" in out
    assert "DEEPSEEK_API_KEY is not set" in out  # listed as a warning, not a failure


def test_doctor_json_is_pure_json(capsys):
    assert run(["doctor", "--json"]) == 0
    report = parse_json_output(capsys.readouterr().out)
    assert report["phase1_local"]["ezdxf_version"]
    assert set(report["phase1_local"]) >= {"platform", "oda_installed", "xvfb_available", "notes"}
    assert set(report["problems"]) >= {"DEEPSEEK_API_KEY is not set: Phase 3 (analyze without --dry-run) will fail"}
    assert report["deepseek"]["api_key_present"] is False
    assert report["deepseek"]["model"] == "deepseek-flash"
    assert report["autodesk_fallback"]["configured"] is False


def test_global_flags_work_before_and_after_the_command(capsys):
    """``--json`` is accepted on either side of the subcommand, and --check-api
    (which would hit the network) is never implied."""
    assert run(["doctor", "--json"]) == 0
    after = parse_json_output(capsys.readouterr().out)
    assert run(["--json", "doctor"]) == 0
    before = parse_json_output(capsys.readouterr().out)
    assert before == after


# ---------------------------------------------------------------------------
# extract / payload / prompt on a real DXF
# ---------------------------------------------------------------------------


def test_extract_prints_a_summary(capsys, arch_dxf):
    assert run(["extract", str(arch_dxf)]) == 0
    out = capsys.readouterr().out
    assert "via ezdxf.readfile" in out
    assert "units: Millimeters" in out
    assert "layers: 10" in out
    assert "entities: 27" in out


def test_extract_json_and_artifacts(capsys, arch_dxf, tmp_path):
    out_dir = tmp_path / "artifacts"
    assert run(["extract", str(arch_dxf), "--json", "--out", str(out_dir)]) == 0
    data = parse_json_output(capsys.readouterr().out)
    assert data["summary"]["entities"] == 27
    assert data["payload"]["token_estimate"] > 0
    assert data["backend"] == "ezdxf.readfile"
    assert (out_dir / "cad_model.json").is_file()
    assert (out_dir / "payload.json").is_file()


def test_extract_summary_only(capsys, arch_dxf):
    assert run(["extract", str(arch_dxf), "--json", "--summary-only"]) == 0
    summary = parse_json_output(capsys.readouterr().out)
    assert set(summary) >= {"entities", "layers", "blocks", "discipline"}
    assert "payload" not in summary


def test_extract_respects_payload_caps(capsys, arch_dxf):
    """The per-section caps apply to Phase 2 (so the model is honest about scope)
    as well as to the payload."""
    assert run(["extract", str(arch_dxf), "--json", "--max-text", "2", "--max-layers", "3", "--float-precision", "0"]) == 0
    data = parse_json_output(capsys.readouterr().out)
    assert data["summary"]["layers"] == 3
    assert data["summary"]["text_items"] == 2


def test_payload_command_writes_minified_json(capsys, arch_dxf, tmp_path):
    target = tmp_path / "deep" / "payload.json"
    assert run(["payload", str(arch_dxf), "--write", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert "\n" not in text.strip()
    assert json.loads(text)["cad_schema"]
    assert "wrote" in capsys.readouterr().err


def test_payload_command_prints_to_stdout(capsys, arch_dxf):
    assert run(["payload", str(arch_dxf)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["layers"]
    assert payload["meta"]["counts"]["entities"] == 27


def test_prompt_command_prints_both_messages(capsys, arch_dxf):
    assert run(["prompt", str(arch_dxf), "--task", "bom"]) == 0
    out = capsys.readouterr().out
    assert out.count("### role:") == 2
    assert "senior CAD/BIM data analyst" in out
    assert "TASK: Bill of materials / component takeoff" in out or "Bill of materials" in out


def test_prompt_system_only_needs_no_file(capsys):
    assert run(["prompt", "--system-only"]) == 0
    assert "PAYLOAD STRUCTURE" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def test_analyze_dry_run_needs_no_api_key(capsys, arch_dxf, tmp_path):
    out_dir = tmp_path / "run"
    assert run(["analyze", str(arch_dxf), "--dry-run", "--out", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "dry-run: True" in out
    assert "(no analysis produced)" in out
    assert "payload:" in out
    manifest = json.loads((out_dir / "run_manifest.json").read_text())
    assert manifest["ok"] is True
    assert "analysis.json" not in [Path(path).name for path in manifest["artifacts"].values()]


def test_analyze_dry_run_json(capsys, arch_dxf):
    assert run(["analyze", str(arch_dxf), "--dry-run", "--json", "--task", "complexity_metrics"]) == 0
    data = parse_json_output(capsys.readouterr().out)
    assert data["dry_run"] is True
    assert data["task"] == "complexity_metrics"
    assert data["analysis"] is None
    assert data["payload"]["token_budget"] > 0


def test_analyze_without_key_is_a_config_error(capsys, arch_dxf):
    """Phases 1-2 still run; only Phase 3 needs a key, and it says so."""
    assert run(["analyze", str(arch_dxf)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "DEEPSEEK_API_KEY" in err
    assert "hint:" in err


def test_analyze_uses_the_key_when_present(capsys, arch_dxf, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-cli-test")
    calls = {}

    class FakeClient:
        def complete(self, messages, *, label=""):
            from cad2ai.ai_client import ChatResult

            calls["messages"] = messages
            return ChatResult(content="{}", data={"summary": "from the fake client"}, parsed=True)

    import cad2ai.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module.Pipeline, "client", lambda self: FakeClient())
    assert run(["analyze", str(arch_dxf), "--json", "--brief", "check the fire doors"]) == 0
    data = parse_json_output(capsys.readouterr().out)
    assert data["analysis"] == {"summary": "from the fake client"}
    assert "check the fire doors" in calls["messages"][-1]["content"]


# ---------------------------------------------------------------------------
# error mapping
# ---------------------------------------------------------------------------


def test_missing_file_exits_with_parse_error(capsys, tmp_path):
    code = run(["extract", str(tmp_path / "ghost.dxf")])
    assert code == EXIT_PARSE
    err = capsys.readouterr().err
    assert "ghost.dxf" in err


def test_non_cad_content_is_rejected(capsys, tmp_path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("this is not a drawing", encoding="utf-8")
    assert run(["extract", str(text_file)]) == EXIT_PARSE
    assert "hint:" in capsys.readouterr().err


def test_dwg_without_converter_exits_and_suggests(capsys, fake_dwg):
    assert run(["extract", str(fake_dwg), "--fallback", "none"]) == EXIT_PARSE
    err = capsys.readouterr().err
    assert "ODA File Converter" in err
    assert "hint:" in err and "--fallback aps" in err


def test_dwg_without_converter_or_credentials_mentions_the_fallback(capsys, fake_dwg):
    assert run(["extract", str(fake_dwg)]) == EXIT_PARSE
    assert "APS_CLIENT_ID" in capsys.readouterr().err


def test_dxf_is_not_sent_to_the_converter(capsys, arch_dxf):
    assert run(["extract", str(arch_dxf), "--backend", "dxf"]) == 0
    assert "ezdxf.readfile" in capsys.readouterr().out


def test_json_error_output_is_parseable(capsys, tmp_path):
    assert run(["extract", str(tmp_path / "ghost.dxf"), "--json"]) == EXIT_PARSE
    payload = parse_json_output(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["exit_code"] == EXIT_PARSE
    assert payload["error"]["error"].endswith("Error")


def test_aps_status_only_requires_a_urn(capsys):
    assert run(["aps", "--status-only"]) == EXIT_CONFIG
    assert "--urn" in capsys.readouterr().err


def test_aps_without_credentials_fails_early(capsys, fake_dwg):
    assert run(["aps", str(fake_dwg)]) == EXIT_CONFIG
    assert "APS_CLIENT_ID" in capsys.readouterr().err


def test_unexpected_errors_are_wrapped_not_dumped(capsys, arch_dxf, monkeypatch):
    def boom(self, path, **kwargs):
        raise RuntimeError("bug in cad2ai")

    monkeypatch.setattr("cad2ai.pipeline.Pipeline.extract", boom)
    assert run(["extract", str(arch_dxf)]) == EXIT_UNEXPECTED
    err = capsys.readouterr().err
    assert "unexpected error: RuntimeError: bug in cad2ai" in err
    assert "CAD2AI_TRACEBACK=1" in err
    assert "Traceback" not in err


def test_traceback_env_var_reraises(arch_dxf, monkeypatch):
    def boom(self, path, **kwargs):
        raise RuntimeError("bug in cad2ai")

    monkeypatch.setattr("cad2ai.pipeline.Pipeline.extract", boom)
    monkeypatch.setenv("CAD2AI_TRACEBACK", "1")
    with pytest.raises(RuntimeError, match="bug in cad2ai"):
        run(["extract", str(arch_dxf)])


def test_verbose_flag_raises_log_level(capsys, arch_dxf):
    assert run(["extract", str(arch_dxf), "-v"]) == 0
    import logging

    assert logging.getLogger("cad2ai").level == logging.INFO


def test_env_file_is_honoured(capsys, tmp_path, arch_dxf):
    env = tmp_path / ".env"
    env.write_text("CAD2AI_MAX_PAYLOAD_TOKENS=900\n", encoding="utf-8")
    assert run(["extract", str(arch_dxf), "--json", "--env-file", str(env)]) == 0
    data = parse_json_output(capsys.readouterr().out)
    # a 900 token budget must force degradation on this drawing
    assert data["payload"]["degraded"]
    assert data["payload"]["token_estimate"] <= 4096


def test_invalid_environment_value_is_a_config_error(capsys, tmp_path, arch_dxf):
    env = tmp_path / ".env"
    env.write_text("CAD2AI_FLOAT_PRECISION=nine\n", encoding="utf-8")
    assert run(["extract", str(arch_dxf), "--env-file", str(env)]) == EXIT_CONFIG
    assert "config error" in capsys.readouterr().err
