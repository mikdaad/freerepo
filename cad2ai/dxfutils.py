"""Defensive helpers for reading ezdxf objects.

Two real-world hazards motivate this module:

1. **DXF attributes are version-gated.**  ``entity.dxf.true_color`` raises
   :class:`ezdxf.lldxf.const.DXFAttributeError` for a document saved as DXF
   R12, and ``ezdxf`` also raises (rather than returning the supplied default)
   when the attribute name does not exist on the entity at all.  Production
   drawings are a zoo of both, so every read goes through :func:`dxf_attr`.

2. **Third-party DWG files contain half-valid entities.**  A single TEXT with
   an illegal rotation value must not abort a batch of 400 drawings; each
   extraction helper logs and continues instead.

Everything here is pure and dependency-light so it can be unit tested without a
CAD file.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

logger = logging.getLogger("cad2ai.dxf")

try:  # pragma: no cover - ezdxf is a hard dependency, but keep import cheap
    from ezdxf.lldxf import const as _ezdxf_const

    _DXF_ERRORS: tuple[type[BaseException], ...] = (
        _ezdxf_const.DXFAttributeError,
        _ezdxf_const.DXFValueError,
        _ezdxf_const.DXFStructureError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    )
except Exception:  # pragma: no cover
    _DXF_ERRORS = (Exception,)


@dataclass
class Warnings:
    """Collector for non-fatal extraction problems.

    Kept as a dataclass (rather than a list) so it can carry a cap and dedupe:
    huge drawings can otherwise produce megabytes of identical warnings.
    """

    items: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    max_unique: int = 200

    def add(self, message: str, *, log: bool = True) -> None:
        key = message.split(":", 1)[0]
        self.counts[key] = self.counts.get(key, 0) + 1
        if message in self.items:
            return
        if len(self.items) >= self.max_unique:
            return
        self.items.append(message)
        if log:
            logger.debug("%s", message)

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.add(message)

    def as_list(self) -> list[str]:
        """Warnings plus an aggregate count for the suppressed families."""
        out = list(self.items)
        extra = {k: v for k, v in self.counts.items() if v > 1}
        if extra:
            out.append("repeat_counts=" + ",".join(f"{k}:{v}" for k, v in sorted(extra.items())))
        return out

    def __len__(self) -> int:  # pragma: no cover - convenience
        return sum(self.counts.values())


def dxf_attr(entity: Any, name: str, default: Any = None) -> Any:
    """Read ``entity.dxf.<name>`` without ever raising.

    ``DXFAttributes.get(name, default)`` raises for attribute *names the entity
    does not define*, which is common across DXF versions, so we try the
    attribute access first (it applies the schema default) and fall back.
    """
    dxf = getattr(entity, "dxf", None)
    if dxf is None:
        return default
    try:
        return getattr(dxf, name)
    except _DXF_ERRORS:
        pass
    try:
        return dxf.get(name, default)
    except _DXF_ERRORS:
        return default


def has_dxf_attr(entity: Any, name: str) -> bool:
    dxf = getattr(entity, "dxf", None)
    if dxf is None:
        return False
    checker = getattr(dxf, "has", None)
    if callable(checker):
        try:
            return bool(checker(name))
        except _DXF_ERRORS:
            return False
    return dxf_attr(entity, name, _MISSING) is not _MISSING


_MISSING = object()


def safe(fn: Callable[[], Any], default: Any = None, *, context: str = "", warnings: Warnings | None = None):
    """Run ``fn``; on any ezdxf/CAD error, record a warning and return default."""
    try:
        return fn()
    except _DXF_ERRORS as exc:
        message = f"{context or 'ezdxf read'} failed: {type(exc).__name__}: {exc}"
        logger.debug("%s", message)
        if warnings is not None:
            warnings.add(message)
        return default


def round_float(value: Any, precision: int = 3) -> Any:
    """Round floats (and points of floats) for token economy.

    ``1775.0000000001`` and ``1775.0`` mean the same thing to a model but cost
    very different numbers of tokens.  Non-finite values become ``None``.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int,)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        rounded = round(value, precision)
        return int(rounded) if rounded.is_integer() and abs(rounded) < 1e15 else rounded
    if isinstance(value, (tuple, list)):
        return [round_float(item, precision) for item in value]
    return value


def point(value: Any, precision: int = 3) -> list[float] | None:
    """Normalise an ezdxf ``Vec3``/tuple-ish point to ``[x, y]`` (``+z`` if 3D)."""
    if value is None:
        return None
    try:
        triple = (float(value.x), float(value.y), float(getattr(value, "z", 0.0)))
    except (AttributeError, TypeError, ValueError):
        try:
            seq = [float(v) for v in value]
        except (TypeError, ValueError):
            return None
        if not seq:
            return None
        triple = (seq[0], seq[1] if len(seq) > 1 else 0.0, seq[2] if len(seq) > 2 else 0.0)
    if any(math.isnan(c) or math.isinf(c) for c in triple):
        return None
    x, y, z = (round(c, precision) for c in triple)
    if z in (0, 0.0):
        out = [x, y]
    else:
        out = [x, y, z]
    return [int(v) if float(v).is_integer() else v for v in out]


def degrees(value: Any, precision: int = 1) -> float | None:
    """Normalise an ezdxf ``Angle`` (radians) or float-in-degrees to degrees."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return round(numeric, precision)


def iter_layout_entities(doc: Any) -> Iterator[tuple[str, Any]]:
    """Yield ``(layout_name, entity)`` for every layout entity in the document.

    Uses the model space first, then each named layout; robust across ezdxf
    versions because the layout table access is duck-typed.
    """
    yielded_ids: set[int] = set()
    msp = None
    try:
        msp = doc.modelspace()
    except Exception:  # pragma: no cover - corrupted documents
        logger.debug("doc.modelspace() failed", exc_info=True)
    if msp is not None:
        name = getattr(msp, "name", "Model") or "Model"
        for entity in _iter_layout(msp):
            yielded_ids.add(id(entity))
            yield name, entity
    for candidate in iter_layout_names(doc):
        if candidate and (msp is not None and candidate == getattr(msp, "name", "Model")):
            continue
        layout = None
        try:
            layout = doc.layout(candidate)
        except Exception:  # pragma: no cover - defensive
            logger.debug("doc.layout(%r) failed", candidate, exc_info=True)
        if layout is None:
            continue
        for entity in _iter_layout(layout):
            if id(entity) in yielded_ids:
                continue
            yielded_ids.add(id(entity))
            yield candidate, entity


def _iter_layout(layout: Any) -> Iterable[Any]:
    try:
        return list(layout)
    except Exception:  # pragma: no cover - defensive
        logger.debug("iterating layout %r failed", getattr(layout, "name", layout), exc_info=True)
        return []


def iter_layout_names(doc: Any) -> list[str]:
    for attribute in ("layout_names", "get_layout_names"):
        getter = getattr(doc, attribute, None)
        if callable(getter):
            try:
                return list(getter())
            except Exception:  # pragma: no cover
                logger.debug("%s() failed", attribute, exc_info=True)
    names: list[str] = []
    for entry in getattr(doc, "layouts_and_blocks", lambda: [])():
        try:
            if getattr(entry, "is_any_paperspace", False):
                names.append(entry.name)
        except Exception:  # pragma: no cover
            continue
    return names


def truncate_text(value: Any, limit: int) -> str | None:
    """Collapse whitespace and clip ``value`` to ``limit`` characters."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "\u2026"


def sha256_prefix(path: str | Path, prefix: int = 12) -> str | None:
    """Short content fingerprint (dedupe/cache key without hashing GB files)."""
    import hashlib
    from pathlib import Path as _Path

    try:
        digest = hashlib.sha256()
        with _Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()[:prefix]


def strip_mtext_markup(value: Any) -> str:
    """Remove MTEXT formatting codes so the payload carries prose, not markup.

    ``plain_text()`` is the correct call for ``MTEXT``; this fallback only
    covers entities that expose a raw ``dxf.text`` (e.g. ``ATTRIB`` inside a
    block that still contains ``{\\fArial|b0|i0;`` runs).
    """
    import re

    text = str(value or "")
    if "\\" not in text and "{" not in text:
        return " ".join(text.split())
    text = re.sub(r"\\[pP]", " ", text)  # paragraph breaks
    text = re.sub(r"\\S([^;^#]*)[^;]*;", r"\1", text)  # stacked fractions -> linear
    text = re.sub(r"\\[ACFHTQWLK][^;]*;", "", text, flags=re.IGNORECASE)  # coded properties
    text = re.sub(r"\\[~\\{}]", " ", text)  # non-breaking space, escaped brace/backslash
    text = text.replace("{", "").replace("}", "")
    return " ".join(text.split())
