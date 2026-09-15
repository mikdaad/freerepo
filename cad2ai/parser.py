"""Phase 1 -- lossless DWG parsing (ezdxf + the ``odafc`` addon).

Why this module exists
----------------------
Generic "DWG -> DXF" converters throw away exactly the metadata that makes a
drawing analyzable (layer table state, linetypes, dimension-style overrides,
block attribute definitions, proxy objects).  ``ezdxf`` keeps all of it, but it
cannot read DWG by itself; the ``ezdxf.addons.odafc`` addon bridges that by
driving the ODA File Converter and handing the result back as a real
:class:`ezdxf.document.Drawing` object graph.  We therefore use

    doc = odafc.readfile('drawing.dwg')            # primary path, per spec

and only fall back to explicit conversion + robust loading when the primary
path trips a known ezdxf loader bug (non-ASCII content in ACIS data -- see
ezdxf issue #690) or a structure error.

Guarantees this module makes
----------------------------
* **Fail fast on version**: the AC10xx header is inspected first, so
  unparseable generations produce :class:`UnsupportedDwgVersionError` without
  spawning a subprocess.
* **Typed errors**: every ``odafc``/``ezdxf`` failure mode is translated into a
  :class:`~cad2ai.errors.Cad2AiError` with a remediation hint.
* **Never partial-silent**: recovered/audited problems surface in
  :attr:`ParsedDrawing.warnings`, and the DXF that was actually parsed can be
  kept on disk for post-mortems (``keep_converted_dxf``).
* **Bounded**: file-size guard before touching disk-heavy conversion, and an
  optional wall-clock timeout so a wedged converter cannot hang a worker
  forever.
"""

from __future__ import annotations

import enum
import logging
import os
import platform
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from cad2ai import dwg_version
from cad2ai.config import Settings
from cad2ai.dxfutils import Warnings, dxf_attr, sha256_prefix
from cad2ai.errors import (
    CorruptCadFileError,
    DwgConverterError,
    DwgConverterNotInstalledError,
    InputFileError,
    NotACadFileError,
    ParseError,
    UnsupportedDwgVersionError,
)

logger = logging.getLogger("cad2ai.parser")

__all__ = [
    "AuditSummary",
    "Backend",
    "CorruptCadFileError",
    "DwgConverterError",
    "DwgConverterNotInstalledError",
    "ParsedDrawing",
    "describe_backend_availability",
    "load_drawing",
    "read_dxf_robust",
    "temp_workspace",
]

DXF_SUFFIXES = {".dxf"}
DWG_SUFFIXES = {".dwg"}
OTHER_CAD_SUFFIXES = {".dxb"}


class Backend(str, enum.Enum):
    """Which loader produced the document."""

    ODA_READFILE = "odafc.readfile"
    ODA_CONVERT = "odafc.convert+ezdxf"
    #: converter output needed ezdxf's tolerant reader (content may be repaired)
    ODA_RECOVERED = "odafc.convert+ezdxf.recover"
    EZDXF = "ezdxf.readfile"
    EZDXF_RECOVER = "ezdxf.recover.readfile"

    @property
    def lossless(self) -> bool:
        """``True`` when the ezdxf object graph (not a JSON manifest) backs it."""
        return self in (
            Backend.ODA_READFILE,
            Backend.ODA_CONVERT,
            Backend.ODA_RECOVERED,
            Backend.EZDXF,
            Backend.EZDXF_RECOVER,
        )


@dataclass
class AuditSummary:
    """Result of ``doc.audit()`` -- how repairable the source file was."""

    errors: list[dict[str, Any]] = field(default_factory=list)
    fixes: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"errors": self.errors[:40], "error_count": len(self.errors), "fixes": self.fixes}


@dataclass
class ParsedDrawing:
    """Everything Phase 2 needs, plus provenance for the run manifest."""

    doc: Any
    source: Path
    backend: Backend
    dwg: dwg_version.DwgVersionInfo | None = None
    warnings: list[str] = field(default_factory=list)
    audit: AuditSummary | None = None
    converted_dxf: Path | None = None
    size_bytes: int = 0
    sha256: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    #: set when Phase 1 came from the Autodesk fallback instead of a real file
    provenance: str = "local"

    @property
    def is_dwg(self) -> bool:
        return self.source.suffix.lower() in DWG_SUFFIXES

    @property
    def dxfversion(self) -> str | None:
        return getattr(self.doc, "dxfversion", None)

    @property
    def acad_release(self) -> str | None:
        return getattr(self.doc, "acad_release", None)

    def summary(self) -> dict[str, Any]:
        """Small, log-safe description (never contains geometry)."""
        doc = self.doc
        try:
            entity_count = len(doc.modelspace())
        except Exception:  # pragma: no cover - defensive
            entity_count = None
        return {
            "source": str(self.source),
            "backend": self.backend.value,
            "provenance": self.provenance,
            "dwg": self.dwg.as_dict() if self.dwg else None,
            "dxf_version": self.dxfversion,
            "acad_release": self.acad_release,
            "modelspace_entities": entity_count,
            "layer_count": _table_len(doc, "layers"),
            "block_count": _table_len(doc, "blocks"),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "audit": self.audit.as_dict() if self.audit else None,
            "warnings": list(self.warnings),
            "timings_ms": {key: round(value * 1000, 1) for key, value in self.timings.items()},
        }


def _table_len(doc: Any, attribute: str) -> int | None:
    table = getattr(doc, attribute, None)
    if table is None:
        return None
    try:
        return len(table)
    except TypeError:  # pragma: no cover - exotic table objects
        try:
            return sum(1 for _ in table)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# availability probing (used by `main.py doctor` and by --fallback logic)
# ---------------------------------------------------------------------------


def _import_odafc() -> Any:
    try:
        from ezdxf.addons import odafc  # type: ignore
    except ImportError as exc:  # pragma: no cover - ezdxf too old / partial install
        raise DwgConverterNotInstalledError(
            f"the ezdxf odafc addon is not importable ({exc}); install ezdxf>=1.1",
            details={"exception": str(exc)},
        ) from exc
    return odafc


def describe_backend_availability() -> dict[str, Any]:
    """Report what Phase 1 can do on this machine (no conversion performed)."""
    report: dict[str, Any] = {
        "platform": platform.system(),
        "ezdxf_version": None,
        "oda_installed": False,
        "oda_executable": None,
        "xvfb_available": shutil.which("Xvfb") is not None,
        "notes": [],
    }
    try:
        import ezdxf

        report["ezdxf_version"] = ".".join(str(part) for part in ezdxf.version[:3])
    except ImportError:  # pragma: no cover
        report["notes"].append("ezdxf is not installed")
        return report
    try:
        odafc = _import_odafc()
    except DwgConverterNotInstalledError as exc:
        report["notes"].append(exc.message)
        return report
    try:
        report["oda_installed"] = bool(odafc.is_installed())
    except Exception as exc:  # pragma: no cover - defensive
        report["notes"].append(f"ODA detection failed: {exc}")
    try:
        if report["oda_installed"]:
            path = odafc._get_odafc_path(platform.system())  # noqa: SLF001 - documented addon API gap
            report["oda_executable"] = str(path)
    except Exception:  # pragma: no cover
        pass
    if not report["oda_installed"]:
        report["notes"].append(
            "ODA File Converter not found: DWG input needs it (or use --fallback aps / pre-convert to DXF)"
        )
    if report["oda_installed"] and report["platform"] == "Linux" and not report["xvfb_available"]:
        report["notes"].append("install xvfb so the ODA converter does not try to open a GUI on Linux")
    return report


def _apply_oda_executable(odafc: Any, executable: str | None, warnings: Warnings) -> None:
    """Point the addon at an explicit ODA binary (AppImage / Windows path)."""
    if not executable:
        return
    path = Path(executable).expanduser()
    if not path.exists():
        warnings.add(f"ODA_EXECUTABLE does not exist: {path}")
        return
    section = "odafc-addon"
    key = "win_exec_path" if platform.system() == "Windows" else "unix_exec_path"
    try:
        import ezdxf

        ezdxf.options.set(section, key, str(path.absolute()))
        logger.debug("set %s.%s = %s", section, key, path)
    except Exception as exc:  # pragma: no cover - ezdxf option plumbing changed
        warnings.add(f"could not configure ODA executable ({exc}); relying on PATH")


def _preserve_proxy_graphics(warnings: Warnings) -> None:
    """Keep proxy graphics objects instead of dropping them at load time.

    This is the "lossless" part of the brief: proxy entities carry data from
    verticals (Civil 3D, Plant 3D, Mechanical) that a naive converter discards.
    """
    try:
        import ezdxf

        ezdxf.options.preserve_proxy_graphics(True)
    except Exception as exc:  # pragma: no cover - very old ezdxf
        warnings.add(f"could not enable proxy graphic preservation: {exc}")


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def load_drawing(
    path: str | os.PathLike[str],
    *,
    backend: str = "auto",
    target_version: str | None = None,
    audit: bool = True,
    allow_legacy_versions: bool = False,
    max_file_mb: float | None = None,
    keep_converted_dxf: str | os.PathLike[str] | None = None,
    oda_executable: str | None = None,
    oda_timeout: float | None = None,
    settings: Any | None = None,
) -> ParsedDrawing:
    """Parse a DWG/DXF into an ezdxf document.

    Args:
        path: ``.dwg`` / ``.dxf`` / ``.dxb`` file.
        backend: ``"auto"`` (DWG -> ODA, DXF -> ezdxf), ``"oda"`` or ``"dxf"``.
        target_version: DXF version the ODA converter targets; defaults to
            ``ACAD2018`` (``AC1032``), the newest version ezdxf represents.
        audit: run ``doc.audit()`` and report (not raise) structural problems.
        allow_legacy_versions: accept pre-R2000 DWGs that lose fidelity.
        max_file_mb: hard size guard before conversion.
        keep_converted_dxf: directory to keep the intermediate DXF in.
        oda_executable: explicit path to ``ODAFileConverter``.
        oda_timeout: wall-clock guard for the conversion step (seconds);
            ``None`` takes ``CAD2AI_ODA_TIMEOUT`` from *settings* or 300 s.
        settings: optional :class:`~cad2ai.config.Settings` supplying defaults
            for the arguments above (explicit args win).

    Returns:
        :class:`ParsedDrawing`.

    Raises:
        cad2ai.errors.InputFileError, NotACadFileError,
        UnsupportedDwgVersionError, DwgConverterNotInstalledError,
        DwgConverterError, CorruptCadFileError.
    """
    warnings = Warnings()
    timings: dict[str, float] = {}

    # Explicit arguments always win; ``settings`` (or the built-in defaults)
    # fill in whatever was left as ``None``.
    defaults = settings if settings is not None else Settings()
    target_version = target_version or defaults.oda_target_version
    allow_legacy_versions = bool(allow_legacy_versions or defaults.allow_legacy_versions)
    if max_file_mb is None:
        max_file_mb = defaults.max_file_mb
    if oda_timeout is None:
        oda_timeout = defaults.oda_timeout
    oda_executable = oda_executable or defaults.oda_executable

    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise InputFileError(f"input file does not exist: {file_path}", path=file_path)
    if file_path.is_dir():
        raise InputFileError(f"input path is a directory, not a CAD file: {file_path}", path=file_path)

    started = time.perf_counter()
    size_bytes = file_path.stat().st_size
    if size_bytes == 0:
        raise InputFileError(f"input file is empty: {file_path}", path=file_path)
    if size_bytes > max_file_mb * 1024 * 1024:
        raise InputFileError(
            f"input file is {size_bytes / 1024 / 1024:.1f} MB, above the {max_file_mb} MB guard",
            path=file_path,
            hint="raise CAD2AI_MAX_FILE_MB, or use the APS fallback for very large drawings",
        )
    timings["stat"] = time.perf_counter() - started

    suffix = file_path.suffix.lower()
    if suffix not in DXF_SUFFIXES | DWG_SUFFIXES | OTHER_CAD_SUFFIXES:
        raise NotACadFileError(
            f"unsupported file extension {suffix or '<none>'!r}: expected .dwg, .dxf or .dxb",
            details={"path": str(file_path), "suffix": suffix},
        )

    if backend == "auto":
        backend = "oda" if suffix in DWG_SUFFIXES | {".dxb"} else "dxf"
    if backend not in ("oda", "dxf"):
        raise ParseError(f"unknown backend {backend!r} (expected 'auto', 'oda' or 'dxf')")

    if backend == "oda":
        parsed = _load_via_oda(
            file_path,
            target_version=target_version or "ACAD2018",
            audit=audit,
            allow_legacy_versions=allow_legacy_versions,
            keep_dir=keep_converted_dxf,
            oda_executable=oda_executable,
            oda_timeout=oda_timeout,
            warnings=warnings,
            timings=timings,
            size_bytes=size_bytes,
        )
    else:
        parsed = _load_via_ezdxf(
            file_path,
            audit=audit,
            warnings=warnings,
            timings=timings,
            size_bytes=size_bytes,
            allow_legacy_versions=allow_legacy_versions,
        )
    if audit:
        parsed.audit = _audit_document(parsed.doc, warnings)
    parsed.warnings = warnings.as_list()
    parsed.timings = timings
    logger.debug("parsed %s via %s", file_path.name, parsed.backend.value)
    return parsed


# ---------------------------------------------------------------------------
# ODA path
# ---------------------------------------------------------------------------


def _load_via_oda(
    file_path: Path,
    *,
    target_version: str,
    audit: bool,
    allow_legacy_versions: bool,
    keep_dir: str | os.PathLike[str] | None,
    oda_executable: str | None,
    oda_timeout: float | None,
    warnings: Warnings,
    timings: dict[str, float],
    size_bytes: int,
) -> ParsedDrawing:
    _preserve_proxy_graphics(warnings)
    odafc = _import_odafc()
    _apply_oda_executable(odafc, oda_executable, warnings)

    sentinel, info = dwg_version.sniff_result(file_path)
    started = time.perf_counter()
    warnings.extend(dwg_version.enforce_policy(info, source=file_path, allow_legacy=allow_legacy_versions))
    timings["version_check"] = time.perf_counter() - started

    try:
        installed = bool(odafc.is_installed())
    except Exception as exc:  # pragma: no cover - addon probing failure
        raise DwgConverterError(f"ODA File Converter detection failed: {exc}") from exc
    if not installed:
        raise DwgConverterNotInstalledError(
            f"reading {file_path.name} requires the ODA File Converter, which was not found",
            details={"expected": "ODAFileConverter on PATH or ODA_EXECUTABLE"},
        )

    # Primary path, exactly as specified in the brief.
    started = time.perf_counter()
    try:
        doc = _run_bounded(
            lambda: odafc.readfile(str(file_path), version=target_version, audit=audit),
            timeout=oda_timeout,
            label=f"odafc.readfile({file_path.name})",
        )
        backend = Backend.ODA_READFILE
        converted: Path | None = None
    except (UnicodeError, UnicodeDecodeError, ValueError) as exc:
        # Known ezdxf loader limitation (ACIS/MTEXT surrogate escapes): convert
        # explicitly and read with a tolerant codec.
        warnings.add(
            f"odafc.readfile failed while decoding the converted DXF ({exc}); "
            "retrying with odafc.convert + errors='ignore'"
        )
        doc, converted, backend = _oda_convert_and_read(
            odafc,
            file_path,
            target_version=target_version,
            audit=audit,
            keep_dir=keep_dir,
            oda_timeout=oda_timeout,
            warnings=warnings,
        )
    except UnsupportedDwgVersionError:
        raise
    except Exception as exc:  # noqa: BLE001 - every odafc failure is mapped
        raise _map_odafc_error(exc, file_path=file_path, info=info, sentinel=sentinel) from exc
    timings["oda_convert"] = time.perf_counter() - started

    _note_document_version(doc, info, warnings)
    return ParsedDrawing(
        doc=doc,
        source=file_path,
        backend=backend,
        dwg=info,
        converted_dxf=converted,
        size_bytes=size_bytes,
        sha256=sha256_prefix(file_path),
    )


def _oda_convert_and_read(
    odafc: Any,
    file_path: Path,
    *,
    target_version: str,
    audit: bool,
    keep_dir: str | os.PathLike[str] | None,
    oda_timeout: float | None,
    warnings: Warnings,
) -> tuple[Any, Path | None, Backend]:
    """Convert to DXF ourselves so we control decoding and can keep the file."""
    owns_dir = keep_dir is None
    out_dir = Path(keep_dir) if keep_dir is not None else Path(tempfile.mkdtemp(prefix="cad2ai-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (file_path.stem + ".dxf")
    try:
        _run_bounded(
            lambda: odafc.convert(str(file_path), str(target), version=target_version, audit=audit, replace=True),
            timeout=oda_timeout,
            label=f"odafc.convert({file_path.name})",
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_odafc_error(exc, file_path=file_path, info=None, sentinel=None) from exc
    if not target.exists():
        raise CorruptCadFileError(
            f"ODA File Converter produced no output for {file_path.name}",
            hint="the converter writes <input>.dxf into the output folder; check that the file is not locked",
            details={"expected": str(target)},
        )
    doc, loaded_with = read_dxf_robust(target, warnings=warnings)
    # The document came out of the ODA converter either way; ``loaded_with`` only
    # records whether ezdxf needed its tolerant loader, which the warnings carry.
    backend = Backend.ODA_RECOVERED if loaded_with is Backend.EZDXF_RECOVER else Backend.ODA_CONVERT
    if owns_dir:
        # The temporary directory is removed once the DXF has been parsed.
        warnings.add(f"intermediate DXF discarded (pass keep_converted_dxf=<dir> to retain it): {target.name}")
        shutil.rmtree(out_dir, ignore_errors=True)
    return doc, None if owns_dir else target, backend


def _map_odafc_error(exc: Exception, *, file_path: Path, info: Any, sentinel: str | None) -> ParseError:
    """Translate ``odafc`` exceptions into the typed error hierarchy."""
    module_name = type(exc).__module__ or ""
    name = type(exc).__name__
    message = str(exc) or name
    lowered = message.lower()
    base = {"path": str(file_path), "converter_error": message[:400]}

    if name == "ODAFCNotInstalledError":
        return DwgConverterNotInstalledError(f"{file_path.name}: {message}", details=base)
    if (
        name in ("UnsupportedVersion",)
        or "unsupported version" in lowered
        or "unsupported dwg" in lowered
        or "version is not supported" in lowered
        or "not supported by this converter" in lowered
        or "out of range" in lowered and "version" in lowered
    ):
        return UnsupportedDwgVersionError(
            f"{file_path.name}: the ODA File Converter rejected this DWG version ({message})",
            sentinel=sentinel or (info.sentinel if info else None),
            release=info.release if info else None,
            hint=(
                "re-save the drawing as DWG 2018 (AC1032) with a matching ODA/AutoCAD version, "
                "update the ODA File Converter, or run with --fallback aps"
            ),
            details=base,
        )
    if name == "UnsupportedFileFormat":
        return NotACadFileError(f"{file_path.name}: {message}", details=base)
    if name == "UnsupportedPlatform":
        return DwgConverterError(f"ODA File Converter does not support {platform.system()}: {message}", details=base)
    if "timeout" in lowered or isinstance(exc, TimeoutError):
        return DwgConverterError(
            f"converting {file_path.name} timed out: {message}",
            hint="increase CAD2AI_ODA_TIMEOUT or run conversion on a dedicated worker",
            details=base,
        )
    if isinstance(exc, FileNotFoundError):
        return InputFileError(f"ODA File Converter could not read {file_path.name}: {message}", details=base)
    if "recover" in lowered or "invalid" in lowered or "corrupt" in lowered:
        return CorruptCadFileError(f"{file_path.name}: unrecoverable structure error ({message})", details=base)
    return DwgConverterError(
        f"ODA File Converter failed on {file_path.name}: {message}",
        hint="run `main.py doctor` to check the converter installation, or retry with --fallback aps",
        details={**base, "exception_module": module_name},
    )


def _note_document_version(doc: Any, info: Any, warnings: Warnings) -> None:
    """Warn when the loaded document disagrees with the file header."""
    doc_sentinel = getattr(doc, "drawing_version", None)
    if info is None or not doc_sentinel:
        return
    if doc_sentinel != info.sentinel:
        warnings.add(
            f"document loaded as DXF {doc_sentinel} while the DWG header says {info.sentinel}: "
            "version down-levelling occurred; proxy objects may have been simplified"
        )


# ---------------------------------------------------------------------------
# DXF path (+ robust loader shared with the ODA fallback)
# ---------------------------------------------------------------------------


def _recover_readfile(target: str, warnings: Warnings, *, last_error_hint: bool = False) -> Any:
    """``ezdxf.recover.readfile`` wrapper returning the document only."""
    from ezdxf import recover as ezdxf_recover

    result = ezdxf_recover.readfile(target)
    if isinstance(result, tuple):
        doc, status = (result + (None,))[:2]
        problems = list(getattr(status, "errors", None) or [])
        fixes = list(getattr(status, "fixes", None) or [])
        if problems or fixes:
            warnings.add(
                f"ezdxf.recover repaired the DXF: {len(problems)} error(s), {len(fixes)} fix(es)"
                + (f"; first: {problems[0]}" if problems else "")
            )
        return doc
    return result


def read_dxf_robust(
    path: str | Path,
    *,
    warnings: Warnings | None = None,
    encoding: str | None = None,
) -> tuple[Any, Backend]:
    """Load a DXF with escalating tolerance (readfile -> tolerant -> recover).

    ``ezdxf.recover`` repairs structure but can silently drop content, so it is
    only reached when the strict loads fail, and the fallback is always
    reported as a warning.
    """
    warnings = warnings if warnings is not None else Warnings()
    import ezdxf

    target = str(path)
    attempts: list[tuple[Backend, Callable[[], Any]]] = [
        (Backend.EZDXF, lambda: ezdxf.readfile(target, encoding=encoding) if encoding else ezdxf.readfile(target)),
        (Backend.EZDXF, lambda: ezdxf.readfile(target, errors="ignore")),
        # ``recover.readfile`` returns ``(document, audit_status)`` -- unpack it,
        # otherwise a tuple leaks into the whole pipeline as "the document".
        (Backend.EZDXF_RECOVER, lambda: _recover_readfile(target, warnings, last_error_hint=True)),
    ]
    last_error: Exception | None = None
    for index, (backend, loader) in enumerate(attempts):
        try:
            doc = loader()
        except Exception as exc:  # noqa: BLE001 - mapped below
            last_error = exc
            continue
        if backend is Backend.EZDXF_RECOVER or index > 0:
            warnings.add(
                f"DXF loaded with reduced strictness ({backend.value}, attempt {index + 1}); "
                f"some entities may have been repaired or dropped: {exc_text(last_error)}"
            )
        return doc, backend
    raise CorruptCadFileError(
        f"could not load DXF {path}: {exc_text(last_error)}",
        hint="open and re-save the file in AutoCAD, or use the APS fallback",
        details={"path": str(path), "exception": exc_text(last_error)},
    )


def exc_text(exc: BaseException | None) -> str:
    return f"{type(exc).__name__}: {exc}" if exc is not None else "unknown error"


def _load_via_ezdxf(
    file_path: Path,
    *,
    audit: bool,
    warnings: Warnings,
    timings: dict[str, float],
    size_bytes: int,
    allow_legacy_versions: bool,
) -> ParsedDrawing:
    _preserve_proxy_graphics(warnings)
    backend_enum = Backend.EZDXF
    doc: Any = None
    started = time.perf_counter()
    if file_path.suffix.lower() in DWG_SUFFIXES:
        # A .dwg opened with the "dxf" backend is a user error worth naming.
        raise NotACadFileError(
            f"{file_path.name} is a DWG but backend='dxf' was requested",
            hint="use backend='oda' (default for .dwg) or convert to DXF first",
        )
    doc, backend_enum = read_dxf_robust(file_path, warnings=warnings)
    timings["dxf_read"] = time.perf_counter() - started
    sentinel = getattr(doc, "drawing_version", None)
    info = dwg_version.describe(sentinel) if sentinel else None
    if info is not None:
        try:
            warnings.extend(
                dwg_version.enforce_policy(info, source=file_path, allow_legacy=allow_legacy_versions)
            )
        except UnsupportedDwgVersionError as exc:
            # DXF is always at least representable; downgrade to a warning.
            warnings.add(f"legacy DXF version accepted: {exc.message}")
    return ParsedDrawing(
        doc=doc,
        source=file_path,
        backend=backend_enum,
        dwg=info,
        size_bytes=size_bytes,
        sha256=sha256_prefix(file_path),
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _audit_document(doc: Any, warnings: Warnings) -> AuditSummary | None:
    """Run ``doc.audit()`` and summarise it (never raises)."""
    audit_fn = getattr(doc, "audit", None)
    if not callable(audit_fn):
        return None
    started = time.perf_counter()
    try:
        auditor = audit_fn()
    except Exception as exc:  # noqa: BLE001
        warnings.add(f"audit skipped: {exc_text(exc)}")
        return None
    errors: list[dict[str, Any]] = []
    for item in getattr(auditor, "errors", []) or []:
        errors.append(
            {
                "code": getattr(item, "code", None),
                "message": str(getattr(item, "message", item))[:300],
                "handle": dxf_attr(item, "handle") or getattr(item, "handle", None),
            }
        )
    fixes = len(getattr(auditor, "fixes", []) or [])
    if errors:
        warnings.add(f"audit found {len(errors)} structural error(s) and applied {fixes} fix(es)")
    logger.debug("audit: %d errors, %d fixes (%.2fs)", len(errors), fixes, time.perf_counter() - started)
    return AuditSummary(errors=errors, fixes=fixes)


def _run_bounded(action: Callable[[], Any], *, timeout: float | None, label: str) -> Any:
    """Run ``action`` with a wall-clock guard.

    The ODA File Converter is a GUI application driven over ``subprocess`` with
    no timeout support, so a wedged converter would otherwise hang the worker.
    On timeout the calling thread returns with a :class:`DwgConverterError`;
    the child process is left to finish on its own (Python cannot interrupt
    ``subprocess.run`` safely) -- container-level limits are the real mitigation
    and this guard only protects the caller's SLA.
    """
    if not timeout:
        return action()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="oda") as pool:
        future = pool.submit(action)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            raise DwgConverterError(
                f"{label} exceeded the {timeout:.0f}s CAD2AI_ODA_TIMEOUT",
                hint="the ODA converter may be waiting on a GUI; install xvfb / use a headless AppImage",
                details={"timeout_seconds": timeout, "action": label},
            ) from exc
        except Exception:
            raise


def temp_workspace(prefix: str = "cad2ai-") -> Path:
    """Create a caller-owned temporary directory (kept, not auto-removed)."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    logger.debug("workspace %s", path)
    return path
