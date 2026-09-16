"""Hybrid CAD Compliance System — FastAPI orchestration backend.

The heart of the system: a 4-step pipeline executed per uploaded DWG file,
with a strict separation between deterministic math and semantic AI:

    Phase 1  Deterministic Extraction     C# / ACadSharp  -> cad_geometry.json
    Phase 2  Semantic Identification      DeepSeek        -> entity-id mapping
    Phase 3  Mathematical Verification    Shapely         -> exact setback + verdict
    Phase 4  Compliance Reporting         DeepSeek        -> formal report (prose only)

Progress is streamed to the Next.js dashboard as Server-Sent Events:

    event: pipeline_start   {report_id, source_file, phases, rule}
    event: phase            {phase, status: running|complete|failed, detail}
    event: result           {full ComplianceReport}
    event: error            {phase, message}
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app import db
from app.config import REPO_ROOT, get_settings
from app.pipeline import cad_extractor, reporting, semantic
from app.pipeline import geometry as geometry_engine
from app.pipeline.errors import PipelineError

settings = get_settings()

PIPELINE_PHASES = [
    {
        "phase": 1,
        "name": "Deterministic Extraction",
        "engine": "C# · ACadSharp",
        "description": "Parse the DWG and export exact coordinates, layers and block attributes to cad_geometry.json.",
    },
    {
        "phase": 2,
        "name": "Semantic Identification",
        "engine": "DeepSeek",
        "description": "Map entity ids to the Building Perimeter and the Boundary Wall. No measurements.",
    },
    {
        "phase": 3,
        "name": "Mathematical Verification",
        "engine": "Python · Shapely",
        "description": "Compute the exact minimum setback distance and compare it to the municipal rule.",
    },
    {
        "phase": 4,
        "name": "Compliance Reporting",
        "engine": "DeepSeek",
        "description": "Draft the formal municipality compliance report from the exact figures.",
    },
]

SAMPLE_GEOMETRY_PATH = REPO_ROOT / "samples" / "cad_geometry.example.json"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url and db.is_available():
        db.ensure_schema(settings.database_url)
    yield


app = FastAPI(
    title="Hybrid CAD Compliance API",
    version="0.1.0",
    description=(
        "Verifies building-code setbacks (e.g. 1.5 m between building perimeter "
        "and boundary wall) from raw .dwg files using a hybrid pipeline: "
        "deterministic geometry engines (C#/ACadSharp + Shapely) for all math, "
        "DeepSeek strictly for semantics and prose."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Helpers -------------------------------------------------------------------


def _sse(event: str, payload: dict | str) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return f"event: {event}\ndata: {data}\n\n"


def _safe_filename(filename: str, fallback: str) -> str:
    cleaned = "".join(c for c in Path(filename).name if c.isalnum() or c in "._-")
    return cleaned or fallback


def _phase_event(phase: int, status: str, detail: dict | None = None) -> str:
    return _sse("phase", {"phase": phase, "status": status, "detail": detail or {}})


async def _read_upload(file: UploadFile, allowed_suffixes: set[str]) -> tuple[str, bytes]:
    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or '(none)'}'. "
            f"Allowed: {', '.join(sorted(allowed_suffixes))}",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    max_bytes = settings.upload_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.upload_max_mb} MB upload limit.",
        )
    return filename, content


def _geometry_summary(geometry: dict) -> dict:
    metadata = geometry.get("metadata") or {}
    return {
        "entities": len(geometry.get("entities", [])),
        "texts": len(geometry.get("texts", [])),
        "blocks": len(geometry.get("blocks", [])),
        "layers": len(geometry.get("layers", [])),
        "units": metadata.get("units", "Unknown"),
        "dwg_version": metadata.get("dwg_version", "unknown"),
    }


# --- Core orchestration ----------------------------------------------------------


async def _stream_pipeline(
    *,
    source_file: str,
    geometry_provider: Callable[[], Awaitable[dict]],
    bypass_phase1: bool = False,
) -> AsyncGenerator[str, None]:
    """Run all four phases, streaming SSE progress events."""
    report_id = str(uuid.uuid4())
    yield _sse(
        "pipeline_start",
        {
            "report_id": report_id,
            "source_file": source_file,
            "phases": PIPELINE_PHASES,
            "rule": {
                "type": "minimum_setback",
                "required_meters": settings.min_setback_meters,
            },
        },
    )

    # -- Phase 1: deterministic extraction (C# / ACadSharp) --------------------
    yield _phase_event(1, "running")
    try:
        geometry = await geometry_provider()
    except PipelineError as exc:
        yield _phase_event(1, "failed", {"message": exc.message})
        yield _sse("error", {"phase": 1, "message": exc.message})
        return
    except Exception as exc:  # defensive: never leak a raw traceback mid-stream
        yield _phase_event(1, "failed", {"message": f"Unexpected error: {exc}"})
        yield _sse("error", {"phase": 1, "message": f"Unexpected error: {exc}"})
        return
    yield _phase_event(
        1, "complete", {"summary": _geometry_summary(geometry), "bypassed": bypass_phase1}
    )

    # -- Phase 2: semantic identification (DeepSeek) ---------------------------
    yield _phase_event(2, "running")
    try:
        mapping = await asyncio.to_thread(semantic.identify_entities, geometry, settings)
    except PipelineError as exc:
        yield _phase_event(2, "failed", {"message": exc.message})
        yield _sse("error", {"phase": 2, "message": exc.message})
        return
    yield _phase_event(
        2,
        "complete",
        {
            "building_lines": mapping["building_lines"],
            "boundary_lines": mapping["boundary_lines"],
            "rationale": mapping["rationale"],
        },
    )

    # -- Phase 3: mathematical verification (Shapely) --------------------------
    yield _phase_event(3, "running")
    try:
        verification = await asyncio.to_thread(
            geometry_engine.verify_setback,
            geometry,
            mapping,
            settings.min_setback_meters,
        )
    except PipelineError as exc:
        yield _phase_event(3, "failed", {"message": exc.message})
        yield _sse("error", {"phase": 3, "message": exc.message})
        return
    yield _phase_event(
        3,
        "complete",
        {
            "verdict": verification["verdict"],
            "min_distance_m": verification["min_distance_m"],
            "required_distance_m": verification["required_distance_m"],
            "margin_m": verification["margin_m"],
        },
    )

    # -- Phase 4: compliance reporting (DeepSeek) ------------------------------
    yield _phase_event(4, "running")
    try:
        report_markdown = await asyncio.to_thread(
            reporting.generate_report,
            report_id=report_id,
            source_file=source_file,
            mapping=mapping,
            verification=verification,
            settings=settings,
        )
    except PipelineError as exc:
        yield _phase_event(4, "failed", {"message": exc.message})
        yield _sse("error", {"phase": 4, "message": exc.message})
        return
    yield _phase_event(4, "complete", {"report_length": len(report_markdown)})

    # -- Persist (optional) and stream the final result --------------------------
    report = {
        "report_id": report_id,
        "verdict": verification["verdict"],
        "source_file": source_file,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verification": verification,
        "mapping": mapping,
        "report_markdown": report_markdown,
        "persisted_to_database": False,
        "cad_metadata": geometry.get("metadata", {}),
    }
    report["persisted_to_database"] = await asyncio.to_thread(
        db.save_report, settings.database_url, report
    )
    yield _sse("result", report)


# --- HTTP endpoints ----------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "min_setback_meters": settings.min_setback_meters,
        "ai_mode": "mock" if settings.ai_is_mocked else "deepseek",
        "database_configured": bool(settings.database_url),
    }


@app.get("/api/pipeline/phases")
async def pipeline_phases() -> dict:
    return {
        "phases": PIPELINE_PHASES,
        "rule": {
            "type": "minimum_setback",
            "required_meters": settings.min_setback_meters,
        },
    }


@app.get("/api/sample-geometry")
async def sample_geometry():
    """Bundled cad_geometry.json sample for demos/tests without a DWG file."""
    if not SAMPLE_GEOMETRY_PATH.exists():
        raise HTTPException(status_code=404, detail="Sample geometry not found.")
    return JSONResponse(json.loads(SAMPLE_GEOMETRY_PATH.read_text()))


@app.post("/api/pipeline/run")
async def run_pipeline(file: UploadFile = File(...)):
    """Full 4-phase pipeline for an uploaded .dwg (or .dxf) file."""
    filename, content = await _read_upload(file, {".dwg", ".dxf"})
    safe_name = _safe_filename(filename, "drawing.dwg")

    async def provider() -> dict:
        with tempfile.TemporaryDirectory(prefix="cad-compliance-") as tmp:
            dwg_path = Path(tmp) / safe_name
            dwg_path.write_bytes(content)
            return await cad_extractor.extract_geometry(dwg_path, settings)

    return StreamingResponse(
        _stream_pipeline(source_file=filename, geometry_provider=provider),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/pipeline/run-json")
async def run_pipeline_json(file: UploadFile = File(...)):
    """Phases 2–4 from a pre-extracted cad_geometry.json (Phase 1 bypassed).

    Useful for testing the AI + math stages without the .NET toolchain.
    """
    filename, content = await _read_upload(file, {".json"})

    async def provider() -> dict:
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise PipelineError(1, f"Uploaded JSON is invalid: {exc}") from None

    return StreamingResponse(
        _stream_pipeline(
            source_file=filename, geometry_provider=provider, bypass_phase1=True
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/pipeline/run-sample")
async def run_pipeline_sample():
    """Phases 2–4 against the bundled sample geometry (demo mode)."""

    async def provider() -> dict:
        if not SAMPLE_GEOMETRY_PATH.exists():
            raise PipelineError(1, "samples/cad_geometry.example.json is missing.")
        return json.loads(SAMPLE_GEOMETRY_PATH.read_text())

    return StreamingResponse(
        _stream_pipeline(
            source_file="cad_geometry.example.json (sample)",
            geometry_provider=provider,
            bypass_phase1=True,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
