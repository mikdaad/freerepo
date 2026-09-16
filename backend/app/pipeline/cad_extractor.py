"""Phase 1 — Deterministic Extraction.

Invokes the C# `cad-engine` CLI (ACadSharp) as a subprocess and returns the
parsed `cad_geometry.json`. The Python backend never parses DWG bytes itself:
every coordinate that enters this pipeline was produced by deterministic .NET
code, which is exactly what keeps LLM hallucination out of the math.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from app.config import Settings

from .errors import PipelineError

PHASE = 1


def _resolve_command(settings: Settings) -> list[str]:
    """Locate the C# engine: published binary first, `dotnet run` as fallback."""
    if settings.cad_engine_bin:
        binary = Path(settings.cad_engine_bin).expanduser()
        if binary.exists():
            return [str(binary)]
        raise PipelineError(
            PHASE, f"CAD_ENGINE_BIN is set but the binary was not found: {binary}"
        )

    dotnet = shutil.which("dotnet")
    project_file = settings.cad_engine_project / "CadEngine.csproj"
    if dotnet and project_file.exists():
        return [
            dotnet,
            "run",
            "--project",
            str(settings.cad_engine_project),
            "-c",
            "Release",
            "--",
        ]

    raise PipelineError(
        PHASE,
        "C# CAD engine unavailable. Build it (see README.md: "
        "`cd cad-engine/CadEngine && dotnet publish -c Release`) and set "
        "CAD_ENGINE_BIN, or install the .NET 8 SDK so `dotnet run` works.",
    )


async def extract_geometry(dwg_path: Path, settings: Settings) -> dict:
    """Run the C# engine on `dwg_path` and return the parsed geometry JSON."""
    output_path = dwg_path.with_name(f"{dwg_path.stem}.cad_geometry.json")
    command = [*_resolve_command(settings), str(dwg_path), str(output_path)]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=settings.cad_engine_timeout_s
        )
    except asyncio.TimeoutError:
        process.kill()
        raise PipelineError(
            PHASE,
            f"CAD engine timed out after {settings.cad_engine_timeout_s}s",
        ) from None

    if process.returncode != 0 or not output_path.exists():
        detail = (
            stderr.decode(errors="replace").strip()
            or stdout.decode(errors="replace").strip()
            or f"exit code {process.returncode}"
        )
        raise PipelineError(PHASE, f"CAD engine failed: {detail[-2000:]}")

    try:
        return json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        raise PipelineError(
            PHASE, f"cad_geometry.json produced by the C# engine is invalid: {exc}"
        ) from None
