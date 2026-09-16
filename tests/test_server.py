"""HTTP-level tests for ``server.py`` (FastAPI).

The pipeline itself is covered elsewhere, so these tests inject a fake *worker*:
what is under test is the service contract -- status codes, cleanup, limits,
concurrency, the JSON envelope shape -- not CAD parsing or DeepSeek.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import server as api
from cad2ai.config import Settings
from cad2ai.errors import (
    Cad2AiError,
    CorruptCadFileError,
    DeepSeekRateLimitError,
    MissingEnvironmentVariableError,
    UnsupportedDwgVersionError,
)

ANALYSIS = {
    "drawing": "wall-plan.dxf",
    "discipline": {"assigned": "architectural", "confirmed": False, "comment": "mixed A-/M- layers"},
    "confidence": 0.74,
    "findings": [
        {
            "id": "F1",
            "bucket": "data_quality",
            "severity": "high",
            "title": "Overridden dimension text",
            "detail": "3 dimensions carry typed text",
            "evidence": ["dimensions[4].text=12000 TYP"],
            "recommendation": "Remove the overrides",
        }
    ],
    "release_recommendation": "hold",
    "effort_hours_estimate": 6,
}


def make_client(
    tmp_path: Path,
    worker: Callable[[api.ExtractionRequest], dict[str, Any]] | None = None,
    *,
    max_upload_mb: float = 1.0,
    timeout_s: float = 30.0,
    concurrency: int = 4,
    **cfg: Any,
) -> TestClient:
    config = api.ApiConfig(
        max_upload_mb=max_upload_mb,
        timeout_s=timeout_s,
        concurrency=concurrency,
        cors_origins=("http://localhost:3000",),
        artifact_root=tmp_path / "runs",
        **cfg,
    )
    app = api.create_app(
        worker=worker or (lambda request: {"analysis": dict(ANALYSIS)}),
        config=config,
        settings=Settings.from_env(environ={}),
    )
    return TestClient(app, raise_server_exceptions=False)


def post_file(
    client: TestClient,
    name: str = "wall-plan.dxf",
    content: bytes = b"AC1032 dummy dxf",
    form: dict[str, Any] | None = None,
):
    return client.post(
        "/api/analyze",
        files={"file": (name, content, "application/octet-stream")},
        data=form or {},
    )


def record_worker(bodies: list[api.ExtractionRequest], result: dict[str, Any] | None = None):
    """Fake extraction that records the request (and the staged bytes, which only
    exist while the worker runs) and proves the temp dir is dropped afterwards."""

    def worker(request: api.ExtractionRequest) -> dict[str, Any]:
        request.notes["bytes"] = request.input_path.read_bytes()
        request.notes["marker"] = request.input_path.with_suffix(".marker")
        request.notes["parent"] = request.input_path.parent
        request.notes["marker"].write_text("seen", encoding="utf-8")
        bodies.append(request)
        return dict(result or {"analysis": dict(ANALYSIS)})

    return worker


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def test_health_advertises_capabilities_without_touching_any_api(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["limits"]["allowed_suffixes"] == [".dwg", ".dxf"]
    assert "sheet_review" in body["tasks"]
    assert body["readiness"]["accepts_dxf"] is True
    # no key/config in this environment: reported, never guessed
    assert body["deepseek"]["key_present"] is False
    assert body["readiness"]["full_pipeline"] is False
    assert body["autodesk"]["configured"] is False
    assert "ODA_CLIENT_ID" not in str(body)
    assert set(body["backends"]) >= {"platform", "oda_installed", "ezdxf_version"}


def test_openapi_documents_the_upload_contract(tmp_path):
    client = make_client(tmp_path)
    schema = client.get("/openapi.json").json()
    assert "/api/analyze" in schema["paths"]
    assert "/api/health" in schema["paths"]


def test_cors_allows_the_dashboard_origin_only(tmp_path):
    client = make_client(tmp_path)
    preflight = client.options(
        "/api/analyze",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code in (200, 204)
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"

    other = client.options(
        "/api/analyze",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert other.headers.get("access-control-allow-origin") is None


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------


def test_analyze_returns_analysis_and_cleans_up_the_upload(tmp_path):
    seen: list[api.ExtractionRequest] = []
    client = make_client(tmp_path, record_worker(seen))

    response = post_file(client)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["analysis"]["release_recommendation"] == "hold"
    assert body["run_id"]
    assert body["input_retained"] is False
    assert body["artifact_dir"] is None
    assert body["elapsed_s"] >= 0

    (request,) = seen
    assert request.task == "sheet_review"
    assert request.filename == "wall-plan.dxf"
    assert request.notes["bytes"].startswith(b"AC1032")
    # the marker proves the worker really saw the staged file; its parent must be gone
    assert not request.notes["marker"].exists(), "the temporary directory must be removed after processing"
    assert not Path(request.notes["parent"]).exists()


def test_filename_survives_sanitisation_for_the_report_header(tmp_path):
    seen: list[api.ExtractionRequest] = []
    client = make_client(tmp_path, record_worker(seen))
    response = client.post(
        "/api/analyze",
        files={"file": ("..\\..\\Bad Name;| A-101.dxf", b"AC1032", "application/octet-stream")},
    )
    assert response.status_code == 200
    name = seen[0].filename
    assert ".." not in name and ";" not in name and "|" not in name
    assert name.endswith(".dxf")
    assert response.json()["filename"] == name


def test_form_fields_reach_the_pipeline_request(tmp_path):
    seen: list[api.ExtractionRequest] = []
    client = make_client(tmp_path, record_worker(seen))
    response = client.post(
        "/api/analyze",
        files={"file": ("sheet.dxf", b"AC1032", "application/octet-stream")},
        data={"task": "bom", "brief": "permit set", "dry_run": "1", "include_markdown": "0"},
    )
    assert response.status_code == 200
    (request,) = seen
    assert request.task == "bom"
    assert request.brief == "permit set"
    assert request.dry_run is True
    assert request.include_markdown is False
    assert response.json()["analysis"]["release_recommendation"] == "hold"


def test_non_serialisable_model_output_still_returns_valid_json(tmp_path):
    def worker(request):
        return {"analysis": ANALYSIS, "extras": {"paths": {Path("a.dxf")}, "when": time.time()}}

    client = make_client(tmp_path, worker)
    response = post_file(client)
    assert response.status_code == 200
    assert json.loads(response.text)["analysis"]["drawing"] == "wall-plan.dxf"


# ---------------------------------------------------------------------------
# rejected before the pipeline is touched
# ---------------------------------------------------------------------------


def test_missing_file_field_is_400(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/analyze", data={"task": "sheet_review"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file_missing"


def test_wrong_extension_is_415(tmp_path):
    client = make_client(tmp_path)
    response = post_file(client, name="notes.txt", content=b"just a memo")
    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "unsupported_file_type"
    assert "DWG 2018" in error["hint"]
    # the caller is told the extension they actually sent, not the sanitised name
    assert ".txt" in error["message"]
    assert error["details"]["filename"] == "notes.txt"
    assert error["details"]["accepted"] == [".dwg", ".dxf"]


def test_dwg_without_the_right_magic_is_still_tried(tmp_path):
    """The server does not sniff formats -- the pipeline owns that judgement."""
    seen: list[api.ExtractionRequest] = []
    client = make_client(tmp_path, record_worker(seen))
    response = post_file(client, name="suspect.dxf", content=b"not a cad file at all")
    assert response.status_code == 200
    assert len(seen) == 1


def test_empty_upload_is_400(tmp_path):
    client = make_client(tmp_path)
    response = post_file(client, content=b"")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_oversize_upload_is_413_and_never_reaches_the_worker(tmp_path):
    calls: list[api.ExtractionRequest] = []

    def worker(request):
        calls.append(request)
        return {"analysis": ANALYSIS}

    client = make_client(tmp_path, worker, max_upload_mb=0.002)  # ~2 kB
    response = post_file(client, content=b"x" * 40_000)
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert error["details"]["limit_bytes"] == 2097
    assert calls == []


@pytest.mark.parametrize("field,value,code", [("task", "make_it_pretty", "unknown_task"), ("fallback", "magic", "bad_fallback")])
def test_bad_form_options_are_422(tmp_path, field, value, code):
    client = make_client(tmp_path)
    response = client.post(
        "/api/analyze",
        files={"file": ("a.dxf", b"AC1032", "application/octet-stream")},
        data={field: value},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == code
    if code == "unknown_task":
        assert "sheet_review" in body["error"]["known_tasks"]


# ---------------------------------------------------------------------------
# typed pipeline errors -> meaningful HTTP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,expected_status,expected_code",
    [
        (MissingEnvironmentVariableError("DEEPSEEK_API_KEY"), 503, None),
        (UnsupportedDwgVersionError("AC1009 too old", sentinel="AC1009"), 415, None),
        (CorruptCadFileError("broken", hint="re-export"), 422, None),
        (DeepSeekRateLimitError("rate limited", retry_after=7.5), 429, None),
        (Cad2AiError("nope"), 500, None),
    ],
)
def test_error_mapping(tmp_path, exc, expected_status, expected_code):
    def worker(request):
        raise exc

    client = make_client(tmp_path, worker)
    response = post_file(client)
    assert response.status_code == expected_status
    body = response.json()
    error = body["error"]
    assert error["message"] == exc.message
    assert error["status"] == expected_status
    assert error["exit_code"] == exc.exit_code
    if expected_code:
        assert error["code"] == expected_code
    if expected_status == 429:
        assert int(response.headers["retry-after"]) >= 1


def test_unexpected_worker_crash_becomes_a_json_envelope(tmp_path):
    def worker(request):
        raise ValueError("boom in a dependency")

    client = make_client(tmp_path, worker)
    response = post_file(client)
    assert response.status_code == 500
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "internal_error"
    assert "boom in a dependency" in body["error"]["message"]
    assert response.headers["content-type"].startswith("application/json")


def test_timeout_is_504(tmp_path):
    def worker(request):
        time.sleep(1.5)
        return {"analysis": ANALYSIS}

    client = make_client(tmp_path, worker, timeout_s=0.2)
    response = post_file(client)
    assert response.status_code == 504
    error = response.json()["error"]
    assert error["code"] == "extraction_timeout"
    assert "CAD2AI_API_TIMEOUT_S" in error["hint"]


def test_gate_overload_answers_429_instead_of_queuing(tmp_path):
    release = threading.Event()
    done = threading.Event()

    def worker(request):
        if not release.wait(timeout=5):  # first caller parks here
            return {"analysis": ANALYSIS}
        done.set()
        return {"analysis": ANALYSIS}

    client = make_client(tmp_path, worker, concurrency=1)
    results: dict[str, int] = {}

    first = threading.Thread(target=lambda: results.update(one=post_file(client).status_code), daemon=True)
    first.start()
    time.sleep(0.35)  # let it take the permit
    second = post_file(client)
    results["two"] = second.status_code
    release.set()
    first.join(timeout=8)

    assert second.status_code == 429
    error = second.json()["error"]
    assert error["code"] == "busy"
    assert error["details"]["limit"] == 1
    assert results["one"] == 200
    assert second.headers.get("retry-after")


# ---------------------------------------------------------------------------
# kept artifacts
# ---------------------------------------------------------------------------


def test_keep_artifacts_writes_a_fetchable_run(tmp_path):
    def worker(request: api.ExtractionRequest) -> dict[str, Any]:
        assert request.artifact_dir is not None
        request.artifact_dir.mkdir(parents=True, exist_ok=True)
        (request.artifact_dir / "analysis.json").write_text(json.dumps(ANALYSIS), encoding="utf-8")
        # The pipeline names the markdown ``analysis.md``; the API serves it as ``report.md``.
        (request.artifact_dir / "analysis.md").write_text("# report\n- finding", encoding="utf-8")
        return {"analysis": ANALYSIS, "markdown": "# report\n- finding"}

    client = make_client(tmp_path, worker)
    response = post_file(client, form={"keep": "1"})
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert Path(body["artifact_dir"]).name == run_id

    fetched = client.get(f"/api/runs/{run_id}/analysis.json")
    assert fetched.status_code == 200
    assert fetched.json()["drawing"] == "wall-plan.dxf"

    markdown = client.get(f"/api/runs/{run_id}/report.md")
    assert markdown.status_code == 200
    assert markdown.text.startswith("# report")

    assert client.get(f"/api/runs/{run_id}/secrets.env").status_code == 404
    assert client.get(f"/api/runs/{run_id}/missing.json").status_code == 404


def test_keep_by_default_env_style_config(tmp_path):
    client = make_client(tmp_path, keep_by_default=True)
    response = post_file(client)
    assert response.status_code == 200
    assert response.json()["artifact_dir"] is not None


@pytest.mark.parametrize("run_id", ["..", "..%2F..", "a" * 80, "bad/id"])
def test_run_id_path_guard(tmp_path, run_id):
    client = make_client(tmp_path)
    response = client.get(f"/api/runs/{run_id}/analysis.json")
    assert response.status_code in (400, 404)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def test_safe_filename_rules():
    assert api._safe_filename("A-101 Floor Plan.dwg") == "A-101 Floor Plan.dwg"
    assert api._safe_filename("/etc/passwd") == "passwd"
    assert api._safe_filename("..\\..\\x.dxf") == "x.dxf"
    assert api._safe_filename("weird|name;.txt") == "weird_name_"  # unsupported suffix is dropped
    assert api._safe_filename("") == "drawing"
    assert api._safe_filename("x" * 300 + ".dxf").startswith("xxx")
    assert len(api._safe_filename("x" * 300 + ".dxf")) <= 76


def test_as_int_tolerates_form_strings():
    assert api._as_int("1") == 1
    assert api._as_int(True) == 1
    assert api._as_int("") == 0
    assert api._as_int(None) == 0
    assert api._as_int("nope") == 0


def test_config_from_env_reads_the_documented_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CAD2AI_API_MAX_UPLOAD_MB", "12")
    monkeypatch.setenv("CAD2AI_API_TIMEOUT_S", "45")
    monkeypatch.setenv("CAD2AI_API_CONCURRENCY", "3")
    monkeypatch.setenv("CAD2AI_CORS_ORIGINS", "http://localhost:3000, https://review.example")
    monkeypatch.setenv("CAD2AI_API_KEEP", "1")
    monkeypatch.setenv("CAD2AI_API_ARTIFACT_DIR", str(tmp_path / "kept"))
    config = api.ApiConfig.from_env()
    assert config.max_upload_mb == 12.0
    assert config.timeout_s == 45.0
    assert config.concurrency == 3
    assert config.cors_origins == ("http://localhost:3000", "https://review.example")
    assert config.keep_by_default is True
    assert config.artifact_root == tmp_path / "kept"


def test_config_rejects_nonsense_values(monkeypatch):
    monkeypatch.setenv("CAD2AI_API_TIMEOUT_S", "0")
    with pytest.raises(Cad2AiError, match="greater than 0"):
        api.ApiConfig.from_env()
    monkeypatch.setenv("CAD2AI_API_TIMEOUT_S", "soon")
    with pytest.raises(Cad2AiError, match="must be a number"):
        api.ApiConfig.from_env()
