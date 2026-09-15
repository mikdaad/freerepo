"""Phase 1 fallback: Autodesk Platform Services (OSS + Model Derivative).

Every HTTP call is served by :class:`FakeSession`, so no credentials and no
network are needed.  The routes mirror the real APS OpenAPI (2-legged token,
signed-S3 three-step upload, async translation job, manifest polling, view
metadata/properties).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cad2ai.aps import (
    ApsClient,
    ApsConfig,
    ApsExtraction,
    OssObject,
    cad_model_from_aps,
    decode_urn,
    encode_urn,
    normalize_manifest,
)
from cad2ai.errors import (
    AutodeskAuthError,
    AutodeskError,
    AutodeskNotFound,
    AutodeskRateLimitError,
    AutodeskTranslationError,
    AutodeskTranslationTimeoutError,
    AutodeskUploadError,
    ConfigError,
)
from cad2ai.payload import build_payload

MANIFEST_SUCCESS = {
    "urn": "dXJuOmFkc2sub2JqZWN0",
    "progress": "complete",
    "status": "success",
    "hasThumbnail": "true",
    "derivatives": [
        {
            "outputType": "svf2",
            "progress": "complete",
            "status": "success",
            "hasThumbnail": "true",
            "children": [
                {"role": "2d", "name": "A-101", "mime": "image/png", "status": "success", "urn": "dXJuOmE=.2d"},
                {
                    "role": "3d",
                    "name": "Floor Plan",
                    "mime": "application/json",
                    "status": "success",
                    "guid": "guid-1",
                    "urn": "dXJuOmE=.view-1/geometry",
                    "type": "view",
                },
            ],
        },
        {
            "outputType": "obj",
            "status": "failed",
            "messages": [{"code": "ManifestResolutionError", "reason": "no OBJ exporter for DWG"}],
        },
    ],
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, *, headers=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""
        if content and not payload:
            self.text = content.decode("utf-8", "replace")

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    """Minimal ``requests.Session`` stand-in driven by URL patterns."""

    def __init__(self, *, details=None, manifest_script=None, extra=None, transport_error=None):
        self.calls: list[dict] = []
        self.details = details
        self.manifest_script = list(manifest_script or [MANIFEST_SUCCESS])
        self.extra = extra or {}
        self.transport_error = transport_error
        self.transport = transport_error
        self.token_calls = 0

    def request(self, method, url, *, json=None, data=None, headers=None, params=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "json": json, "data": data, "headers": headers or {}, "params": params, "timeout": timeout}
        )
        if self.transport_error is not None and re.search(r"developer\.api|s3\.example", url):
            # a fresh instance per call: re-raising one exception object across
            # retries builds a self-referential __context__ chain
            raise self.transport() if callable(self.transport_error) else self.transport_error
        for pattern, response in self.extra.items():
            if re.search(pattern, url) and callable(response):
                found = response(method, url, json, headers)
                if found is not None:
                    return found
        if "/authentication/v2/token" in url:
            self.token_calls += 1
            return FakeResponse(200, {"access_token": f"tok-{self.token_calls}", "expires_in": 1800})
        if url.endswith("/oss/v2/buckets") and method == "POST":
            return FakeResponse(201, {"bucketKey": "cad2ai", "policyKey": "transient"})
        if url.endswith("/details"):
            if self.details is None:
                return FakeResponse(404, {"type": "ObjectNotFound", "message": "not found"})
            return FakeResponse(200, self.details)
        if "signeds3upload" in url and method == "GET":
            parts = int((params or {}).get("parts") or 1)
            return FakeResponse(
                200,
                {
                    "uploadKey": "uk-1",
                    "urls": [f"https://s3.example/put?part={index + 1}" for index in range(parts)],
                },
            )
        if "s3.example" in url and method == "PUT":
            return FakeResponse(200, None, headers={"ETag": f'"etag-{len(data or b"")}"'})
        if "signeds3upload" in url and method == "POST":
            return FakeResponse(200, {"uploadKey": "uk-1", "objectIds": ["urn:adsk.objects:os.object:cad2ai/x.dwg"]})
        if "/designdata/job" in url and method == "POST":
            return FakeResponse(202, {"result": "Success", "urn": (json or {}).get("input", {}).get("urn")})
        if re.search(r"/manifest/.+", url):
            return FakeResponse(200, None, content=b'{"geometry": {"curves": 12}}')
        if url.endswith("/manifest"):
            if self.manifest_script:
                payload = self.manifest_script.pop(0)
                if isinstance(payload, FakeResponse):
                    return payload
                return FakeResponse(200, payload)
            return FakeResponse(200, MANIFEST_SUCCESS)
        if url.endswith("/metadata"):
            return FakeResponse(
                200,
                {
                    "data": {
                        "metadata": [
                            {"role": "3d", "name": "Floor Plan", "guid": "guid-1", "association": {"objNames": "LayerNames2"}},
                            {"role": "2d", "name": "A-101", "guid": "guid-2"},
                        ]
                    }
                },
            )
        if url.endswith("/properties"):
            page = int((params or {}).get("page") or 1)
            if page == 1:
                return FakeResponse(
                    200,
                    {
                        "data": {
                            "collection": [
                                {"objectid": "1", "name": "Wall", "layer": "A-WALL", "X": 1.0},
                                {"objectid": "2", "name": "Door", "layer": "A-DOOR", "properties": {"Layer": "A-DOOR"}},
                            ],
                            "pagination": {"page": 1, "total": 2, "next": "page=2"},
                        }
                    },
                )
            if page == 2:
                return FakeResponse(
                    200,
                    {"data": {"collection": [{"objectid": "3", "name": "Column", "layer": "S-COLS"}], "pagination": {"page": 2, "total": 2}}},
                )
            return FakeResponse(200, {"data": {"collection": []}})
        if url.endswith("/hierarchies"):
            return FakeResponse(200, {"data": {"children": [{"name": "Levels", "items": []}]}})
        if method == "DELETE":
            return FakeResponse(204, None)
        return FakeResponse(404, {"type": "NotFound", "message": f"unrouted: {method} {url}"})


@pytest.fixture
def config() -> ApsConfig:
    return ApsConfig(
        client_id="cid",
        client_secret="csecret",
        bucket_key="cad2ai",
        translation_timeout=30.0,
        poll_interval=1.0,
        max_attempts=3,
        min_delay=0.1,
        max_delay=1.0,
    )


@pytest.fixture
def dwg(tmp_path: Path) -> Path:
    path = tmp_path / "A-101.dwg"
    path.write_bytes(b"AC1032" + b"\x00" * 2048)
    return path


def client_for(config, session, *, sleeps=None, now=None):
    return ApsClient(
        config,
        session=session,
        sleep=(sleeps if sleeps is not None else []).append,
        monotonic=now or (lambda: 0.0),
    )


# ---------------------------------------------------------------------------
# urns
# ---------------------------------------------------------------------------


def test_urn_encoding_is_url_safe_and_unpadded():
    original = "urn:adsk.objects:os.object:my-bucket/weird name+file.dwg"
    encoded = encode_urn(original)
    assert "=" not in encoded and "+" not in encoded and "/" not in encoded
    assert decode_urn(encoded) == original


def test_decode_urn_accepts_already_encoded_input():
    assert decode_urn("urn:adsk.objects:os.object:b/k") == "urn:adsk.objects:os.object:b/k"


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


def test_credentials_are_required():
    with pytest.raises(ConfigError, match="APS client credentials"):
        ApsClient(ApsConfig(client_id="", client_secret=""))


def test_token_is_cached_across_calls(config, dwg):
    session = FakeSession()
    client = client_for(config, session)
    first = client.get_token()
    client.upload_file(dwg)
    client.get_manifest("urn")
    assert first == "tok-1"
    assert session.token_calls == 1, "one 2-legged token per process until it expires"


def test_expired_token_is_refreshed(config, dwg):
    session = FakeSession()
    clock = {"now": 0.0}
    client = client_for(config, session, now=lambda: clock["now"])
    assert client.get_token() == "tok-1"
    clock["now"] = 4000.0  # beyond expires_in - 30
    assert client.get_token() == "tok-2"
    assert session.token_calls == 2


def test_token_endpoint_retries_without_recursion(config):
    # A transient failure at the token endpoint must retry the token call, not
    # re-enter get_token() from inside _request (that used to recurse forever).
    session = FakeSession(transport_error=lambda: OSError("dns failure"))
    client = client_for(ApsConfig(client_id="a", client_secret="b", bucket_key="k", max_attempts=3), session)
    with pytest.raises(AutodeskError):
        client.get_token()
    token_calls = [call for call in session.calls if "/authentication/v2/token" in call["url"]]
    assert len(token_calls) == 3


def test_auth_failure_is_typed(config):
    session = FakeSession(extra={r"/manifest": lambda *a: FakeResponse(401, {"developerMessage": "token expired"})})
    client = client_for(config, session)
    with pytest.raises(AutodeskAuthError) as excinfo:
        client.get_manifest("urn")
    assert excinfo.value.status_code == 401
    assert excinfo.value.exit_code == 5


def test_rate_limit_is_retried_then_propagates(config):
    sleeps: list[float] = []
    calls = {"n": 0}

    def rate_limited(method, url, body, headers):
        calls["n"] += 1
        if url.endswith("/manifest") and calls["n"] <= 2:
            return FakeResponse(429, {"message": "throttled"}, headers={"Retry-After": "4"})
        return None

    session = FakeSession(extra={r"/manifest": rate_limited})
    client = ApsClient(config, session=session, sleep=sleeps.append, monotonic=lambda: 0.0)
    assert client.get_manifest("urn")["status"] == "success"
    assert sleeps == [4.0, 4.0], "Retry-After must be honoured on each attempt"


def test_persistent_rate_limit_becomes_typed_error(config):
    session = FakeSession(extra={r"/manifest": lambda *a: FakeResponse(429, {"message": "throttled"}, headers={"Retry-After": "2"})})
    client = client_for(config, session)
    with pytest.raises(AutodeskRateLimitError) as excinfo:
        client.get_manifest("urn")
    assert excinfo.value.retry_after == 2.0
    assert excinfo.value.retryable is True


def test_missing_manifest_is_not_found(config):
    session = FakeSession(extra={r"/manifest": lambda *a: FakeResponse(404, {"type": "NotFound", "message": "no such urn"})})
    client = client_for(config, session)
    with pytest.raises(AutodeskNotFound) as excinfo:
        client.get_manifest("bad-urn")
    assert excinfo.value.status_code == 404


def test_transport_error_is_wrapped(config):
    session = FakeSession(transport_error=lambda: OSError("dns failure"))
    client = client_for(config, session)
    with pytest.raises(AutodeskError, match="failed after 3 attempt"):
        client.get_manifest("urn")


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------


def test_upload_uses_signed_s3_three_step_flow(config, dwg):
    session = FakeSession()
    client = client_for(config, session)
    uploaded = client.upload_file(dwg)
    sequence = [
        call["method"]
        + " "
        + (
            "token"
            if "token" in call["url"]
            else "buckets"
            if call["url"].endswith("/buckets")
            else "details"
            if call["url"].endswith("/details")
            else "sign"
            if "signeds3upload" in call["url"]
            else "s3"
            if "s3.example" in call["url"]
            else call["url"]
        )
        for call in session.calls
    ]
    assert sequence == ["POST token", "POST buckets", "GET details", "GET sign", "PUT s3", "POST sign"]
    complete = [call for call in session.calls if call["method"] == "POST" and call["url"].endswith("signeds3upload")][0]
    assert complete["json"]["uploadKey"] == "uk-1"
    assert complete["json"]["eTags"] == ["etag-2054"]
    assert complete["json"]["size"] == 2054
    put = [call for call in session.calls if call["method"] == "PUT"][0]
    assert put["data"] == b"AC1032" + b"\x00" * 2048
    assert put["headers"]["Content-Type"] == "application/octet-stream"
    assert uploaded.reused is False
    assert uploaded.size_bytes == 2054
    assert uploaded.object_key.startswith("A-101-") and uploaded.object_key.endswith(".dwg")
    assert uploaded.object_urn == f"urn:adsk.objects:os.object:cad2ai/{uploaded.object_key}"
    assert decode_urn(uploaded.encoded_urn) == uploaded.object_urn


def test_upload_is_skipped_when_the_object_already_matches(config, dwg):
    session = FakeSession(details={"size": 2054, "lastModified": "now"})
    client = client_for(config, session)
    uploaded = client.upload_file(dwg)
    assert uploaded.reused is True
    assert [call["method"] for call in session.calls if call["method"] == "PUT"] == []


def test_force_reupload_ignores_existing_object(config, dwg):
    session = FakeSession(details={"size": 2054})
    client = client_for(config, session)
    uploaded = client.upload_file(dwg, force=True)
    assert uploaded.reused is False
    assert any(call["method"] == "PUT" for call in session.calls)


def test_custom_object_key_is_used(config, dwg):
    session = FakeSession()
    client = client_for(config, session)
    uploaded = client.upload_file(dwg, object_key="projects/a101.dwg")
    assert uploaded.object_key == "projects/a101.dwg"
    assert "projects%2Fa101.dwg" in session.calls[-1]["url"] or "projects/a101.dwg" in session.calls[-1]["url"]


def test_missing_input_file_is_an_upload_error(config, tmp_path):
    client = client_for(config, FakeSession())
    with pytest.raises(AutodeskUploadError, match="input file not found"):
        client.upload_file(tmp_path / "nope.dwg")


def test_multipart_upload_uses_one_signed_url_per_part(config, tmp_path):
    big = tmp_path / "big.dwg"
    payload = b"AC1032" + b"\x00" * 1_500_000
    big.write_bytes(payload)
    session = FakeSession()
    client = client_for(ApsConfig(client_id="a", client_secret="b", bucket_key="cad2ai", part_size_mb=1), session)
    uploaded = client.upload_file(big)
    puts = [call for call in session.calls if call["method"] == "PUT"]
    assert len(puts) == 2
    assert [len(call["data"]) for call in puts] == [1048576, len(payload) - 1048576]
    signed = [call for call in session.calls if call["method"] == "GET" and "signeds3upload" in call["url"]][0]
    assert signed["params"]["parts"] == 2
    complete = [call for call in session.calls if call["method"] == "POST" and call["url"].endswith("signeds3upload")][0]
    assert len(complete["json"]["eTags"]) == 2
    assert uploaded.size_bytes == len(payload)


def test_bucket_is_created_once(config, dwg):
    session = FakeSession()
    client = client_for(config, session)
    client.upload_file(dwg)
    client.upload_file(dwg, object_key="second.dwg")
    creates = [call for call in session.calls if call["method"] == "POST" and call["url"].endswith("/oss/v2/buckets")]
    assert len(creates) == 1


# ---------------------------------------------------------------------------
# translation
# ---------------------------------------------------------------------------


def test_translation_job_body(config):
    session = FakeSession()
    client = client_for(config, session)
    client.start_translation("ENC-URN")
    job = [call for call in session.calls if call["url"].endswith("/designdata/job")][0]
    assert job["json"] == {
        "input": {"urn": "ENC-URN"},
        "output": {"formats": [{"type": "svf2", "views": ["2d", "3d"]}]},
    }
    assert "x-ads-force" not in job["headers"]


def test_force_translation_sets_the_ads_header(config):
    session = FakeSession()
    client = client_for(config, session)
    client.start_translation("ENC", force=True, output_format="svf", views=["2d"])
    job = [call for call in session.calls if call["url"].endswith("/designdata/job")][0]
    assert job["headers"]["x-ads-force"] == "true"
    assert job["json"]["output"]["formats"] == [{"type": "svf", "views": ["2d"]}]


def test_unsupported_output_format_is_refused(config):
    client = client_for(config, FakeSession())
    with pytest.raises(AutodeskError, match="unsupported APS output format"):
        client.start_translation("urn", output_format="pdf")


def test_manifest_polling_waits_for_success(config):
    sleeps: list[float] = []
    session = FakeSession(manifest_script=[{"progress": "0%", "status": "pending"}, {"status": "inprogress", "progress": "40%"}, MANIFEST_SUCCESS])
    clock = {"t": 0.0}
    client = ApsClient(config, session=session, sleep=lambda s: (sleeps.append(s), clock.__setitem__("t", clock["t"] + s)), monotonic=lambda: clock["t"])
    manifest = client.wait_for_manifest("ENC")
    assert manifest["status"] == "success"
    assert sleeps == [1.0, 1.35], "polling backs off by poll_backoff"
    assert len(sleeps) == 2


def test_failed_translation_reports_the_manifest_messages(config):
    failed = {"status": "failed", "derivatives": [{"outputType": "svf2", "status": "failed", "messages": [{"reason": "the DWG is password protected"}]}]}
    session = FakeSession(manifest_script=[failed])
    client = client_for(config, session)
    with pytest.raises(AutodeskTranslationError) as excinfo:
        client.wait_for_manifest("ENC")
    assert "password protected" in excinfo.value.message
    assert "trueView" in excinfo.value.hint


def test_translation_timeout_is_bounded(config):
    session = FakeSession(manifest_script=[{"status": "pending", "progress": "1%"}] * 20)
    clock = {"t": 0.0}
    client = ApsClient(
        ApsConfig(client_id="a", client_secret="b", bucket_key="k", translation_timeout=10.0, poll_interval=1.0, poll_backoff=1.0),
        session=session,
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        monotonic=lambda: clock["t"],
    )
    with pytest.raises(AutodeskTranslationTimeoutError) as excinfo:
        client.wait_for_manifest("ENC")
    assert "within 10s" in excinfo.value.message
    assert "APS_TRANSLATION_TIMEOUT" in excinfo.value.hint
    assert excinfo.value.details["polls"] >= 2


# ---------------------------------------------------------------------------
# metadata extraction
# ---------------------------------------------------------------------------


def test_views_and_properties_are_fetched(config):
    session = FakeSession()
    client = client_for(config, session)
    views = client.list_model_views("ENC")
    assert {view["guid"] for view in views} == {"guid-1", "guid-2"}
    assert {view["role"] for view in views} == {"3d", "2d"}
    records = client.fetch_view_properties("ENC", "guid-1")
    assert [record["name"] for record in records] == ["Wall", "Door", "Column"]
    assert {record["layer"] for record in records} == {"A-WALL", "A-DOOR", "S-COLS"}


def test_property_pages_stop_on_error(config):
    seen = {"pages": 0}

    def boom(method, url, body, headers):
        if not url.endswith("/properties"):
            return None
        seen["pages"] += 1
        if seen["pages"] >= 2:
            return FakeResponse(500, {"message": "kaboom"})
        return None

    session = FakeSession(extra={r"/properties": boom})
    client = client_for(config, session)
    with pytest.raises(AutodeskError, match="kaboom|500"):
        client.fetch_view_properties("ENC", "guid-1")
    assert seen["pages"] >= 2

    # ...but a whole extract() degrades gracefully instead of failing the run
    extraction = client.extract(_dwg_for(session))
    assert any("unavailable" in warning for warning in extraction.warnings)


def _dwg_for(session):
    import tempfile
    from pathlib import Path as _P

    directory = _P(tempfile.mkdtemp(prefix="cad2ai-aps-"))
    path = directory / "A-101.dwg"
    path.write_bytes(b"AC1032" + b"\x00" * 2048)
    return path


def test_hierarchy_fetch(config):
    session = FakeSession()
    client = client_for(config, session)
    assert client.fetch_hierarchy("ENC", "guid-1")["data"]["children"][0]["name"] == "Levels"


def test_download_derivative_returns_bytes(config):
    client = client_for(config, FakeSession())
    blob = client.download_derivative("ENC", "dXJuOmE=.view-1/geometry")
    assert json.loads(blob)["geometry"]["curves"] == 12


# ---------------------------------------------------------------------------
# manifest normalisation + model bridge
# ---------------------------------------------------------------------------


def test_normalize_manifest_extracts_structural_facts():
    structure = normalize_manifest(MANIFEST_SUCCESS)
    assert structure["status"] == "success"
    assert structure["urn"] == "dXJuOmFkc2sub2JqZWN0"
    assert {view["name"] for view in structure["views"]} == {"A-101", "Floor Plan"}
    assert {item["output_type"] for item in structure["derivative_formats"]} == {"svf2", "obj"}
    assert structure["counts"]["views"] == 2


def test_normalize_manifest_tolerates_junk():
    for junk in (None, {}, {"derivatives": "not-a-list"}, {"derivatives": [None, 7]}):
        structure = normalize_manifest(junk)
        assert structure["views"] == []


def test_layer_names_are_recovered_from_children():
    manifest = {
        "status": "success",
        "derivatives": [
            {
                "outputType": "svf2",
                "children": [
                    {"role": "3d", "type": "view", "guid": "g", "metadata": [{"name": "A-WALL"}, {"name": "S-COLS"}]},
                ],
            }
        ],
    }
    assert sorted(item["name"] for item in normalize_manifest(manifest)["layers"]) == ["A-WALL", "S-COLS"]


def test_extract_returns_a_full_extraction(config, dwg):
    session = FakeSession()
    client = client_for(config, session)
    extraction = client.extract(dwg)
    assert isinstance(extraction, ApsExtraction)
    assert extraction.manifest["status"] == "success"
    assert extraction.object.object_key.startswith("A-101-")
    assert extraction.structure["views"]
    assert [record["name"] for record in extraction.properties] == ["Wall", "Door", "Column"]
    assert "translate" in extraction.timings and extraction.timings["upload"] >= 0
    assert extraction.derivatives  # the JSON view fragment was downloaded

    blob = extraction.as_dict()
    assert blob["source"] == "autodesk-platform-services"
    assert blob["object"]["object_key"].startswith("A-101-")
    assert blob["object"]["bucket"] == "cad2ai"
    assert "structure" in blob and "manifest" in blob
    assert blob["timings_ms"]["upload"] >= 0


def test_extract_can_skip_waiting(config, dwg):
    session = FakeSession()
    client = client_for(config, session)
    extraction = client.extract(dwg, wait=False)
    assert extraction.manifest == {}
    assert extraction.views == []
    assert not any(call["url"].endswith("/manifest") for call in session.calls)


def test_delete_after_extract(config, dwg):
    session = FakeSession()
    client = client_for(
        ApsConfig(client_id="a", client_secret="b", bucket_key="cad2ai", delete_after_extract=True, translation_timeout=30.0, poll_interval=1.0),
        session,
    )
    client.extract(dwg)
    assert any(call["method"] == "DELETE" for call in session.calls)


def test_write_json_artifact(config, dwg, tmp_path):
    client = client_for(config, FakeSession())
    extraction = client.extract(dwg)
    target = extraction.write_json(tmp_path / "nested" / "aps.json")
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["structure"]["status"] == "success"
    assert saved["manifest"]["urn"]


# ---------------------------------------------------------------------------
# CadModel bridge
# ---------------------------------------------------------------------------


def test_cad_model_from_aps_is_marked_lossy(config, dwg):
    client = client_for(config, FakeSession())
    extraction = client.extract(dwg)
    model = cad_model_from_aps(extraction, source_path=dwg, dwg_version={"sentinel": "AC1032", "release": "R2018"})
    data = model.as_dict()
    assert data["source"]["lossless"] is False
    assert data["source"]["provenance"] == "autodesk-platform-services"
    assert data["source"]["backend"] == "aps-model-derivative"
    assert "structural metadata only" in data["warnings"][0]
    assert data["document"]["dwg"] == {"sentinel": "AC1032", "release": "R2018"}
    # SVF2 property records carry no DXF entity types -> the histogram says so
    assert data["entities"]["by_type"] == {"unclassified": 3}
    assert data["entities"]["total"] == 3
    layer_names = {layer["name"] for layer in data["layers"]}
    assert {"A-WALL", "A-DOOR", "S-COLS"} == layer_names - {""} or {"A-WALL", "A-DOOR", "S-COLS"} <= layer_names
    assert data["extraction"]["backend"] == "aps"
    assert data["extraction"]["aps"]["urn"] == "dXJuOmFkc2sub2JqZWN0"
    assert model.discipline["primary"] in {"architectural", "mixed", "structural"}


def test_aps_model_feeds_the_payload_builder(config, dwg):
    client = client_for(config, FakeSession())
    model = cad_model_from_aps(client.extract(dwg), source_path=dwg)
    built = build_payload(model)
    data = json.loads(built.json)
    assert data["source"]["lossless"] is False
    assert data["source"]["provenance"] == "autodesk-platform-services"
    assert "layers" in data
    assert "units" not in data["document"]  # unknown units are dropped, never invented
    assert built.token_estimate > 0


def test_progress_events_are_emitted(config, dwg):
    events: list[tuple[str, dict]] = []
    session = FakeSession()
    client = ApsClient(config, session=session, sleep=lambda seconds: None, monotonic=lambda: 0.0, progress=lambda name, payload: events.append((name, payload)))
    client.extract(dwg)
    names = [name for name, _ in events]
    assert "upload_started" in names and "upload_finished" in names
    assert "translation_submitted" in names and "translation_status" in names
    assert "extracted" in names


def test_broken_progress_callback_does_not_break_extraction(config, dwg):
    def bad(name, payload):
        raise RuntimeError("callback exploded")

    client = ApsClient(config, session=FakeSession(), sleep=lambda seconds: None, monotonic=lambda: 0.0, progress=bad)
    assert client.extract(dwg).manifest["status"] == "success"


def test_config_from_settings(settings):
    configured = settings.__class__.from_env(
        environ={"APS_CLIENT_ID": "id1", "APS_CLIENT_SECRET": "sec1", "APS_BUCKET_KEY": "bucket1", "APS_OUTPUT_FORMAT": "svf"}
    )
    config = ApsConfig.from_settings(configured)
    assert (config.client_id, config.client_secret, config.bucket_key) == ("id1", "sec1", "bucket1")
    assert config.output_format == "svf"
    assert config.part_size == 8 * 1024 * 1024
    with pytest.raises(ConfigError, match="APS_CLIENT_ID"):
        ApsConfig.from_settings(settings.__class__.from_env(environ={}))


def test_oss_object_dict_is_artifact_safe():
    obj = OssObject(object_key="k", object_urn="urn:x", encoded_urn="urnx", bucket_key="b", size_bytes=3)
    assert obj.as_dict()["object_key"] == "k"
    assert obj.as_dict()["reused"] is False
