"""End-to-end orchestration: phases 1→2→3, artifacts and markdown rendering.

Phase 3 is always a stubbed client, and the Autodesk fallback uses an injected
fake APS client, so these tests run offline while still exercising the real
parser (DXF path), structurer, payload builder and prompt builder.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cad2ai.ai_client import ChatResult, UsageSnapshot
from cad2ai.aps import ApsExtraction, OssObject, normalize_manifest
from cad2ai.errors import (
    ConfigError,
    DeepSeekRateLimitError,
    DwgConverterNotInstalledError,
    ParseError,
    UnsupportedDwgVersionError,
)
from cad2ai.pipeline import (
    Pipeline,
    cleanup_dir,
    extract as extract_phases,
    extraction_manifest,
    render_markdown,
)
from cad2ai.structurer import build_cad_model
from conftest import build_architecture_doc

ANALYSIS = {
    "drawing": "A-101",
    "summary": "Two load-bearing walls are unannotated.",
    "findings": [
        {
            "title": "Missing dimension on grid line 3",
            "severity": "high",
            "evidence": ["dimensions.count=4", "layers[2].name=S-COLS"],
            "recommendation": "add the dimension before issue",
        }
    ],
    "data_gaps": ["no proxy entities in the payload"],
    "confidence": 0.72,
}


class StubClient:
    def __init__(self, data=None, *, error: Exception | None = None) -> None:
        self.calls: list[list[dict]] = []
        self.data = ANALYSIS if data is None else data
        self.error = error

    def complete(self, messages, *, label: str = "", **kwargs):
        from cad2ai.payload import estimate_tokens

        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        # A believable prompt size: the stub "sees" the whole message list.
        prompt_tokens = sum(estimate_tokens(str(message.get("content") or "")) for message in messages)
        return ChatResult(
            content=json.dumps(self.data),
            data=self.data,
            parsed=True,
            usage=UsageSnapshot(prompt_tokens=prompt_tokens, completion_tokens=567, total_tokens=prompt_tokens + 567, cached_tokens=1000),
            model="deepseek-flash",
            id="chatcmpl-stub",
            finish_reason="stop",
        )

    @property
    def total_usage(self):
        return UsageSnapshot(prompt_tokens=12_345, completion_tokens=567, total_tokens=12_912)


def stub_loader(path, *, settings=None, **kwargs):
    document = build_architecture_doc()
    return SimpleNamespace(
        doc=document,
        source=str(path),
        backend=SimpleNamespace(value="ezdxf"),
        dwg=None,
        warnings=[],
        audit=None,
        size_bytes=1024,
        sha256="abc123",
        provenance="local",
        timings={},
        summary=lambda: {"backend": "ezdxf", "audit": None},
    )


@pytest.fixture
def stub_pipeline(settings):
    client = StubClient()
    pipeline = Pipeline(settings, load=stub_loader, build_model=lambda parsed, settings=None: build_cad_model(parsed.doc), client_factory=lambda s: client)
    pipeline.stub_client = client
    return pipeline


# ---------------------------------------------------------------------------
# full run
# ---------------------------------------------------------------------------


def test_run_returns_payload_analysis_and_usage(stub_pipeline, tmp_path):
    report = stub_pipeline.run("A-101.dwg", task="sheet_review", brief="focus on fire rating", out_dir=tmp_path)
    assert report.ok is True
    assert report.mode == "ezdxf"
    assert report.task == "sheet_review"
    assert report.analysis == ANALYSIS
    payload = json.loads(report.payload)
    assert payload["cad_schema"]
    assert payload["layers"]
    assert report.usage["prompt_tokens"] > 0 and report.usage["completion_tokens"] == 567
    # the run context tells the model what it must not assume
    user_message = stub_pipeline.stub_client.calls[0][-1]["content"]
    assert "focus on fire rating" in user_message
    assert '"units":"Millimeters"' in user_message
    assert '"lossless":true' in user_message


def test_usage_is_reported_on_the_pipeline_client(settings):
    client = StubClient()
    pipeline = Pipeline(settings, load=stub_loader, build_model=lambda parsed, settings=None: build_cad_model(parsed.doc), client_factory=lambda s: client)
    assert pipeline.client() is client
    assert pipeline.client() is client, "the client is cached so usage totals accumulate"


def test_dry_run_skips_the_model(stub_pipeline, tmp_path):
    report = stub_pipeline.run("A-101.dwg", dry_run=True, out_dir=tmp_path)
    assert report.analysis is None
    assert stub_pipeline.stub_client.calls == []
    assert (tmp_path / "payload.json").is_file()
    assert not (tmp_path / "analysis.json").exists()
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["ok"] is True
    assert "error" not in manifest


def test_artifacts_are_written_and_json_safe(stub_pipeline, tmp_path):
    report = stub_pipeline.run("A-101.dwg", out_dir=tmp_path / "nested" / "run")
    target = tmp_path / "nested" / "run"
    assert sorted(path.name for path in target.iterdir()) == [
        "ai_meta.json",
        "analysis.json",
        "analysis.md",
        "cad_model.json",
        "payload.json",
        "run_manifest.json",
    ]
    model = json.loads((target / "cad_model.json").read_text())
    assert model["discipline"]["primary"] == "architectural"
    payload = json.loads((target / "payload.json").read_text())
    assert payload["source"]["backend"] == "ezdxf.document"
    analysis = json.loads((target / "analysis.json").read_text())
    assert analysis["findings"][0]["severity"] == "high"
    meta = json.loads((target / "ai_meta.json").read_text())
    assert meta["usage"]["prompt_tokens"] > 0
    assert (target / "analysis.md").read_text().startswith("# DeepSeek analysis")

    manifest = json.loads((target / "run_manifest.json").read_text())
    assert manifest["artifacts"]["payload"].endswith("payload.json")
    assert manifest["cad2ai_version"]
    assert manifest["payload"]["token_estimate"] == payload["meta"]["token_estimate"]
    # the API's real count re-calibrates the local estimate for the next run
    calibration = manifest["payload"]["tokenizer_calibration"]
    assert calibration == pytest.approx(report.payload_meta["tokenizer_calibration"])
    # the API saw more than the payload alone (the system brief is part of the prompt)
    assert calibration > 1.0
    assert manifest["payload"]["prompt_tokens_actual"] == report.usage["prompt_tokens"]
    assert manifest["payload"]["prompt_tokens_actual"] > report.payload_meta["token_estimate"]
    assert report.artifacts["run_manifest"].endswith("run_manifest.json")


def test_run_manifest_never_leaks_secrets(stub_pipeline, settings, tmp_path):
    report = stub_pipeline.run("A-101.dwg", dry_run=True, out_dir=tmp_path)
    text = (tmp_path / "run_manifest.json").read_text()
    assert "sk-test-0000" not in text
    assert report.payload  # the run still produced a payload
    manifest = json.loads(text)
    assert manifest["config"]["deepseek_api_key"].startswith("***")


def test_report_summary_shape(stub_pipeline):
    report = stub_pipeline.run("A-101.dwg", dry_run=True)
    summary = report.summary
    assert summary["mode"] == "ezdxf"
    assert summary["model"]["entities"] == 27
    assert summary["payload"]["chars"] > 100
    assert summary["usage"] is None
    assert summary["latency_seconds"] >= 0


def test_pipeline_works_without_injected_dependencies(arch_dxf, settings):
    """The real Phase 1/2 chain on a real DXF file (only Phase 3 is stubbed)."""
    client = StubClient()
    pipeline = Pipeline(settings, client_factory=lambda s: client)
    parsed, model, context = pipeline.extract(arch_dxf)
    assert parsed.backend.value == "ezdxf.readfile"
    assert model.summary()["entities"] == 27
    assert context["backend"] == "ezdxf.readfile"
    assert context["attempts"][0]["ok"] is True
    report = pipeline.run(arch_dxf, out_dir=None, task="bom")
    assert json.loads(report.payload)["source"]["file"] == "demo.dxf"
    assert report.analysis == ANALYSIS


def test_extract_helper_returns_parsed_and_model(settings, monkeypatch, tmp_path):
    monkeypatch.setattr("cad2ai.pipeline.Pipeline.load", lambda self, path, **kw: stub_loader(path))
    parsed, model = extract_phases(tmp_path / "x.dxf", settings=settings)
    assert model.summary()["layers"] == 10


def test_payload_override_validation(stub_pipeline):
    limits = stub_pipeline.payload_limits(max_text_items=5)
    assert limits.max_text_items == 5
    with pytest.raises(ConfigError, match="unknown payload option"):
        stub_pipeline.payload_limits(max_textitemz=5)


def test_tiny_token_budget_degrades_the_payload(stub_pipeline, tmp_path):
    stub_pipeline.settings = type(stub_pipeline.settings).from_env(
        environ={"DEEPSEEK_API_KEY": "sk-test-0000", "CAD2AI_MAX_PAYLOAD_TOKENS": "600", "APS_CLIENT_ID": "a", "APS_CLIENT_SECRET": "b", "APS_BUCKET_KEY": "c"}
    )
    report = stub_pipeline.run("A-101.dwg", dry_run=True, out_dir=tmp_path)
    meta = report.payload_meta
    assert meta["degraded"], "the applied degradation steps must be announced"
    assert "budget_exceeded_by" in meta, "an impossible budget must be announced, not silently missed"
    assert meta["token_estimate"] < 4096, "degradation must still shrink the payload a lot"
    assert meta["degraded"]
    assert any("CAD2AI_MAX_PAYLOAD_TOKENS" in warning for warning in report.warnings)
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["payload"]["degraded"]


# ---------------------------------------------------------------------------
# failure handling & fallback
# ---------------------------------------------------------------------------


class StubApsClient:
    def __init__(self):
        self.extracted = []

    def extract(self, path):
        self.extracted.append(Path(path))
        manifest = {"urn": "encoded", "status": "success", "progress": "complete", "derivatives": [{"outputType": "svf2", "status": "success", "children": [{"role": "3d", "name": "Plan", "guid": "g1", "type": "view", "metadata": [{"name": "A-WALL"}]}]}]}
        return ApsExtraction(
            manifest=manifest,
            structure=normalize_manifest(manifest),
            views=[{"guid": "g1", "name": "Plan", "role": "3d"}],
            properties=[{"objectid": "1", "name": "Wall", "layer": "A-WALL"}],
            timings={"upload": 0.5, "translate": 1.0},
            object=OssObject(object_key="k", object_urn="urn:x", encoded_urn="e", bucket_key="cad2ai", size_bytes=10),
        )


def failing_loader(exc):
    def load(path, *, settings=None, **kwargs):
        raise exc

    return load


def aps_settings(settings):
    return type(settings).from_env(
        environ={
            "DEEPSEEK_API_KEY": "sk-test-0000",
            "APS_CLIENT_ID": "cid",
            "APS_CLIENT_SECRET": "secret",
            "APS_BUCKET_KEY": "bucket",
        }
    )


@pytest.mark.parametrize("exc", [DwgConverterNotInstalledError("ODAFileConverter is not installed"), UnsupportedDwgVersionError("AC1015 is below the supported floor")])
def test_local_parse_failure_falls_back_to_aps(settings, exc, tmp_path):
    settings = aps_settings(settings)
    aps = StubApsClient()
    pipeline = Pipeline(
        settings,
        load=failing_loader(exc),
        aps_factory=lambda s: aps,
        client_factory=lambda s: StubClient(),
    )
    drawing = tmp_path / "newer.dwg"
    drawing.write_bytes(b"AC1032" + b"\x00" * 512)
    report = pipeline.run(drawing, task="complexity_metrics")
    assert report.mode == "aps-model-derivative"
    assert aps.extracted == [drawing]
    payload = json.loads(report.payload)
    assert payload["source"]["provenance"] == "autodesk-platform-services"
    assert payload["source"]["lossless"] is False
    assert report.context["fallback"] == "auto"
    assert report.context["attempts"][0]["ok"] is False
    assert report.context["attempts"][0]["error"]["error"] == type(exc).__name__


def test_fallback_can_be_disabled(settings, tmp_path):
    # even with credentials configured, fallback="none" must not upload anything
    pipeline = Pipeline(aps_settings(settings), load=failing_loader(DwgConverterNotInstalledError("no odafc")), aps_factory=lambda s: StubApsClient())
    with pytest.raises(ParseError, match="no odafc"):
        pipeline.run(tmp_path / "a.dwg", fallback="none")


def test_missing_credentials_explain_the_fallback(settings, tmp_path):
    bare = type(settings).from_env(environ={"DEEPSEEK_API_KEY": "sk-test-0000"})
    pipeline = Pipeline(bare, load=failing_loader(DwgConverterNotInstalledError("no odafc")))
    with pytest.raises(ParseError) as excinfo:
        pipeline.run(tmp_path / "a.dwg")
    assert "APS_CLIENT_ID" in excinfo.value.hint


def test_model_errors_are_recorded_in_the_manifest(settings, tmp_path):
    client = StubClient(error=DeepSeekRateLimitError("rate limited", retry_after=3.0, status_code=429))
    pipeline = Pipeline(settings, load=stub_loader, build_model=lambda parsed, settings=None: build_cad_model(parsed.doc), client_factory=lambda s: client)
    with pytest.raises(DeepSeekRateLimitError):
        pipeline.run("A-101.dwg", out_dir=tmp_path)
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["error"] == "DeepSeekRateLimitError"
    assert manifest["error"]["exit_code"] == 6
    assert manifest["error"]["retry_after"] == 3.0
    assert manifest["error"]["details"]["retry_after_seconds"] == 3.0
    # the payload survived even though the analysis did not
    assert (tmp_path / "payload.json").is_file()


def test_unexpected_errors_are_wrapped(settings):
    def boom(path, *, settings=None, **kwargs):
        raise ZeroDivisionError("bug")

    pipeline = Pipeline(settings, load=boom)
    with pytest.raises(ZeroDivisionError):
        pipeline.run("x.dwg")


def test_extract_via_aps_records_context(settings, tmp_path):
    aps = StubApsClient()
    settings = aps_settings(settings)
    pipeline = Pipeline(settings, aps_factory=lambda s: aps)
    drawing = tmp_path / "a.dwg"
    drawing.write_bytes(b"AC1032" + b"\x00" * 512)
    model, context = pipeline.extract_via_aps(drawing)
    assert model.source["backend"] == "aps-model-derivative"
    assert context["views"] == 1
    # the raw manifest rides along in the context, and ``extraction_manifest``
    # finds it under the "aps" key that ``extract()`` installs
    assert context["manifest"]["status"] == "success"
    assert extraction_manifest({"aps": context})["status"] == "success"
    assert extraction_manifest({"no_aps": True}) is None


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------


def test_raw_manifest_artifact_is_written_on_the_aps_path(settings, tmp_path):
    drawing = tmp_path / "a.dwg"
    drawing.write_bytes(b"AC1032" + b"\x00" * 512)
    pipeline = Pipeline(
        aps_settings(settings),
        load=failing_loader(DwgConverterNotInstalledError("no odafc")),
        aps_factory=lambda s: StubApsClient(),
        client_factory=lambda s: StubClient(),
    )
    report = pipeline.run(drawing, out_dir=tmp_path, include_raw_manifest=True, dry_run=True)
    manifest_path = Path(report.artifacts["aps_manifest"])
    assert manifest_path.name == "aps_manifest.json"
    assert json.loads(manifest_path.read_text())["status"] == "success"
    assert extraction_manifest(report.context)["urn"] == "encoded"


def test_render_markdown_is_readable():
    text = render_markdown(ANALYSIS)
    assert text.startswith("# DeepSeek analysis")
    assert "- **summary**: Two load-bearing walls are unannotated." in text
    assert "- **Missing dimension on grid line 3**  `high`" in text
    assert "add the dimension before issue" in text
    assert "0.72" in text
    assert "Every finding cites a payload path" in text


def test_render_markdown_handles_odd_shapes():
    assert "- **a**: yes" in render_markdown({"a": True})
    assert "- **a**: no" in render_markdown({"a": False})
    assert render_markdown({"a": None}).count("**a**") == 0  # empty values are skipped
    assert "- 1" in render_markdown([1])
    assert "DeepSeek analysis" in render_markdown("plain string")
    assert render_markdown({}) .count("- **") == 0


def test_cleanup_dir_keeps_the_requested_files(tmp_path):
    (tmp_path / "keep.txt").write_text("k")
    (tmp_path / "drop.txt").write_text("d")
    removed = cleanup_dir(tmp_path, keep=["keep.txt"])
    assert removed == ["drop.txt"]
    assert (tmp_path / "keep.txt").is_file()
    assert cleanup_dir(tmp_path / "missing") == []
