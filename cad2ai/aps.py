"""Phase 1 (fallback) -- Autodesk Platform Services Model Derivative extraction.

When the ODA File Converter is unavailable (headless CI, macOS without a
converter build, a DWG newer than the local converter, or a locked-down
workstation), the drawing can still be analysed by letting Autodesk do the
parsing:

    1. 2-legged OAuth 2.0 token                      POST /authentication/v2/token
    2. ensure an OSS bucket                           POST /oss/v2/buckets
    3. upload the DWG via signed S3 URLs          GET/PUT/POST .../signeds3upload
    4. request derivatives (SVF2 keeps 2D sheets)     POST /modelderivative/v2/designdata/job
    5. poll the manifest                    GET /modelderivative/v2/designdata/{urn}/manifest
    6. download the JSON manifest + model/view/props   .../manifest/{derivativeUrn}
                                                             /metadata, /metadata/{guid}[/properties|/hierarchies]
    7. normalise everything into a CadModel (Phase 2)

Notes on correctness:
* Model Derivative URNs are *URL-safe base64, no padding* of the
  ``urn:adsk.objects:os.object:{bucket}/{object}`` string.
* The ``PUT /oss/v2/.../objects/{key}`` direct-upload endpoint is retired -- the
  signed-S3 three-step flow below is the supported path.
* Translation is asynchronous: ``pending``/``inprogress`` keep polling,
  ``success`` stops, ``failed``/``timeout`` raise with the per-derivative
  messages attached.
* Data may leave the machine when this module is used.  ``ApsConfig`` documents
  the region/retention knobs, and ``cleanup_bucket`` is available because the
  default ``transient`` policy keeps objects for 30 days.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from datetime import datetime, timezone
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cad2ai.errors import (
    AutodeskAuthError,
    AutodeskError,
    AutodeskNotFound,
    AutodeskRateLimitError,
    AutodeskTranslationError,
    AutodeskTranslationTimeoutError,
    AutodeskUploadError,
    ConfigError,
    UnsupportedDwgVersionError,
)

logger = logging.getLogger("cad2ai.aps")

__all__ = [
    "ApsClient",
    "ApsConfig",
    "ApsExtraction",
    "OssObject",
    "encode_urn",
    "decode_urn",
]

DEFAULT_BASE_URL = "https://developer.api.autodesk.com"
DEFAULT_SCOPES = "data:read data:write data:create bucket:create bucket:read"
#: Manifest statuses that mean "still working".
IN_PROGRESS = {"pending", "inprogress", "starting", "queued"}
#: Retried with backoff (transient upstream conditions).
RETRY_STATUSES = {429, 500, 502, 503, 504}
#: Anything that means "this file cannot be translated here".
UNSUPPORTED_HINTS = (
    "unsupported file format",
    "not a valid",
    "unrecognised",
    "unrecognized",
    "cannot be translated",
    "version",
)


def encode_urn(object_urn: str) -> str:
    """URL-safe base64, **without padding** -- exactly what MD expects."""
    return base64.urlsafe_b64encode(object_urn.encode("utf-8")).decode("ascii").rstrip("=")


def decode_urn(encoded: str) -> str:
    """Inverse of :func:`encode_urn` (re-adds padding for decoding).

    Tolerant by design: users paste either the encoded form or the plain
    ``urn:adsk.objects:...`` string, and a decode error must not abort a run.
    """
    text = str(encoded or "").strip()
    if not text or text.startswith("urn:"):
        return text
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return text
    return decoded if decoded else text


@dataclass(frozen=True)
class ApsConfig:
    """Everything needed to talk to APS for one application."""

    client_id: str
    client_secret: str
    #: Data residency: US by default; EU tenants must use the EU base URL and
    #: an EU-resident bucket.
    base_url: str = DEFAULT_BASE_URL
    bucket_key: str = ""
    policy_key: str = "transient"
    scopes: str = DEFAULT_SCOPES
    #: ``svf2`` keeps 2D sheet structure (needed for DWG), ``svf`` is legacy.
    output_format: str = "svf2"
    views: tuple[str, ...] = ("2d", "3d")
    translation_timeout: float = 900.0
    poll_interval: float = 3.0
    poll_backoff: float = 1.35
    poll_max_interval: float = 30.0
    http_timeout: float = 60.0
    max_attempts: int = 4
    min_delay: float = 1.0
    max_delay: float = 30.0
    #: Multipart chunk size for signed-S3 uploads (S3 minimum is 5 MiB).
    part_size_mb: int = 8
    #: Delete the uploaded object once extraction finished (privacy).
    delete_after_extract: bool = False
    #: Do not upload/translate at all -- only inspect an existing URN.
    read_only: bool = False

    @classmethod
    def from_settings(cls, settings: Any) -> "ApsConfig":
        client_id, client_secret, bucket_key = settings.require_aps_credentials()
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            base_url=settings.aps_base_url or DEFAULT_BASE_URL,
            bucket_key=bucket_key,
            policy_key=settings.aps_policy_key,
            scopes=settings.aps_scopes,
            output_format=settings.aps_output_format,
            translation_timeout=settings.aps_translation_timeout,
            http_timeout=settings.aps_timeout,
            part_size_mb=max(5, int(settings.aps_max_upload_part_mb or 8)),
        )

    @property
    def part_size(self) -> int:
        return self.part_size_mb * 1024 * 1024


@dataclass
class OssObject:
    """A design file stored in APS Object Storage Service."""

    object_key: str
    object_urn: str
    encoded_urn: str
    bucket_key: str
    size_bytes: int = 0
    content_type: str = "application/octet-stream"
    reused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket_key,
            "object_key": self.object_key,
            "urn": self.object_urn,
            "encoded_urn": self.encoded_urn,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "reused": self.reused,
        }


@dataclass
class ApsExtraction:
    """Raw + normalised results of an APS run (the "JSON manifest")."""

    manifest: dict[str, Any]
    structure: dict[str, Any]
    views: list[dict[str, Any]] = field(default_factory=list)
    properties: list[dict[str, Any]] = field(default_factory=list)
    derivatives: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    object: OssObject | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": "autodesk-platform-services",
            "object": self.object.as_dict() if self.object else None,
            "manifest": self.manifest,
            "structure": self.structure,
            "views": self.views,
            "properties": self.properties,
            "derivatives": self.derivatives,
            "warnings": self.warnings,
            "timings_ms": {key: round(value * 1000, 1) for key, value in self.timings.items()},
        }

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.as_dict(), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        return target


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, dict[str, Any]], None]


class ApsClient:
    """Minimal, dependency-light APS client (OSS + Model Derivative).

    ``requests`` is imported lazily so that a DWG parsed locally never needs the
    extra dependency, and ``transport`` can be swapped in tests.
    """

    def __init__(
        self,
        config: ApsConfig,
        *,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        progress: ProgressCallback | None = None,
    ) -> None:
        if not config.client_id or not config.client_secret:
            raise ConfigError("APS client credentials are required for the Autodesk fallback")
        self.config = config
        self._sleep = sleep
        self._monotonic = monotonic
        self._progress = progress
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._session = session
        self._bucket_ready = False

    # ------------------------------------------------------------------ plumbing
    @property
    def base_url(self) -> str:
        return self.config.base_url.rstrip("/")

    def _http(self) -> Any:
        if self._session is None:
            try:
                import requests
            except ImportError as exc:  # pragma: no cover - requirements.txt ships it
                raise AutodeskError(
                    "the Autodesk fallback needs the 'requests' package (pip install requests)"
                ) from exc
            self._session = requests.Session()
        return self._session

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        logger.info("aps: %s", event, extra={"event": event})
        if self._progress is not None:
            try:
                self._progress(event, payload)
            except Exception:  # pragma: no cover - a bad callback must not kill extraction
                logger.debug("progress callback failed", exc_info=True)

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        auth: bool = True,
        json_body: Mapping[str, Any] | None = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        extra_retries: set[int] | None = None,
    ) -> Any:
        """HTTP with token injection, backoff and typed errors.

        Returns the ``requests`` response for 2xx; raises for everything else.
        """
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        merged: dict[str, str] = dict(headers or {})
        if auth:
            merged["Authorization"] = f"Bearer {self.get_token()}"
        retry_statuses = set(RETRY_STATUSES) | set(extra_retries or ())
        attempts = max(1, self.config.max_attempts)
        last: Any = None
        for attempt in range(1, attempts + 1):
            if attempt > 1 and auth:
                # Re-read the cached token: it may have been refreshed by an
                # earlier attempt (or expired between attempts).  The token
                # request itself (``auth=False``) must never re-enter
                # ``get_token`` -- that would recurse on a transient failure.
                merged["Authorization"] = f"Bearer {self.get_token()}"
            try:
                response = self._http().request(
                    method,
                    url,
                    json=json_body if json_body is not None else None,
                    data=data,
                    headers=merged,
                    params=dict(params) if params else None,
                    timeout=timeout or self.config.http_timeout,
                )
            except Exception as exc:  # network/transport layer
                last = exc
                if attempt >= attempts:
                    raise AutodeskError(
                        f"{method} {url} failed after {attempt} attempt(s): {type(exc).__name__}: {_safe_str(exc)}",
                        hint="check network egress to developer.api.autodesk.com and proxy settings",
                        details={"method": method, "url": url, "attempts": attempt, "last_error": _safe_str(last)},
                    ) from exc
                delay = min(self.config.max_delay, self.config.min_delay * (2 ** (attempt - 1)))
                logger.warning(
                    "aps transport error (attempt %s/%s): %s; retrying in %.1fs",
                    attempt,
                    attempts,
                    _safe_str(exc),
                    delay,
                )
                self._sleep(delay)
                continue

            if response.status_code in (200, 201, 202, 204, 206):
                return response
            retry_after = _retry_after_seconds(response)
            if response.status_code in retry_statuses and attempt < attempts:
                delay = retry_after or min(self.config.max_delay, self.config.min_delay * (2 ** (attempt - 1)))
                self._emit("retry", {"status": response.status_code, "attempt": attempt, "delay": delay})
                logger.warning("APS %s on %s %s; retrying in %.1fs", response.status_code, method, url, delay)
                self._sleep(delay)
                continue
            raise self._error_for(method, url, response, attempt=attempt)
        raise AutodeskError(f"{method} {url} exhausted retries", details={"attempts": attempts})  # pragma: no cover

    def _error_for(self, method: str, url: str, response: Any, *, attempt: int = 1) -> AutodeskError:
        status = getattr(response, "status_code", None)
        body = _safe_body(response)
        text = _body_text(body)
        details = {"method": method, "url": url, "attempts": attempt, "response": text[:1500]}
        lowered = text.lower()

        if status in (401, 403):
            hint = None
            if "token" in lowered or "expired" in lowered:
                hint = "the 2-legged token expired mid-run; cad2ai refreshes automatically -- re-check clock skew"
            elif "scope" in lowered or "forbidden" in lowered:
                hint = f"the app is missing an OAuth scope; required scopes are: {self.config.scopes}"
            return AutodeskAuthError(
                f"APS authentication/authorisation failed ({status}) for {method} {url.split('?')[0]}",
                status_code=status,
                hint=hint or "verify APS_CLIENT_ID/APS_CLIENT_SECRET and that the app has the OSS + MD services enabled",
                details=details,
            )
        if status == 404:
            return AutodeskNotFound(
                f"APS resource not found (404) for {method} {url.split('?')[0]}",
                status_code=status,
                hint="the object may have expired (transient policy keeps 30 days) or the URN is malformed",
                details=details,
            )
        if status == 409:
            return AutodeskUploadError(
                f"APS conflict (409) for {method} {url.split('?')[0]}",
                status_code=status,
                hint="bucket keys are global: pick a unique APS_BUCKET_KEY",
                details=details,
            )
        if status == 429:
            return AutodeskRateLimitError(
                "APS rate limit reached (429)",
                retry_after=_retry_after_seconds(response),
                status_code=status,
                hint="reduce concurrency/burst; APS throttles per client",
                details=details,
            )
        if status in (500, 502, 503, 504):
            return AutodeskError(
                f"APS server error ({status}) for {method} {url.split('?')[0]}",
                status_code=status,
                hint="transient upstream failure -- cad2ai retried and gave up; re-run later",
                details=details,
            )
        if status in (400, 406, 422):
            if any(hint in lowered for hint in UNSUPPORTED_HINTS):
                return UnsupportedDwgVersionError(
                    f"APS cannot translate this file: {text[:300]}",
                    hint="re-save as DWG 2018 (AC1032), or translate locally with the ODA File Converter",
                    details={"path": url, "aps_response": text[:800]},
                )
            return AutodeskTranslationError(
                f"APS rejected the request ({status}): {text[:400]}",
                status_code=status,
                hint="check the URN encoding and the requested output format/views",
                details=details,
            )
        return AutodeskError(
            f"unexpected APS status {status} for {method} {url.split('?')[0]}",
            status_code=status,
            details=details,
        )

    # ------------------------------------------------------------- authentication
    def get_token(self) -> str:
        """Return a cached 2-legged token, refreshed 30 s before expiry."""
        now = self._monotonic()
        if self._token and now < self._token_expires_at:
            return self._token
        response = self._request(
            "POST",
            "/authentication/v2/token",
            auth=False,
            data={"grant_type": "client_credentials", "scope": self.config.scopes},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": "Basic "
                + base64.b64encode(f"{self.config.client_id}:{self.config.client_secret}".encode()).decode(),
            },
            extra_retries={400},
        )
        payload = _json_or_raise(response, context="APS token response")
        token = payload.get("access_token")
        if not token:
            raise AutodeskAuthError("APS token response contained no access_token", details={"keys": sorted(payload)})
        expires_in = float(payload.get("expires_in") or 3600)
        self._token = str(token)
        self._token_expires_at = now + max(30.0, expires_in - 30.0)
        logger.debug("acquired APS token valid ~%.0fs (scopes=%s)", expires_in, self.config.scopes)
        return self._token

    def introspect(self) -> dict[str, Any]:
        """Cheap credential check used by ``main.py doctor`` (no data leaves beyond auth)."""
        started = self._monotonic()
        token = self.get_token()
        return {
            "authenticated": True,
            "token_length": len(token),
            "latency_ms": round((self._monotonic() - started) * 1000, 1),
            "base_url": self.base_url,
            "scopes": self.config.scopes,
        }

    # ------------------------------------------------------------------ storage
    def ensure_bucket(self) -> str:
        """Create the OSS bucket if needed (409 "already exists" is fine)."""
        if self._bucket_ready or not self.config.bucket_key:
            return self.config.bucket_key
        try:
            self._request(
                "POST",
                "/oss/v2/buckets",
                json_body={"bucketKey": self.config.bucket_key, "policyKey": self.config.policy_key},
                headers={"Accept": "application/json"},
            )
            self._emit("bucket_created", {"bucket": self.config.bucket_key, "policy": self.config.policy_key})
        except AutodeskError as exc:
            # Bucket already existing (or being owned by this app) is not an error.
            status = exc.details.get("response", "") if isinstance(exc.details, dict) else ""
            if not _looks_like_conflict(str(status), exc.message):
                raise
            self._emit("bucket_exists", {"bucket": self.config.bucket_key})
        self._bucket_ready = True
        return self.config.bucket_key

    def upload_file(self, path: str | Path, *, object_key: str | None = None, force: bool = False) -> OssObject:
        """Upload a design file via the signed-S3 three-step flow.

        Large files use S3 multipart uploads; small files a single PUT.  The
        object is reused (skipping the upload) unless ``force`` is set, which
        makes re-running analysis of an unchanged drawing much cheaper.
        """
        file_path = Path(path)
        if not file_path.is_file():
            raise AutodeskUploadError(f"input file not found: {file_path}", details={"path": str(file_path)})
        self.ensure_bucket()
        size = file_path.stat().st_size
        key = object_key or _default_object_key(file_path)
        bucket = self.config.bucket_key
        object_urn = f"urn:adsk.objects:os.object:{bucket}/{key}"

        if not force and self._object_exists(bucket, key, expected_size=size):
            self._emit("upload_reused", {"object_key": key, "size_bytes": size})
            return OssObject(
                object_key=key,
                object_urn=object_urn,
                encoded_urn=encode_urn(object_urn),
                bucket_key=bucket,
                size_bytes=size,
                content_type=_content_type(file_path),
                reused=True,
            )

        part_size = self.config.part_size
        parts = max(1, (size + part_size - 1) // part_size)
        started = self._monotonic()
        self._emit("upload_started", {"object_key": key, "size_bytes": size, "parts": int(parts)})

        signed = _json_or_raise(
            self._request(
                "GET",
                f"/oss/v2/buckets/{bucket}/objects/{_quote(key)}/signeds3upload",
                params={"parts": int(parts), "minutesExpiration": 60},
                headers={"Accept": "application/json"},
            ),
            context="signed-S3 upload URLs",
        )
        upload_key = signed.get("uploadKey")
        urls = signed.get("urls") or []
        if not upload_key or not urls:
            raise AutodeskUploadError(
                "APS did not return a signed S3 upload URL",
                details={"response": {k: signed.get(k) for k in ("uploadKey", "urls")}},
            )
        etags: list[str] = []
        with file_path.open("rb") as handle:
            for index, url in enumerate(urls):
                chunk = handle.read(part_size)
                if not chunk:
                    break
                response = self._request(
                    "PUT",
                    url,
                    auth=False,
                    data=chunk,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=max(self.config.http_timeout, 300.0),
                )
                etag = response.headers.get("ETag") if response is not None else None
                if etag:
                    etags.append(etag.strip('"'))
                self._emit("upload_part", {"part": index + 1, "of": len(urls), "bytes": len(chunk)})
        body: dict[str, Any] = {"uploadKey": upload_key}
        if etags:
            body["eTags"] = etags
        if size:
            body["size"] = size
        _json_or_raise(
            self._request(
                "POST",
                f"/oss/v2/buckets/{bucket}/objects/{_quote(key)}/signeds3upload",
                json_body=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            ),
            context="complete S3 upload",
        )
        elapsed = self._monotonic() - started
        self._emit("upload_finished", {"object_key": key, "seconds": round(elapsed, 1)})
        return OssObject(
            object_key=key,
            object_urn=object_urn,
            encoded_urn=encode_urn(object_urn),
            bucket_key=bucket,
            size_bytes=size,
            content_type=_content_type(file_path),
        )

    def _object_exists(self, bucket: str, key: str, *, expected_size: int) -> bool:
        try:
            response = self._request("GET", f"/oss/v2/buckets/{bucket}/objects/{_quote(key)}/details", auth=True)
        except AutodeskError as exc:
            if exc.status_code == 404:
                return False
            logger.debug("object details lookup failed: %s", exc)
            return False
        payload = _maybe_json(response)
        if not isinstance(payload, Mapping):
            return False
        return int(payload.get("size") or -1) == int(expected_size)

    def delete_object(self, object_key: str, *, bucket: str | None = None) -> None:
        """Best-effort cleanup (used with ``delete_after_extract``)."""
        target_bucket = bucket or self.config.bucket_key
        try:
            self._request("DELETE", f"/oss/v2/buckets/{target_bucket}/objects/{_quote(object_key)}")
            self._emit("object_deleted", {"object_key": object_key})
        except AutodeskError as exc:
            logger.warning("could not delete APS object %s: %s", object_key, exc.message)

    # ------------------------------------------------------------ model derivative
    def start_translation(
        self,
        encoded_urn: str,
        *,
        output_format: str | None = None,
        views: Sequence[str] | None = None,
        root_filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Kick off ``POST /modelderivative/v2/designdata/job`` (async)."""
        fmt = (output_format or self.config.output_format).lower()
        if fmt not in ("svf2", "svf"):
            raise AutodeskError(
                f"unsupported APS output format {fmt!r}",
                hint="cad2ai can only derive structural metadata from svf2/svf outputs",
            )
        payload: dict[str, Any] = {
            "input": {"urn": encoded_urn},
            "output": {"formats": [{"type": fmt, "views": list(views or self.config.views)}]},
        }
        if root_filename:
            payload["input"]["rootFilename"] = root_filename
        headers = {"Accept": "application/json"}
        if force:
            headers["x-ads-force"] = "true"  # restart the translation job
        response = self._request(
            "POST",
            "/modelderivative/v2/designdata/job",
            json_body=payload,
            headers=headers,
        )
        body = _maybe_json(response) or {}
        self._emit("translation_submitted", {"urn": encoded_urn[:24] + "...", "format": fmt, "views": list(views or self.config.views)})
        return dict(body)

    def get_manifest(self, encoded_urn: str) -> dict[str, Any]:
        response = self._request("GET", f"/modelderivative/v2/designdata/{encoded_urn}/manifest")
        return _json_or_raise(response, context="manifest")

    def wait_for_manifest(self, encoded_urn: str, *, timeout: float | None = None) -> dict[str, Any]:
        """Poll the manifest until success/failure/timeout with jittered backoff."""
        limit = timeout if timeout is not None else self.config.translation_timeout
        started = self._monotonic()
        delay = self.config.poll_interval
        manifest: dict[str, Any] = {}
        polls = 0
        while True:
            polls += 1
            manifest = self.get_manifest(encoded_urn)
            status = str(manifest.get("status") or manifest.get("progress") or "").lower()
            progress = manifest.get("progress")
            self._emit(
                "translation_status",
                {"status": status or "unknown", "progress": progress, "poll": polls},
            )
            if status == "success" or (status == "" and progress in ("complete", "success")):
                return manifest
            if status in ("failed", "timeout"):
                raise AutodeskTranslationError(
                    f"APS translation {status}: {_derivative_messages(manifest)[:400] or 'no detail in manifest'}",
                    hint="check that the DWG opens in AutoCAD/trueView; corrupt or password-protected files fail here",
                    details={"manifest_excerpt": _excerpt(manifest)},
                )
            if status not in IN_PROGRESS and status not in ("", "inprogress", "pending"):
                logger.debug("unexpected manifest status %r; continuing to poll", status)
            if self._monotonic() - started > limit:
                raise AutodeskTranslationTimeoutError(
                    f"APS translation did not finish within {limit:.0f}s (last status={status or 'unknown'})",
                    hint="raise APS_TRANSLATION_TIMEOUT for large drawings, or pre-translate and reuse the URN",
                    details={"last_manifest_excerpt": _excerpt(manifest), "polls": polls},
                )
            self._sleep(min(delay, self.config.poll_max_interval))
            delay = min(delay * self.config.poll_backoff, self.config.poll_max_interval)

    def download_derivative(self, encoded_urn: str, derivative_urn: str) -> bytes:
        """Fetch one derivative payload (manifest child ``urn``)."""
        response = self._request(
            "GET",
            f"/modelderivative/v2/designdata/{encoded_urn}/manifest/{_quote(derivative_urn, safe=':/')}",
            headers={"Accept": "application/octet-stream, application/json, */*"},
        )
        return getattr(response, "content", b"") or b""

    def list_model_views(self, encoded_urn: str) -> list[dict[str, Any]]:
        """``GET /{urn}/metadata`` -> view descriptors (name/role/guid)."""
        payload = _maybe_json(self._request("GET", f"/modelderivative/v2/designdata/{encoded_urn}/metadata")) or {}
        data = payload.get("data") if isinstance(payload, Mapping) else None
        metadata = (data or {}).get("metadata") if isinstance(data, Mapping) else None
        if not isinstance(metadata, list):
            return []
        out: list[dict[str, Any]] = []
        for item in metadata:
            if not isinstance(item, Mapping):
                continue
            out.append(
                {
                    "guid": item.get("guid"),
                    "name": item.get("name"),
                    "role": item.get("role"),
                    "is_master_view": item.get("isMasterView"),
                }
            )
        return out

    def fetch_view_properties(
        self,
        encoded_urn: str,
        guid: str,
        *,
        max_records: int = 500,
    ) -> list[dict[str, Any]]:
        """``GET /{urn}/metadata/{guid}/properties`` with pagination."""
        records: list[dict[str, Any]] = []
        page = 1
        while len(records) < max_records:
            response = self._request(
                "GET",
                f"/modelderivative/v2/designdata/{encoded_urn}/metadata/{guid}/properties",
                params={"page": page} if page > 1 else None,
            )
            payload = _maybe_json(response) or {}
            data = payload.get("data") if isinstance(payload, Mapping) else {}
            collection = (data or {}).get("collection") or []
            if not isinstance(collection, list) or not collection:
                break
            for item in collection:
                if isinstance(item, Mapping):
                    records.append(dict(item))
                    if len(records) >= max_records:
                        break
            if not _has_next(data or {}):
                break
            page += 1
        return records

    def fetch_hierarchy(self, encoded_urn: str, guid: str) -> dict[str, Any]:
        """``GET /{urn}/metadata/{guid}/hierarchies`` -- full tree, first page only."""
        payload = _maybe_json(
            self._request("GET", f"/modelderivative/v2/designdata/{encoded_urn}/metadata/{guid}/hierarchies")
        )
        return dict(payload or {})

    # ------------------------------------------------------------------ workflow
    def extract(
        self,
        path: str | Path,
        *,
        object_key: str | None = None,
        wait: bool = True,
        fetch_properties: bool = True,
        force_translation: bool = False,
    ) -> ApsExtraction:
        """Full Phase-1 fallback: upload -> translate -> manifest -> structure."""
        warnings: list[str] = []
        timings: dict[str, float] = {}
        started = self._monotonic()
        uploaded = self.upload_file(path, object_key=object_key, force=force_translation)
        timings["upload"] = self._monotonic() - started

        started = self._monotonic()
        self.start_translation(uploaded.encoded_urn, force=force_translation)
        timings["submit"] = self._monotonic() - started

        started = self._monotonic()
        manifest = self.wait_for_manifest(uploaded.encoded_urn) if wait else {}
        timings["translate"] = self._monotonic() - started

        if self.config.delete_after_extract:
            self.delete_object(uploaded.object_key)

        structure = normalize_manifest(manifest, warnings=warnings)
        views = self.list_model_views(uploaded.encoded_urn) if wait else []
        properties: list[dict[str, Any]] = []
        derivatives: dict[str, Any] = {}
        if wait and views:
            for view in views[:8]:
                guid = view.get("guid")
                if not guid:
                    continue
                if fetch_properties:
                    try:
                        properties.extend(self.fetch_view_properties(uploaded.encoded_urn, str(guid)))
                    except AutodeskError as exc:
                        warnings.append(f"properties for view {view.get('name')!r} unavailable: {exc.message}")
        if wait:
            derivatives = self.download_structural_json(uploaded.encoded_urn, manifest, warnings=warnings)

        extraction = ApsExtraction(
            manifest=manifest,
            structure=structure,
            views=views,
            properties=_dedupe_records(properties),
            derivatives=derivatives,
            timings=timings,
            warnings=warnings,
            object=uploaded,
        )
        self._emit("extracted", {"views": len(views), "properties": len(extraction.properties)})
        return extraction

    def download_structural_json(
        self,
        encoded_urn: str,
        manifest: Mapping[str, Any],
        *,
        max_bytes: int = 4_000_000,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Download the JSON derivatives (view/scene metadata) referenced by ``manifest``.

        Only JSON-ish children are fetched (``application/json`` mimes and
        ``*.json`` hrefs) and each is capped in size, because a full SVF2 scene
        can be hundreds of megabytes -- the structural metadata we need lives in
        small JSON fragments.
        """
        results: dict[str, Any] = {}
        for child in _manifest_json_children(manifest):
            urn = child.get("urn") or child.get("href")
            name = str(child.get("name") or child.get("role") or urn)
            if not urn:
                continue
            try:
                blob = self.download_derivative(encoded_urn, str(urn))
            except AutodeskError as exc:
                message = f"could not download {name}: {exc.message}"
                logger.debug(message)
                if warnings is not None:
                    warnings.append(message)
                continue
            if not blob:
                continue
            truncated = len(blob) > max_bytes
            text = blob[:max_bytes].decode("utf-8", errors="replace")
            if truncated:
                if warnings is not None:
                    warnings.append(f"{name} truncated to {max_bytes} bytes for structural parsing")
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    results[name] = {"truncated": True, "bytes": len(blob), "excerpt": text[:500]}
                    continue
            else:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    results[name] = {"not_json": True, "bytes": len(blob)}
                    continue
            results[name] = parsed
        return results


# ---------------------------------------------------------------------------
# normalisation into the Phase 2 shape
# ---------------------------------------------------------------------------


def normalize_manifest(manifest: Mapping[str, Any] | None, *, warnings: list[str] | None = None) -> dict[str, Any]:
    """Reduce an APS manifest to the structural facts Phase 2/3 care about.

    Returns a dict shaped like ``CadModel``'s ``document``/``entities``/``layers``
    sections (layers may be empty for formats that do not expose them).
    """
    payload = dict(manifest or {})
    derivatives = payload.get("derivatives") or []
    out: dict[str, Any] = {
        "urn": payload.get("urn"),
        "status": payload.get("status"),
        "progress": payload.get("progress"),
        "region": payload.get("region"),
        "has_thumbnail": str(payload.get("hasThumbnail", "")).lower() == "true",
        "derivative_formats": [],
        "views": [],
        "layers": [],
        "counts": {},
    }
    layer_names: set[str] = set()
    for derivative in derivatives if isinstance(derivatives, list) else []:
        if not isinstance(derivative, Mapping):
            continue
        entry: dict[str, Any] = {
            "output_type": derivative.get("outputType") or derivative.get("name"),
            "status": derivative.get("status"),
            "progress": derivative.get("progress"),
            "has_thumbnail": str(derivative.get("hasThumbnail", "")).lower() == "true",
            "children": [],
        }
        for child in derivative.get("children") or []:
            if not isinstance(child, Mapping):
                continue
            summary = {
                "role": child.get("role"),
                "name": child.get("name"),
                "mime": child.get("mime"),
                "type": child.get("type"),
                "status": child.get("status"),
                "guid": child.get("guid"),
                "urn": child.get("urn"),
            }
            entry["children"].append({key: value for key, value in summary.items() if value is not None})
            if summary["role"] in ("2d", "3d") or summary["type"] == "view":
                out["views"].append({key: value for key, value in summary.items() if value is not None})
            layer_name = child.get("layerName") or child.get("layer")
            if isinstance(layer_name, str) and layer_name:
                layer_names.add(layer_name)
            metadata = child.get("metadata")
            if isinstance(metadata, list):
                for item in metadata:
                    if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                        layer_names.add(item["name"])
        if derivative.get("model"):
            entry["model"] = derivative.get("model")
        if derivative.get("messages"):
            entry["messages"] = derivative.get("messages")
            if warnings is not None:
                for message in derivative.get("messages") or []:
                    warnings.append(f"APS derivative message: {_excerpt(message)}"[:400])
        out["derivative_formats"].append(entry)

    out["layers"] = [{"name": name} for name in sorted(layer_names)]
    out["counts"] = {
        "derivatives": len(derivatives) if isinstance(derivatives, list) else 0,
        "views": len(out["views"]),
        "layers": len(out["layers"]),
    }
    return out


def cad_model_from_aps(
    extraction: ApsExtraction,
    *,
    source_path: str | Path,
    dwg_version: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> Any:
    """Build a :class:`~cad2ai.structurer.CadModel` from an APS extraction.

    The payload is intentionally partial (``source.lossless`` is False): the
    structural manifest is *not* equivalent to the DWG object graph, and the
    model must be told that, otherwise it will present estimates as facts.
    """
    from cad2ai.structurer import CadModel, SCHEMA_VERSION

    structure = extraction.structure or {}
    layers = []
    for layer in structure.get("layers") or []:
        if isinstance(layer, Mapping) and layer.get("name"):
            layers.append({"name": str(layer["name"])})
    properties = extraction.properties or []
    derived_layers: dict[str, int] = {}
    for record in properties:
        if not isinstance(record, Mapping):
            continue
        layer = None
        candidates = [record.get("layer"), (record.get("properties") or {}).get("Layer") if isinstance(record.get("properties"), Mapping) else None]
        for value in candidates:
            if isinstance(value, str) and value:
                layer = value
                break
        if layer:
            derived_layers[layer] = derived_layers.get(layer, 0) + 1
    for name, count in sorted(derived_layers.items(), key=lambda item: -item[1]):
        if not any(existing["name"] == name for existing in layers):
            layers.append({"name": name, "entities": count})

    view_names = [view.get("name") for view in structure.get("views") or [] if isinstance(view, Mapping)]
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "name": str(source_path),
            "file": Path(source_path).name,
            "backend": "aps-model-derivative",
            "lossless": False,
            "provenance": "autodesk-platform-services",
            "size_bytes": extraction.object.size_bytes if extraction.object else None,
        },
        "document": {
            "units": {"insunits": None, "name": None},
            "dwg": dict(dwg_version or {}),
            "tables": {"layers": len(layers), "views": len(view_names)},
        },
        "layers": layers,
        "layer_stats": {"count": len(layers), "note": "layer metadata from the structural manifest; no ACI/linetype data"},
        "entities": {"total": len(properties) or None, "by_type": _property_type_histogram(properties)},
        "layouts": [{"name": name, "source": "aps-viewable"} for name in view_names if name],
        "blocks": [],
        "block_stats": {"note": "APS SVF2 output does not expose block definitions; use odafc for block analysis"},
        "text": [],
        "text_stats": {"note": "text is not part of the structural manifest"},
        "dimensions": [],
        "dimension_stats": {"note": "dimensions are not part of the structural manifest"},
        "dimension_styles": [],
        "linetypes": [],
        "text_styles": [],
        "discipline": {},
        "warnings": [
            "extracted via Autodesk Platform Services: structural metadata only (no entity-level geometry, colours or dimensions)",
            *extraction.warnings,
        ],
        "extraction": {
            "backend": "aps",
            "manifest_status": structure.get("status"),
            "views": len(view_names),
            "properties": len(properties),
            "timings_s": {key: round(value, 2) for key, value in extraction.timings.items()},
        },
        "aps": {
            "urn": (extraction.manifest or {}).get("urn"),
            "object": extraction.object.as_dict() if extraction.object else None,
            "derivative_formats": [
                {"output_type": item.get("output_type"), "status": item.get("status"), "children": len(item.get("children") or [])}
                for item in structure.get("derivative_formats") or []
            ],
        },
    }
    model = CadModel(**{key: value for key, value in payload.items() if key in CadModel.__dataclass_fields__})
    # `aps` is not a CadModel field; keep it in the warnings/extraction section.
    model.extraction["aps"] = payload["aps"]
    from cad2ai import discipline as discipline_module

    model.discipline = discipline_module.infer_discipline(
        [SimpleNamespaceLayer(name=item["name"], entities=item.get("entities", 0)) for item in layers]
    )
    return model


class SimpleNamespaceLayer:
    """Tiny adapter so the layer-based classifier works on APS names too."""

    def __init__(self, name: str, entities: int = 0) -> None:
        self.name = name
        self.entities = int(entities or 0)


# ---------------------------------------------------------------------------
# module helpers
# ---------------------------------------------------------------------------


def _default_object_key(file_path: Path) -> str:
    from cad2ai.dxfutils import sha256_prefix

    digest = sha256_prefix(file_path, 10) or "local"
    safe_stem = "".join(char if char.isalnum() or char in "-_." else "-" for char in file_path.stem)[:60]
    return f"{safe_stem}-{digest}{file_path.suffix.lower() or '.dwg'}"


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _quote(value: str, *, safe: str = "/") -> str:
    from urllib.parse import quote

    return quote(str(value), safe=safe)


def _retry_after_seconds(response: Any) -> float | None:
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.5, float(raw))
    except (TypeError, ValueError):
        pass
    try:  # HTTP-date form
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(str(raw))
        if when is None:  # pragma: no cover
            return None
        return max(0.5, float(when.timestamp() - time.time()))
    except (TypeError, ValueError, OSError):
        return None


def _safe_body(response: Any) -> Any:
    if response is None:
        return None
    try:
        return response.json()
    except Exception:
        try:
            return getattr(response, "text", "")
        except Exception:  # pragma: no cover
            return None


def _body_text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body, ensure_ascii=False, default=str)
    except Exception:  # pragma: no cover
        return str(body)


def _maybe_json(response: Any) -> Any:
    if response is None:
        return None
    try:
        return response.json()
    except Exception:
        return None


def _json_or_raise(response: Any, *, context: str) -> dict[str, Any]:
    payload = _maybe_json(response)
    if isinstance(payload, Mapping):
        return dict(payload)
    raise AutodeskError(
        f"APS {context} returned a non-JSON body",
        hint="an intermediate proxy may be intercepting the call",
        details={"body_excerpt": _body_text(_safe_body(response))[:400]},
    )


def _excerpt(value: Any, limit: int = 500) -> str:
    text = _body_text(value if isinstance(value, (str, bytes, bytearray)) else _jsonable(value))
    return text[:limit]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in list(value)[:30]]
    return value


def _derivative_messages(manifest: Mapping[str, Any]) -> str:
    messages: list[str] = []
    for derivative in manifest.get("derivatives") or []:
        if not isinstance(derivative, Mapping):
            continue
        for message in derivative.get("messages") or []:
            messages.append(_body_text(message))
    return " | ".join(message for message in messages if message)[:1000]


def _safe_str(value: Any) -> str:
    """``str()`` that cannot explode.

    Socket/SSL/peer exceptions occasionally have ``__str__`` implementations
    that recurse (or raise), and that must not turn a retryable transport error
    into an unhandled crash while the log line is being formatted.
    """
    try:
        return str(value)
    except Exception:  # pragma: no cover - pathological __str__
        return type(value).__name__


def _has_next(data: Mapping[str, Any]) -> bool:
    """Does this paged APS response have a following page?

    Pagination metadata sits at ``data.pagination`` for the properties/metadata
    endpoints and directly on ``data`` for others, so both are consulted; the
    numeric form (``page``/``limit``/``total``) is checked too because SVF2
    responses omit an explicit ``next`` link.
    """
    sources: list[Mapping[str, Any]] = [data]
    nested = data.get("pagination") if isinstance(data.get("pagination"), Mapping) else None
    if nested is not None:
        sources.append(nested)
    for source in sources:
        for key in ("next", "nxt", "hasNext", "has_next"):
            if source.get(key):
                return True
        try:
            page = int(source.get("page") or 0)
            limit = int(source.get("limit") or 0)
            total = int(source.get("total") or 0)
        except (TypeError, ValueError):
            continue
        if page and total and (limit or page >= 1) and page * max(limit, 1) < total:
            return True
    return False


def _dedupe_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        key = _body_text(_jsonable(record))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(record))
    return out


def _property_type_histogram(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Histogram of translated objects by their object/category metadata.

    SVF2 property records do not carry DXF entity types, so "unclassified" is
    a legitimate value -- it keeps the model honest instead of inventing types.
    """
    histogram: dict[str, int] = {}
    for record in records:
        properties = record.get("properties") if isinstance(record.get("properties"), Mapping) else {}
        kind = (
            record.get("objectType")
            or record.get("category")
            or (properties or {}).get("Object Type")
            or (properties or {}).get("Category")
            or "unclassified"
        )
        kind = str(kind).strip()[:40] or "unclassified"
        histogram[kind] = histogram.get(kind, 0) + 1
    return dict(sorted(histogram.items(), key=lambda item: (-item[1], item[0]))[:40])


def _manifest_json_children(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for derivative in manifest.get("derivatives") or []:
        if not isinstance(derivative, Mapping):
            continue
        model = derivative.get("model")
        if isinstance(model, Mapping) and _is_jsonish(model):
            children.append(dict(model))
        for child in derivative.get("children") or []:
            if isinstance(child, Mapping) and _is_jsonish(child):
                children.append(dict(child))
    return children


def _is_jsonish(child: Mapping[str, Any]) -> bool:
    mime = str(child.get("mime") or "").lower()
    href = str(child.get("href") or child.get("urn") or "").lower()
    if "json" in mime:
        return True
    if mime and "json" not in mime:
        return False
    return href.endswith(".json") or "manifest" in href


def _looks_like_conflict(text: str, message: str) -> bool:
    haystack = f"{text} {message}".lower()
    return "already exists" in haystack or "conflict" in haystack or "in use" in haystack
