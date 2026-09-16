"""FastAPI service in front of the ``cad2ai`` pipeline.

The CLI (``python main.py analyze drawing.dwg``) and this server run *exactly* the
same code path -- ``cad2ai.pipeline.Pipeline.run`` -- so an answer obtained
through the API is byte-for-byte reproducible from the artifact directory. The
server adds only what a service needs: upload handling, per-request isolation,
concurrency and timeout guards, typed HTTP status codes, and guaranteed cleanup
of the uploaded file.

Run it::

    pip install -r requirements-api.txt
    uvicorn server:app --reload --host 0.0.0.0 --port 8000

Endpoints
    ``POST /api/analyze``            multipart upload (.dwg/.dxf) -> ``analysis.json`` body
    ``GET  /api/health``             backends, model config, limits, active jobs (``?probe=1`` pings DeepSeek)
    ``GET  /api/runs/{id}/…``        the kept artifacts of a run (``?keep=1`` on the upload)

Configuration (all optional, read from the process environment or ``.env``):

===========================  ======  =========================================================
variable                     default  meaning
===========================  ======  =========================================================
``CAD2AI_API_MAX_UPLOAD_MB``  64      reject larger uploads with ``413``
``CAD2AI_API_TIMEOUT_S``      900     wall-clock limit per job; ``504`` beyond it
``CAD2AI_API_CONCURRENCY``    2       parallel pipeline runs; ``429`` beyond it
``CAD2AI_CORS_ORIGINS``       http://localhost:3000  comma-separated allow-list
``CAD2AI_API_ARTIFACT_DIR``   out/api-runs  where ``?keep=1`` runs are written
``CAD2AI_API_KEEP``           0       keep artifacts even when the client did not ask
===========================  ======  =========================================================

Notes for reviewers
    * The pipeline is blocking (subprocess + HTTP), so it runs on Starlette's
      threadpool; the event loop stays free to answer ``/api/health`` while a
      drawing is being parsed.
    * A timeout answers ``504`` but cannot preempt the worker thread (Python has no
      mechanism for that), so the run keeps going to completion and is logged as
      orphaned. Its staged upload is still removed by the request's ``finally``;
      DeepSeek may be called once more for a client that already gave up, which is
      why the timeout should be set below your gateway's.
    * Nothing here trusts the model output; ``analysis`` is whatever DeepSeek
      returned (already JSON-parsed by ``ai_client``), and the dashboard
      normalises it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from cad2ai import __version__ as CAD2AI_VERSION
from cad2ai.config import Settings
from cad2ai.errors import (
    AutodeskAuthError,
    AutodeskError,
    AutodeskRateLimitError,
    AutodeskTranslationTimeoutError,
    Cad2AiError,
    ConfigError,
    CorruptCadFileError,
    DeepSeekAuthError,
    DeepSeekBadRequestError,
    DeepSeekEmptyResponseError,
    DeepSeekError,
    DeepSeekInsufficientBalanceError,
    DeepSeekJsonError,
    DeepSeekRateLimitError,
    DeepSeekResponseError,
    DeepSeekServerError,
    DeepSeekTransportError,
    DeepSeekTruncatedResponseError,
    DwgConverterError,
    DwgConverterNotInstalledError,
    DwgSecurityError,
    InputFileError,
    MissingEnvironmentVariableError,
    NotACadFileError,
    ParseError,
    UnsupportedDwgVersionError,
)
from cad2ai.parser import describe_backend_availability
from cad2ai.pipeline import Pipeline, render_markdown
from cad2ai.prompts import TASKS, resolve_task

logger = logging.getLogger("cad2ai.api")

ALLOWED_SUFFIXES = {".dwg", ".dxf"}
DEFAULT_CORS_ORIGINS = ("http://localhost:3000",)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FALLBACKS = ("auto", "none", "aps")

# Fallback for errors that do not carry an explicit HTTP mapping of their own.
_EXIT_STATUS = {2: 422, 3: 415, 4: 422, 5: 502, 6: 502}


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0")
    return value


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


@dataclass(frozen=True)
class ApiConfig:
    """Service-level limits, separated from pipeline settings on purpose."""

    max_upload_mb: float = 64.0
    timeout_s: float = 900.0
    concurrency: int = 2
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    allow_origin_regex: str | None = None
    artifact_root: Path = Path("out/api-runs")
    keep_by_default: bool = False

    @classmethod
    def from_env(cls) -> "ApiConfig":
        origins = tuple(
            entry.strip()
            for entry in (os.environ.get("CAD2AI_CORS_ORIGINS") or "").split(",")
            if entry.strip()
        ) or DEFAULT_CORS_ORIGINS
        root = (os.environ.get("CAD2AI_API_ARTIFACT_DIR") or "out/api-runs").strip()
        return cls(
            max_upload_mb=_env_float("CAD2AI_API_MAX_UPLOAD_MB", 64.0),
            timeout_s=_env_float("CAD2AI_API_TIMEOUT_S", 900.0),
            concurrency=_env_int("CAD2AI_API_CONCURRENCY", 2),
            cors_origins=origins,
            allow_origin_regex=(os.environ.get("CAD2AI_CORS_ORIGIN_REGEX") or "").strip() or None,
            artifact_root=Path(root),
            keep_by_default=(os.environ.get("CAD2AI_API_KEEP") or "").strip().lower() in {"1", "true", "yes"},
        )

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


class ConcurrencyGate:
    """Non-blocking permit counter, so an overloaded API answers ``429`` instantly.

    ``asyncio.Semaphore`` would make callers queue; a review service should say
    "try again" instead of holding ten 80-second requests open until they all
    time out at the proxy. The check-and-increment is atomic because it runs on
    the event loop without an ``await`` in between.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._active = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    def acquire(self) -> bool:
        if self._active >= self._limit:
            return False
        self._active += 1
        return True

    def release(self) -> None:
        self._active = max(0, self._active - 1)


# ---------------------------------------------------------------------------
# the unit of work
# ---------------------------------------------------------------------------


@dataclass
class ExtractionRequest:
    """One upload, already on disk, ready for the pipeline."""

    run_id: str
    input_path: Path
    filename: str
    task: str = "sheet_review"
    brief: str | None = None
    fallback: str = "auto"
    dry_run: bool = False
    include_markdown: bool = True
    settings: Settings = field(default_factory=Settings.from_env)
    artifact_dir: Path | None = None
    #: ``load_drawing`` honours ``max_file_mb=None`` by falling back to settings;
    #: the API enforces its own cap while streaming the upload, so it passes a
    #: relaxed value here rather than mutating validated settings.
    max_file_mb: float | None = None
    #: scratch pad for wrappers/tests (the pipeline ignores it)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_log_line(self) -> str:
        return (
            f"run={self.run_id} file={self.filename} task={self.task} mode={self.fallback} "
            f"dry_run={int(self.dry_run)}"
        )


# A worker takes an ExtractionRequest and returns the response body. Swapping it
# (``create_app(worker=...)``) is how the tests run the whole HTTP surface
# without ezdxf, the ODA converter or an API key.
Worker = Callable[[ExtractionRequest], Mapping[str, Any]]


def pipeline_worker(request: ExtractionRequest) -> dict[str, Any]:
    """Run the real pipeline. Blocking by design: called on the threadpool."""
    started = time.perf_counter()
    pipeline = Pipeline(request.settings)
    load_kwargs: dict[str, Any] = {}
    if request.max_file_mb is not None:
        load_kwargs["max_file_mb"] = request.max_file_mb
    report = pipeline.run(
        request.input_path,
        task=request.task,
        brief=request.brief,
        fallback=request.fallback,
        dry_run=request.dry_run,
        out_dir=request.artifact_dir,
        **load_kwargs,
    )
    meta = dict(report.payload_meta or {})
    body: dict[str, Any] = {
        "ok": True,
        "run_id": request.run_id,
        "filename": request.filename,
        "task": report.task or request.task,
        "mode": report.mode,
        "dry_run": request.dry_run,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "timings": dict(report.timings or {}),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis": report.analysis,
        "summary": report.summary,
        "payload": {
            "chars": meta.get("chars"),
            "token_estimate": meta.get("token_estimate"),
            "token_budget": meta.get("token_budget"),
            "degraded": meta.get("degraded") or [],
            "truncations": meta.get("truncations") or {},
            "budget_exceeded_by": meta.get("budget_exceeded_by"),
            "prompt_tokens_actual": meta.get("prompt_tokens_actual"),
            "counts": meta.get("counts") or {},
        },
        "usage": report.usage,
        "warnings": list(report.warnings or []),
        "artifacts": dict(report.artifacts or {}),
    }
    if request.include_markdown and isinstance(report.analysis, Mapping):
        try:
            body["markdown"] = render_markdown(report.analysis)
        except Exception as exc:  # noqa: BLE001 - a cosmetic rendering must not fail a run
            logger.warning("markdown rendering failed for run %s: %s", request.run_id, exc)
    return body


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------


def _status_for(exc: BaseException) -> int:
    """Map the typed error hierarchy onto meaningful status codes."""
    ordered: tuple[tuple[type[BaseException], int], ...] = (
        # the service itself is not usable yet -> caller cannot fix it by retrying
        (MissingEnvironmentVariableError, 503),
        (DwgConverterNotInstalledError, 503),
        # client-side request problems
        (UnsupportedDwgVersionError, 415),
        (NotACadFileError, 415),
        (InputFileError, 400),
        (DwgSecurityError, 400),
        (CorruptCadFileError, 422),
        (ParseError, 422),
        (DeepSeekRateLimitError, 429),
        (AutodeskRateLimitError, 429),
        (DeepSeekBadRequestError, 400),
        (AutodeskTranslationTimeoutError, 504),
        (DeepSeekAuthError, 502),
        (DeepSeekInsufficientBalanceError, 502),
        (AutodeskAuthError, 502),
        (DeepSeekTruncatedResponseError, 502),
        (DeepSeekEmptyResponseError, 502),
        (DeepSeekJsonError, 502),
        (DeepSeekResponseError, 502),
        (DeepSeekServerError, 502),
        (DeepSeekTransportError, 502),
        (DeepSeekError, 502),
        (DwgConverterError, 502),
        (AutodeskError, 502),
        (ConfigError, 422),
        (Cad2AiError, None),  # type: ignore[arg-type]
    )
    for kind, code in ordered:
        if isinstance(exc, kind):
            if code is not None:
                return code
            return _EXIT_STATUS.get(int(getattr(exc, "exit_code", 1) or 1), 500)
    if isinstance(exc, Cad2AiError):
        return _EXIT_STATUS.get(int(exc.exit_code or 1), 500)
    return 500


def _error_body(
    exc: BaseException,
    *,
    code: str | None = None,
    status_code: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Uniform error envelope the dashboard renders verbatim."""
    http = int(status_code) if status_code else (_status_for(exc) if isinstance(exc, Cad2AiError) else 500)
    if isinstance(exc, Cad2AiError):
        error = dict(exc.to_dict())
    else:
        error = {
            "error": type(exc).__name__,
            "message": str(exc)[:600],
            "hint": "unexpected server error; check the service log (CAD2AI_LOG_LEVEL=DEBUG)",
            "retryable": False,
            "exit_code": 1,
            "details": {},
        }
    error["status"] = http
    if code:
        error["code"] = code
    if extra:
        error.update(extra)
    return {"ok": False, "error": error}


def _fail(
    exc: BaseException,
    *,
    code: str | None = None,
    status_code: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> JSONResponse:
    body = _error_body(exc, code=code, status_code=status_code, extra=extra)
    headers: dict[str, str] = {}
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(exc, (DeepSeekRateLimitError, AutodeskRateLimitError)) or body["error"].get("status") == 429:
        headers["Retry-After"] = str(int(retry_after) if retry_after else 5)
    return JSONResponse(status_code=int(body["error"]["status"]), content=_plain(body), headers=headers or None)


def _plain(value: Any) -> Any:
    """Best-effort JSON-safety net for model output (never 500 on a weird type)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# Artifact name -> file name on disk. The pipeline writes ``analysis.md``; the
# dashboard and the docs call it ``report.md``, and both spellings resolve.
_SERVED_AS_ON_DISK = {"report.md": "analysis.md", "analysis_md": "analysis.md"}


def _safe_filename(original: str | None) -> str:
    """Keep a recognisable name for ``analysis.drawing`` without path traversal."""
    # Browsers send a bare basename, but a curl/Windows client may not: split on
    # both separators before sanitising, or "..\..\x.dxf" becomes a legal-looking name.
    raw = re.split(r"[\\/]", str(original or "drawing"))[-1] or "drawing"
    stem = _SAFE_NAME.sub("_", Path(raw).stem).strip(" .") or "drawing"
    suffix = Path(raw).suffix.lower()
    suffix = suffix if suffix in ALLOWED_SUFFIXES else ""
    return f"{stem[:72]}{suffix}"


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    worker: Worker | None = None,
    config: ApiConfig | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Build the app. ``worker`` is injected by the tests (see ``tests/test_server.py``)."""

    cfg = config or ApiConfig.from_env()
    base_settings = settings or Settings.from_env()
    run_extraction: Worker = worker or pipeline_worker
    gate = ConcurrencyGate(cfg.concurrency)
    started = time.time()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:  # pragma: no cover - trivial wiring
        """Configure logging, create the artifact root, announce the capabilities.

        Logging is set up here rather than at import time so that embedding the
        app (``app = create_app()`` inside a bigger service) does not reconfigure
        the host application's handlers.
        """
        level = getattr(logging, str(base_settings.log_level).upper(), logging.INFO)
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        cfg.artifact_root.mkdir(parents=True, exist_ok=True)
        availability = describe_backend_availability()
        logger.info(
            "cad2ai %s API ready (oda=%s, xvfb=%s, deepseek_key=%s, cors=%s, limits=%sMB/%ss/x%s)",
            CAD2AI_VERSION,
            availability.get("oda_installed"),
            availability.get("xvfb_available"),
            bool(base_settings.deepseek_api_key),
            ",".join(cfg.cors_origins),
            cfg.max_upload_mb,
            cfg.timeout_s,
            cfg.concurrency,
        )
        yield

    app = FastAPI(
        title="cad2ai analysis service",
        version=CAD2AI_VERSION,
        summary="DWG/DXF extraction + DeepSeek sheet review behind one HTTP endpoint.",
        description=(
            "Wraps ``cad2ai.pipeline.Pipeline.run``. Upload a drawing, get the "
            "``analysis.json`` object back. See ``/api/health`` for what this "
            "particular process can actually do (ODA converter, API key, APS app)."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        # The dashboard runs on :3000 in dev. Credentials are never sent, so
        # wildcards stay off the allow-list unless an operator opts in by regex.
        allow_origins=list(cfg.cors_origins),
        allow_origin_regex=cfg.allow_origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )


    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    async def health(probe: int = 0) -> JSONResponse:
        """Everything the dashboard needs to pre-flight before letting you upload."""
        availability = describe_backend_availability()
        from cad2ai.aps import ApsConfig

        try:
            ApsConfig.from_settings(base_settings)  # raises unless id/secret/bucket are all set
            aps_ready, aps_missing = True, []
        except Cad2AiError as exc:
            aps_ready = False
            details = exc.to_dict().get("details") or {}
            aps_missing = list(details.get("missing") or []) or [exc.message]
        body: dict[str, Any] = {
            "ok": True,
            "service": {
                "version": CAD2AI_VERSION,
                "uptime_s": round(time.time() - started, 1),
                "log_level": base_settings.log_level,
            },
            "backends": availability,
            "deepseek": {
                "base_url": base_settings.deepseek_base_url,
                "model": base_settings.deepseek_model,
                "key_present": bool(base_settings.deepseek_api_key),
                "json_mode": bool(base_settings.deepseek_json_mode),
                "thinking": base_settings.deepseek_thinking,
            },
            "autodesk": {"configured": aps_ready, "missing": aps_missing},
            "limits": {
                "max_upload_mb": cfg.max_upload_mb,
                "timeout_s": cfg.timeout_s,
                "concurrency": gate.limit,
                "active": gate.active,
                "allowed_suffixes": sorted(ALLOWED_SUFFIXES),
            },
            "tasks": sorted(TASKS),
            "readiness": {
                "accepts_dxf": True,
                # A .dwg needs the converter; without it the service is only
                # useful for DXF input (or APS, if that is configured).
                "accepts_dwg": bool(availability.get("oda_installed")) or aps_ready,
                "full_pipeline": bool(base_settings.deepseek_api_key),
            },
        }
        if probe:
            # A real round trip (~15 completion tokens) so an operator can prove
            # the key/base URL work without uploading a drawing.
            try:
                client = Pipeline(base_settings).client()
                body["deepseek"]["probe"] = await run_in_threadpool(client.health_check)
            except Cad2AiError as exc:
                body["deepseek"]["probe"] = {"ok": False, **_error_body(exc)["error"]}
            except Exception as exc:  # noqa: BLE001 - probes never fail the request
                body["deepseek"]["probe"] = {"ok": False, "message": str(exc)[:200]}
        return JSONResponse(content=_plain(body))

    @app.get("/", include_in_schema=False)
    async def index() -> PlainTextResponse:
        return PlainTextResponse(
            f"cad2ai analysis service v{CAD2AI_VERSION}\n"
            "POST /api/analyze  (multipart: file, task, brief, dry_run, keep)\n"
            "GET  /api/health\n"
            "docs: /docs\n"
        )

    # ---------------------------------------------------------------- analyze
    @app.post("/api/analyze")
    async def analyze(
        request: Request,
        file: UploadFile | None = File(default=None, description="A .dwg or .dxf drawing"),
        task: str = Form(default="sheet_review"),
        brief: str | None = Form(default=None),
        fallback: str = Form(default="auto"),
        dry_run: int = Form(default=0, description="1 = phases 1+2 only, no DeepSeek call"),
        keep: int = Form(default=-1, description="1 = retain artifacts, -1 = use CAD2AI_API_KEEP"),
        include_markdown: int = Form(default=1),
        max_payload_tokens: int = Form(default=0, description="override CAD2AI_MAX_PAYLOAD_TOKENS for this run"),
    ) -> Any:
        """Parse, structure and analyse one uploaded drawing.

        The response body is ``analysis.json`` plus the provenance the dashboard
        needs (which backend produced it, what the payload had to drop, timings).
        """
        run_id = _new_run_id()
        if file is None or not (file.filename or "").strip():
            return _fail(
                InputFileError(
                    "no file uploaded",
                    hint="send multipart/form-data with a 'file' field holding a .dwg or .dxf",
                ),
                code="file_missing",
            )

        filename = _safe_filename(file.filename)
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            # Quote the extension the caller actually sent: ``_safe_filename`` drops
            # anything unsupported, so "plan.zip" would otherwise read as "(none)".
            sent = Path(str(file.filename or "drawing")).suffix.lower() or "(no extension)"
            return _fail(
                NotACadFileError(
                    f"unsupported file type {sent}: this service accepts .dwg and .dxf",
                    hint="export the drawing to DWG 2018 or DXF from AutoCAD, or upload the original file",
                    details={"filename": file.filename, "accepted": sorted(ALLOWED_SUFFIXES)},
                ),
                code="unsupported_file_type",
            )

        wanted_task = str(task or "sheet_review").strip() or "sheet_review"
        # ``resolve_task`` is deliberately forgiving (unknown -> custom). A service
        # caller who typos "make_it_pretty" should hear back, not get a custom task.
        spec = resolve_task(wanted_task)
        if spec.key == "custom" and wanted_task.strip().lower() not in {"custom", ""}:
            return _fail(
                ConfigError(
                    f"unknown task {wanted_task!r}",
                    hint=f"task must be one of {', '.join(sorted(TASKS))} (aliases such as 'qa' or 'materials' also work)",
                    details={"task": wanted_task},
                ),
                code="unknown_task",
                status_code=422,
                extra={"known_tasks": sorted(TASKS)},
            )

        wanted_fallback = str(fallback or "auto").strip().lower()
        if wanted_fallback not in _FALLBACKS:
            return _fail(
                ConfigError(
                    f"unknown fallback {wanted_fallback!r}",
                    hint=f"fallback must be one of {', '.join(_FALLBACKS)}",
                    details={"fallback": wanted_fallback},
                ),
                code="bad_fallback",
            )

        if not gate.acquire():
            return _fail(
                Cad2AiError(
                    f"this service is already running {gate.limit} extraction(s)",
                    hint="retry shortly; raise CAD2AI_API_CONCURRENCY or queue the job on the caller side",
                    details={"active": gate.active, "limit": gate.limit},
                ),
                code="busy",
                status_code=429,
            )

        temp_root = Path(tempfile.mkdtemp(prefix=f"cad2ai-api-{run_id}-"))
        payload_path = temp_root / filename
        started = time.perf_counter()
        acquired = True
        try:
            # ---- write the upload, enforcing the size cap while streaming
            written = 0
            limit = cfg.max_upload_bytes
            try:
                with payload_path.open("wb") as handle:
                    while True:
                        chunk = await file.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > limit:
                            handle.close()
                            return _fail(
                                InputFileError(
                                    f"{filename} is {written / 1e6:.1f} MB, above the {limit / 1e6:.0f} MB limit",
                                    hint="split the sheet set, or raise CAD2AI_API_MAX_UPLOAD_MB",
                                    details={"bytes": written, "limit_bytes": limit},
                                ),
                                code="file_too_large",
                                status_code=413,
                            )
                        handle.write(chunk)
            except OSError as exc:
                return _fail(
                    InputFileError(f"could not stage the upload: {exc}", details={"path": str(payload_path)}),
                    code="staging_failed",
                )
            if written == 0:
                return _fail(
                    InputFileError(
                        f"{filename} is empty",
                        hint="check the file: a 0-byte upload is usually an interrupted transfer",
                        details={"bytes": 0},
                    ),
                    code="empty_file",
                )

            want_keep = cfg.keep_by_default if keep == -1 else bool(_as_int(keep))
            artifact_dir = cfg.artifact_root / run_id if want_keep else None
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)

            try:
                request_settings = (
                    Settings.from_env(payload_max_tokens=_as_int(max_payload_tokens))
                    if _as_int(max_payload_tokens) > 0
                    else base_settings
                )
            except Cad2AiError as exc:
                return _fail(exc, code="bad_payload_budget")

            extraction = ExtractionRequest(
                run_id=run_id,
                input_path=payload_path,
                filename=filename,
                task=wanted_task,
                brief=(str(brief).strip() if brief else None) or None,
                fallback=wanted_fallback,
                dry_run=bool(_as_int(dry_run)),
                include_markdown=bool(_as_int(include_markdown)),
                settings=request_settings,
                artifact_dir=artifact_dir,
                max_file_mb=max(base_settings.max_file_mb, cfg.max_upload_mb + 8),
            )
            logger.info("start %s bytes=%d", extraction.to_log_line(), written)

            # ---- the long part: bounded, off the event loop
            try:
                result = await asyncio.wait_for(
                    run_in_threadpool(run_extraction, extraction),
                    timeout=cfg.timeout_s,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "timeout for run %s after %ss: answering 504 while the worker thread keeps running "
                    "(its staged upload is removed below)",
                    run_id,
                    cfg.timeout_s,
                )
                return _fail(
                    Cad2AiError(
                        f"extraction did not finish within {cfg.timeout_s:.0f}s",
                        hint=(
                            "the drawing may need a longer ODA/conversion timeout; raise CAD2AI_API_TIMEOUT_S, "
                            "ODA_TIMEOUT or APS_TRANSLATION_TIMEOUT, or analyse per sheet"
                        ),
                        details={"timeout_s": cfg.timeout_s, "run_id": run_id},
                    ),
                    code="extraction_timeout",
                    status_code=504,
                )
            except Cad2AiError as exc:
                logger.warning("failed %s: %s", extraction.to_log_line(), exc.message)
                return _fail(exc)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - the caller wants a JSON envelope, not a traceback
                logger.exception("unexpected failure for run %s", run_id)
                return _fail(exc, code="internal_error")

            elapsed = round(time.perf_counter() - started, 3)
            body = dict(result)
            body.setdefault("ok", True)
            body.setdefault("run_id", run_id)
            body.setdefault("filename", filename)
            body.setdefault("elapsed_s", elapsed)
            body.setdefault("size_bytes", written)
            if artifact_dir is not None:
                body["artifact_dir"] = str(artifact_dir)
                body["artifact_urls"] = {
                    "analysis": f"/api/runs/{run_id}/analysis.json",
                    "payload": f"/api/runs/{run_id}/payload.json",
                    "markdown": f"/api/runs/{run_id}/report.md",
                    "manifest": f"/api/runs/{run_id}/manifest.json",
                }
            else:
                body["artifact_dir"] = None
            # The upload itself is never kept: point the client at the artifact
            # directory instead of the discarded temp file.
            body["input_retained"] = False
            logger.info("done run=%s in %.1fs", run_id, elapsed)
            return JSONResponse(content=_plain(body))
        finally:
            if acquired:
                gate.release()
            # Always drop the staged upload. ``temp_root`` holds nothing else when
            # artifacts were kept (those live under ``cfg.artifact_root``).
            shutil.rmtree(temp_root, ignore_errors=True)

    # --------------------------------------------------------------- artifacts
    def _run_dir(run_id: str) -> Path:
        if not _RUN_ID.match(run_id):
            raise HTTPException(
                status_code=400,
                detail={"ok": False, "error": {"code": "bad_run_id", "message": "run ids are 1-64 chars of [A-Za-z0-9._-]"}},
            )
        root = cfg.artifact_root.resolve()
        target = (cfg.artifact_root / run_id).resolve()
        # Belt and braces: never serve outside the artifact root.
        if target.parent != root and root not in target.parents:
            raise HTTPException(status_code=400, detail={"ok": False})
        return target

    @app.get("/api/runs/{run_id}/{artifact}")
    async def artifact(run_id: str, artifact: str) -> Any:
        """Fetch a kept artifact: ``analysis.json`` | ``payload.json`` | ``report.md`` | ``run_manifest.json``."""
        allowed = {
            "analysis.json": ("application/json", "analysis"),
            "payload.json": ("application/json", "payload"),
            "run_manifest.json": ("application/json", "manifest"),
            "manifest.json": ("application/json", "manifest"),
            "cad_model.json": ("application/json", "cad_model"),
            "report.md": ("text/markdown; charset=utf-8", "markdown"),
        }
        if artifact not in allowed:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "unknown_artifact", "known": sorted(allowed)}},
            )
        media_type, key = allowed[artifact]
        directory = _run_dir(run_id)
        # ``report.md`` is the friendly name the API exposes for the markdown the
        # pipeline writes as ``analysis.md``; accept either spelling on disk.
        for candidate in dict.fromkeys([_SERVED_AS_ON_DISK.get(artifact, artifact), artifact]):
            if (directory / candidate).is_file():
                break
        target = directory / candidate
        if not target.is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "ok": False,
                    "error": {
                        "code": "artifact_missing",
                        "message": f"no {artifact} for run {run_id}",
                        "hint": "re-upload with keep=1 (or set CAD2AI_API_KEEP=1) to retain artifacts",
                    },
                },
            )
        data = await run_in_threadpool(target.read_bytes)
        if artifact.endswith(".json"):
            try:
                return JSONResponse(content=json.loads(data.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return PlainTextResponse(data.decode("utf-8", "replace"), media_type="application/json")
        return PlainTextResponse(data.decode("utf-8", "replace"), media_type=media_type)

    @app.exception_handler(Cad2AiError)
    async def _cad2ai_handler(_request: Request, exc: Cad2AiError) -> JSONResponse:
        """Any typed error that escapes a route still leaves the caller a JSON envelope."""
        return _fail(exc)

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - passthrough
        logger.exception("unhandled error")
        return _fail(exc, code="internal_error")

    app.state.config = cfg
    app.state.settings = base_settings
    app.state.gate = gate
    return app


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    token = os.urandom(3).hex()
    return f"{stamp}-{token}"


app = create_app()


def main() -> int:
    """``python server.py`` == ``uvicorn server:app`` with the repo's defaults."""
    import uvicorn

    host = os.environ.get("CAD2AI_API_HOST", "0.0.0.0")
    port = _env_int("CAD2AI_API_PORT", 8000)
    uvicorn.run("server:app", host=host, port=port, reload=bool(os.environ.get("CAD2AI_API_RELOAD")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
