"""DWG header sniffing and version policy.

A DWG file starts with a 6-byte ASCII *version sentinel* (``AC10xx``).  Reading
those bytes costs microseconds and lets the pipeline refuse files the parser
stack cannot represent **before** launching the ODA File Converter, which is
the difference between a clean error and a 40-second subprocess timeout with a
cryptic exit code.

The table below is the publicly documented AutoCAD/ODA mapping.  Two ranges
matter for us:

``oda_import_min`` / ``oda_import_max``
    what ODA File Converter can read (and therefore what ``odafc.readfile``
    can hand to ezdxf).
``ezdxf_max``
    what ezdxf can *represent* (DXF R2018 == DWG AC1032).  Newer sentinels are
    still readable: the converter down-levels them to AC1032 first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cad2ai.errors import NotACadFileError, UnsupportedDwgVersionError

__all__ = [
    "DwgVersionInfo",
    "SNIFF_BYTES",
    "VERSIONS",
    "describe",
    "enforce_policy",
    "read_sentinel",
    "sniff_file",
]

SNIFF_BYTES = 6

#: ODA File Converter can import anything from R13 up to the current release.
ODA_IMPORT_MIN = "AC1012"
#: Newest sentinel that ezdxf can represent natively (DXF R2018).
EZDXF_MAX_REPRESENTABLE = "AC1032"
#: Newest sentinel known to this build of cad2ai.  Anything above it is
#: "newer than our tested baseline": we still try, but we warn.
NEWEST_KNOWN = "AC1036"

_AC_SENTINEL = re.compile(rb"^AC10\d{2}$")


@dataclass(frozen=True)
class DwgVersionInfo:
    """Static description of one DWG format generation."""

    sentinel: str
    release: str
    years: str
    #: numeric sort key (the trailing digits of the sentinel)
    order: int

    @property
    def ezdxf_representable(self) -> bool:
        return _num(self.sentinel) <= _num(EZDXF_MAX_REPRESENTABLE)

    @property
    def known(self) -> bool:
        return _num(self.sentinel) <= _num(NEWEST_KNOWN)

    @property
    def dxf_version(self) -> str:
        """Matching ezdxf DXF version string (best effort)."""
        return DXF_FOR_SENTINEL.get(self.sentinel, "AC1032")

    def as_dict(self) -> dict[str, Any]:
        return {
            "sentinel": self.sentinel,
            "release": self.release,
            "years": self.years,
            "ezdxf_representable": self.ezdxf_representable,
            "known_baseline": self.known,
            "dxf_version": self.dxf_version,
        }


def _num(sentinel: str) -> int:
    match = re.match(r"AC10(\d{2})", sentinel or "")
    return int(match.group(1)) if match else -1


_RAW_VERSIONS: tuple[tuple[str, str, str], ...] = (
    ("AC1004", "R9", "1986-1987"),
    ("AC1006", "R10", "1988-1989"),
    ("AC1009", "R12", "1993-1994"),
    ("AC1012", "R13", "1997"),
    ("AC1014", "R14", "1998-1999"),
    ("AC1015", "R2000", "2000-2002"),
    ("AC1018", "R2004", "2004-2006"),
    ("AC1021", "R2007", "2007-2009"),
    ("AC1024", "R2010", "2010-2012"),
    ("AC1027", "R2013", "2013-2017"),
    ("AC1032", "R2018", "2018-2023"),
    ("AC1036", "R2024+", "2024-current"),
)

#: sentinel -> DwgVersionInfo
VERSIONS: dict[str, DwgVersionInfo] = {
    sentinel: DwgVersionInfo(sentinel, release, years, _num(sentinel))
    for sentinel, release, years in _RAW_VERSIONS
}

#: sentinel -> ezdxf ``dxfversion`` (ezdxf has no R9/R10 reader at all)
DXF_FOR_SENTINEL: dict[str, str] = {
    "AC1009": "AC1009",
    "AC1012": "AC1012",
    "AC1014": "AC1014",
    "AC1015": "AC1015",
    "AC1018": "AC1018",
    "AC1021": "AC1021",
    "AC1024": "AC1024",
    "AC1027": "AC1027",
    "AC1032": "AC1032",
    "AC1036": "AC1032",  # down-levelled by ODA before ezdxf sees it
}


def describe(sentinel: str | None) -> DwgVersionInfo | None:
    """Return metadata for a sentinel, or ``None`` when unknown."""
    if not sentinel:
        return None
    return VERSIONS.get(sentinel.strip().upper())


def read_sentinel(data: bytes) -> str | None:
    """Extract the ``AC10xx`` sentinel from the first bytes of a DWG."""
    candidate = data[:SNIFF_BYTES].decode("ascii", errors="ignore").strip("\x00 ")
    return candidate if _AC_SENTINEL.match(candidate.encode("ascii", errors="ignore")) else None


def sniff_file(path: str | Path) -> str | None:
    """Read the DWG version sentinel of ``path`` (``None`` when not a DWG)."""
    file_path = Path(path)
    try:
        with file_path.open("rb") as handle:
            head = handle.read(SNIFF_BYTES)
    except OSError as exc:
        raise NotACadFileError(
            f"cannot read {file_path}: {exc}",
            details={"path": str(file_path)},
        ) from exc
    return read_sentinel(head)


def sniff_result(path: str | Path) -> tuple[str | None, DwgVersionInfo | None]:
    """``(sentinel, info)`` -- both ``None`` when the header is not a DWG."""
    sentinel = sniff_file(path)
    return sentinel, describe(sentinel)


def enforce_policy(
    info: DwgVersionInfo | None,
    *,
    source: str | Path | None = None,
    allow_legacy: bool = False,
) -> list[str]:
    """Validate a DWG version against the parser stack.

    Returns a list of human-readable warnings (never raises for warnings) and
    raises :class:`~cad2ai.errors.UnsupportedDwgVersionError` when the file
    cannot be parsed at all.
    """
    name = str(source) if source is not None else "input file"
    if info is None:
        raise UnsupportedDwgVersionError(
            f"{name}: DWG header is missing or not a recognised AutoCAD DWG signature",
            hint=(
                "the file may be a DXF, a corrupted DWG, or a DWG variant "
                "(BricsCAD/RealDWG) -- pass a .dxf file or re-save the drawing from AutoCAD"
            ),
            details={"path": name},
        )

    order = _num(info.sentinel)
    if order < _num(ODA_IMPORT_MIN):
        message = (
            f"{name}: DWG {info.sentinel} ({info.release}, {info.years}) predates "
            f"the {ODA_IMPORT_MIN} (R13) minimum that ODA File Converter can convert"
        )
        if allow_legacy:
            # DXF R12 is representable by ezdxf, so let the caller decide to
            # continue with a warning instead of a hard failure.
            return [f"legacy DWG accepted via allow_legacy_versions: {message}"]
        raise UnsupportedDwgVersionError(
            message,
            sentinel=info.sentinel,
            release=info.release,
            supported=_supported_label(),
            hint=(
                "open the drawing in AutoCAD (or any 2013+ product) and SAVE AS DWG 2018; "
                "DWG R9-R12 are not recoverable by the converter. Set CAD2AI_ALLOW_LEGACY_VERSIONS=1 "
                "to attempt it anyway"
            ),
        )

    warnings: list[str] = []
    if order < _num("AC1015"):
        warnings.append(
            f"DWG {info.sentinel} ({info.release}) converts to DXF {info.dxf_version}: pre-2000 entity "
            "sets lose proxy/XDATA fidelity, treat the extraction as best effort"
        )
    if not info.ezdxf_representable and info.known:
        warnings.append(
            f"DWG {info.sentinel} is newer than the DXF {EZDXF_MAX_REPRESENTABLE} baseline ezdxf "
            "represents; the converter down-levels it, so ACIS/3D solids and newer annotation "
            "objects may degrade"
        )
    if not info.known:
        warnings.append(
            f"DWG sentinel {info.sentinel} is newer than the {NEWEST_KNOWN} baseline this build was "
            "tested against; parsing is attempted but unsupported objects are likely (consider --fallback aps)"
        )
    return warnings


def _supported_label() -> tuple[str, ...]:
    return tuple(
        sentinel
        for sentinel, info in VERSIONS.items()
        if _num(sentinel) >= _num(ODA_IMPORT_MIN) and info.known
    )
