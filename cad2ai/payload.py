"""Phase 2b -- build the minified, token-budgeted JSON payload.

Token space is the cost driver of the whole pipeline, so the payload is built in
a specific order:

1. **Structure before prose.**  Counts, histograms and tables are kept; free
   text is the first thing to be aggregated.
2. **Numbers are rounded.**  ``float_precision`` (default 3) is applied while
   extracting; non-finite values are removed entirely.
3. **Emptiness is removed.**  ``None`` / ``[]`` / ``{}`` never ship.
4. **Degradation is explicit.**  If the payload exceeds the budget, sections are
   *aggregated* in a fixed order (never silently cut mid-list), and every
   applied step is recorded in ``meta.degraded`` so the model is told what it is
   *not* seeing -- which prevents confident hallucination about the missing
   parts.

The result is a single-line JSON document: ``json.dumps(..., separators=(",", ":"))``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

logger = logging.getLogger("cad2ai.payload")

__all__ = [
    "BuiltPayload",
    "PayloadBuilder",
    "PayloadLimits",
    "estimate_tokens",
    "minify",
]

_CJK = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")
#: JSON is punctuation-dense; measured empirically on CAD payloads this lands
#: within ~10% of the DeepSeek tokenizer, which is good enough for budgeting.
_CHARS_PER_TOKEN = 3.6


def estimate_tokens(text: str) -> int:
    """Estimate model tokens for ``text`` (CJK-aware, JSON-tuned heuristic).

    Deliberately cheap: the alternative (a tokenizer dependency) costs more in
    startup time and memory than the accuracy buys, and the pipeline re-calibrates
    the estimate against the API's reported ``usage.prompt_tokens`` after the
    first call.
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return int(cjk + other / _CHARS_PER_TOKEN) + 1


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == {} or value == ""


def _clean(value: Any, *, precision: int = 3) -> Any:
    """Recursively drop empties and non-finite floats, round the rest."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = round(value, precision)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = _clean(item, precision=precision)
            if _is_empty(item) and not isinstance(item, (int, float)):
                continue
            cleaned[str(key)] = item
        return cleaned
    if isinstance(value, (list, tuple)):
        items = [item for item in (_clean(entry, precision=precision) for entry in value) if not _is_empty(item)]
        return items
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def minify(data: Any, *, precision: int = 3) -> str:
    """Serialise to single-line JSON without NaN/Infinity (invalid JSON)."""
    return json.dumps(
        _clean(data, precision=precision),
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=False,
        default=_fallback_serializer,
    )


def _fallback_serializer(value: Any) -> Any:
    """Last-resort conversion for anything exotic left in the model.

    ``Counter`` is a dict subclass, ``set`` is not JSON-representable, and ezdxf
    vectors expose ``x``/``y``/``z``.  Converting loudly is better than raising
    inside ``json.dumps`` after a 30-second conversion.
    """
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    if all(hasattr(value, attribute) for attribute in ("x", "y")):
        try:
            return [round(float(value.x), 3), round(float(value.y), 3)]
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
    return str(value)


@dataclass(frozen=True)
class PayloadLimits:
    """Section-level caps applied *before* the token estimate is checked."""

    max_tokens: int = 120_000
    #: hard ceilings per section (0 = unlimited)
    max_layers: int = 200
    max_blocks: int = 120
    max_text_items: int = 800
    max_dimensions: int = 400
    max_entity_types: int = 40
    text_sample_chars: int = 160
    float_precision: int = 3
    #: when False the payload only carries aggregate statistics
    include_text: bool = True
    include_dimensions: bool = True
    include_tables: bool = True


@dataclass
class BuiltPayload:
    """A payload plus the metadata the model and the operator both need."""

    json: str
    data: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return int(self.meta.get("token_estimate", 0))

    @property
    def chars(self) -> int:
        return int(self.meta.get("chars", 0))

    @property
    def fits_budget(self) -> bool:
        """False when the payload could not be shrunk into ``max_tokens``."""
        return not self.meta.get("budget_exceeded_by")

    def write(self, path: str | Any) -> int:
        """Write the minified JSON (artifacts are byte-for-byte what we sent)."""
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.json, encoding="utf-8")
        return len(self.json)


class PayloadBuilder:
    """Compose the AI payload from a :class:`~cad2ai.structurer.CadModel`."""

    #: Ordered degradation steps; each returns a (possibly) reduced payload.
    DEGRADATION_STEPS: tuple[str, ...] = (
        "text_capped",
        "text_aggregated",
        "dimensions_capped",
        "dimensions_histogram",
        "blocks_capped",
        "block_internals_dropped",
        "layers_capped",
        "tables_aggregated",
        "entity_types_capped",
        "layout_breakdown_dropped",
    )

    def __init__(self, limits: PayloadLimits | None = None) -> None:
        self.limits = limits or PayloadLimits()

    # ------------------------------------------------------------------ build
    def build(self, model: Any) -> BuiltPayload:
        """Build the payload, degrading sections until it fits the budget."""
        data = model.as_dict() if hasattr(model, "as_dict") else dict(model)
        payload = self._compose(data)
        applied: list[str] = []

        text = minify(payload, precision=self.limits.float_precision)
        for step in self.DEGRADATION_STEPS:
            if estimate_tokens(text) <= self.limits.max_tokens:
                break
            before = len(json.dumps(payload, sort_keys=True, default=str))
            payload = self._degrade(payload, step)
            applied.append(step)
            text = minify(payload, precision=self.limits.float_precision)
            if len(json.dumps(payload, sort_keys=True, default=str)) == before:
                applied.pop()  # step had no effect; do not claim we applied it

        if estimate_tokens(text) > self.limits.max_tokens:
            logger.warning(
                "payload still exceeds the budget after degradation (%d > %d tokens); "
                "raising CAD2AI_MAX_PAYLOAD_TOKENS or splitting the analysis is required",
                estimate_tokens(text),
                self.limits.max_tokens,
            )

        meta = self._meta(payload, text, applied)
        payload["meta"] = meta
        # Re-serialise until the numbers inside ``meta`` describe the text that is
        # actually shipped: the estimate changes the byte count, which changes
        # the estimate.  Two or three passes always converge.
        for _ in range(4):
            text = minify(payload, precision=self.limits.float_precision)
            estimate, chars = estimate_tokens(text), len(text)
            if meta["token_estimate"] == estimate and meta["chars"] == chars:
                break
            meta["token_estimate"], meta["chars"] = estimate, chars
        over = meta["token_estimate"] - int(self.limits.max_tokens or 0)
        if self.limits.max_tokens and over > 0:
            # Degrading further would start deleting facts; the operator needs
            # to see this in the artifacts instead of only in a log line.
            meta["budget_exceeded_by"] = over
        return BuiltPayload(json=text, data=payload, meta=meta)

    # ------------------------------------------------------------- composition
    def _compose(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Project the CadModel onto the AI payload shape (short, semantic keys)."""
        limits = self.limits
        entities = dict(data.get("entities") or {})
        if limits.max_entity_types and isinstance(entities.get("by_type"), dict):
            entities["by_type"] = dict(top_n(entities["by_type"], limits.max_entity_types))
            entities["by_type_truncated"] = len(data["entities"].get("by_type") or {}) > limits.max_entity_types
        if not limits.include_tables:
            entities.pop("layout_breakdown", None)

        payload: dict[str, Any] = {
            "cad_schema": data.get("schema", "1.0"),
            "source": _select(data.get("source") or {}, ("file", "size_bytes", "sha256", "backend", "lossless", "provenance")),
            "document": {
                "units": (data.get("document") or {}).get("units"),
                "extents": (data.get("document") or {}).get("extents"),
                "dxf_version": (data.get("document") or {}).get("dxf_version"),
                "dwg": _select(
                    (data.get("document") or {}).get("dwg") or {},
                    ("sentinel", "release", "years", "ezdxf_representable"),
                ),
                "header": _compact_header((data.get("document") or {}).get("header") or {}),
                "tables": (data.get("document") or {}).get("tables"),
            },
            "layers": [
                _compact_layer(layer)
                for layer in (data.get("layers") or [])[: limits.max_layers or None]
            ],
            "layer_stats": data.get("layer_stats") or {},
            "entities": entities,
            "layouts": [
                _compact_layout(layout) for layout in (data.get("layouts") or [])[: (limits.max_layers or 50)]
            ],
            "blocks": {
                "stats": data.get("block_stats") or {},
                "items": [
                    _compact_block(block) for block in (data.get("blocks") or [])[: limits.max_blocks or None]
                ],
            },
            "discipline": data.get("discipline") or {},
            "stats": {
                "text": data.get("text_stats") or {},
                "dimensions": data.get("dimension_stats") or {},
                "proxies": data.get("proxies") or {},
            },
        }
        if limits.include_tables:
            payload["linetypes"] = [
                _compact_linetype(item) for item in (data.get("linetypes") or []) if isinstance(item, Mapping)
            ]
            payload["text_styles"] = [
                _compact_style(item) for item in (data.get("text_styles") or []) if isinstance(item, Mapping)
            ]
            payload["dimension_styles"] = [
                _compact_dimstyle(item) for item in (data.get("dimension_styles") or []) if isinstance(item, Mapping)
            ]
        else:
            payload["table_counts"] = {
                "linetypes": len(data.get("linetypes") or []),
                "text_styles": len(data.get("text_styles") or []),
                "dimension_styles": len(data.get("dimension_styles") or []),
            }
        if limits.include_text:
            payload["text"] = [
                _compact_text(item) for item in (data.get("text") or [])[: limits.max_text_items or None]
            ]
        if limits.include_dimensions:
            payload["dimensions"] = [
                _compact_dimension(item) for item in (data.get("dimensions") or [])[: limits.max_dimensions or None]
            ]
        warnings = data.get("warnings") or []
        if warnings:
            payload["warnings"] = [str(item)[:220] for item in warnings[:40]]
        # Record every section we clipped so the model knows a list is partial
        # instead of mistaking "absent" for "does not exist in the drawing".
        for section, seen, kept in (
            ("layers", len(data.get("layers") or []), len(payload.get("layers") or [])),
            ("text", len(data.get("text") or []), len(payload.get("text") or [])),
            ("dimensions", len(data.get("dimensions") or []), len(payload.get("dimensions") or [])),
            ("blocks.items", len(data.get("blocks") or []), len((payload.get("blocks") or {}).get("items") or [])),
            ("layouts", len(data.get("layouts") or []), len(payload.get("layouts") or [])),
        ):
            _note_truncation(payload, section, dropped=seen - kept)
        return {key: value for key, value in payload.items() if not _is_empty(value)}

    # -------------------------------------------------------------- degradation
    def _degrade(self, payload: dict[str, Any], step: str) -> dict[str, Any]:
        """Apply one named degradation step (idempotent, never destructive)."""
        out = dict(payload)
        if step == "text_capped":
            items = out.get("text") or []
            keep = max(25, len(items) // 4)
            if len(items) > keep:
                out["text"] = items[:keep]
                _note_truncation(out, "text", dropped=len(items) - keep)
        elif step == "text_aggregated":
            items = out.get("text") or []
            if items:
                by_layer: dict[str, int] = {}
                samples: list[str] = []
                for item in items:
                    layer = str(item.get("layer") or "0") if isinstance(item, Mapping) else "0"
                    by_layer[layer] = by_layer.get(layer, 0) + 1
                    if len(samples) < 25 and isinstance(item, Mapping) and item.get("text"):
                        samples.append(f"{layer}:{str(item['text'])[:80]}")
                stats = out.setdefault("stats", {})
                previous = stats.get("text") if isinstance(stats.get("text"), Mapping) else {}
                stats["text"] = {
                    "aggregated": True,
                    "total": (previous or {}).get("total", len(items)),
                    "by_layer": dict(sorted(by_layer.items(), key=lambda kv: -kv[1])[:40]),
                    "samples": samples,
                }
                out.pop("text", None)
        elif step == "dimensions_capped":
            items = out.get("dimensions") or []
            keep = max(25, len(items) // 4)
            if len(items) > keep:
                out["dimensions"] = items[:keep]
                _note_truncated(out, "dimensions", dropped=len(items) - keep)
        elif step == "dimensions_histogram":
            items = out.get("dimensions") or []
            if items:
                kinds: dict[str, int] = {}
                values: list[float] = []
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    kind = str(item.get("kind") or "linear")
                    kinds[kind] = kinds.get(kind, 0) + 1
                    value = item.get("value")
                    if isinstance(value, (int, float)):
                        values.append(float(value))
                stats = out.setdefault("stats", {})
                previous = stats.get("dimensions") if isinstance(stats.get("dimensions"), Mapping) else {}
                stats["dimensions"] = {
                    "aggregated": True,
                    "total": (previous or {}).get("total", len(items)),
                    "by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
                    "count": len(items),
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                }
                out.pop("dimensions", None)
        elif step == "blocks_capped":
            blocks = out.get("blocks") or {}
            items = list(blocks.get("items") or [])
            keep = max(20, len(items) // 2)
            if len(items) > keep:
                blocks = {**blocks, "items": items[:keep]}
                out["blocks"] = blocks
                _note_truncated(out, "blocks.items", dropped=len(items) - keep)
        elif step == "block_internals_dropped":
            blocks = out.get("blocks") or {}
            items = list(blocks.get("items") or [])
            if any(isinstance(item, Mapping) and "entity_types" in item for item in items):
                out["blocks"] = {
                    **blocks,
                    "items": [
                        {key: value for key, value in item.items() if key != "entity_types"}
                        if isinstance(item, Mapping)
                        else item
                        for item in items
                    ],
                }
        elif step == "layers_capped":
            items = out.get("layers") or []
            keep = max(25, len(items) // 2)
            if len(items) > keep:
                out["layers"] = items[:keep]
                _note_truncated(out, "layers", dropped=len(items) - keep)
        elif step == "tables_aggregated":
            for key in ("linetypes", "text_styles", "dimension_styles"):
                items = out.get(key)
                if items:
                    counts = out.setdefault("table_counts", {})
                    counts[key.rstrip("s") + "s"] = len(items)
                    out.pop(key, None)
        elif step == "entity_types_capped":
            entities = out.get("entities") or {}
            by_type = dict(entities.get("by_type") or {})
            if len(by_type) > 12:
                out["entities"] = {**entities, "by_type": dict(top_n(by_type, 12)), "by_type_truncated": True}
        elif step == "layout_breakdown_dropped":
            entities = out.get("entities") or {}
            if "layout_breakdown" in entities:
                out["entities"] = {key: value for key, value in entities.items() if key != "layout_breakdown"}
        return out

    # ------------------------------------------------------------------ helpers
    def _meta(self, payload: Mapping[str, Any], text: str, degraded: Iterable[str]) -> dict[str, Any]:
        """Run metadata; ``sha256`` fingerprints the payload *without* this block."""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return {
            "schema": "cad2ai-payload-1",
            "sha256": digest,
            "chars": len(text),
            "token_estimate": estimate_tokens(text),
            "token_budget": self.limits.max_tokens,
            "degraded": list(degraded),
            "truncations": dict(payload.get("truncations") or {}),
            "counts": {
                "layers": len(payload.get("layers") or []),
                "blocks": len((payload.get("blocks") or {}).get("items") or []),
                "text": len(payload.get("text") or []),
                "dimensions": len(payload.get("dimensions") or []),
                "entities": (payload.get("entities") or {}).get("total"),
            },
            "tokenizer_note": "token_estimate is a heuristic; re-calibrate against usage.prompt_tokens",
        }


def _note_truncation(payload: dict[str, Any], section: str, *, dropped: int) -> None:
    """Record dropped counts so the model knows the list is partial."""
    if dropped <= 0:
        return
    truncations = payload.setdefault("truncations", {})
    truncations[section] = int(truncations.get(section, 0)) + dropped


_note_truncated = _note_truncation


def top_n(mapping: Mapping[str, Any], n: int) -> list[tuple[str, Any]]:
    return sorted(mapping.items(), key=lambda item: (-item[1], item[0]))[:n]


def _select(data: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out = {key: data.get(key) for key in keys if key in data}
    return {key: value for key, value in out.items() if not _is_empty(value)}


def _compact_header(header: Mapping[str, Any]) -> dict[str, Any]:
    """Header vars are renamed to model-friendly keys (``$INSUNITS`` -> ``insunits``)."""
    out: dict[str, Any] = {}
    for key, value in header.items():
        clean = str(key).lstrip("$").lower()
        out[clean] = value
    return out


def _compact_layer(layer: Mapping[str, Any]) -> dict[str, Any]:
    return _select(
        {
            "name": layer.get("name"),
            "color": layer.get("color_aci"),
            "color_hex": layer.get("color_hex"),
            "linetype": layer.get("linetype"),
            "lineweight": layer.get("lineweight"),
            "state": _layer_state(layer),
            "entities": layer.get("entities"),
            "annotations": layer.get("annotations"),
            "text": layer.get("text"),
            "dimensions": layer.get("dimensions"),
            "xrefs": layer.get("xrefs"),
            "proxy": layer.get("proxy"),
        },
        tuple(
            "name color color_hex linetype lineweight state entities annotations text dimensions xrefs proxy".split()
        ),
    )


def _layer_state(layer: Mapping[str, Any]) -> str | None:
    flags = []
    if not layer.get("on", True):
        flags.append("off")
    if layer.get("frozen"):
        flags.append("frozen")
    if layer.get("locked"):
        flags.append("locked")
    if not layer.get("plotted", True):
        flags.append("donotplot")
    return ",".join(flags) or None


def _compact_linetype(item: Mapping[str, Any]) -> dict[str, Any]:
    return _select({"name": item.get("name"), "segments": item.get("segments")}, ("name", "segments"))


def _compact_style(item: Mapping[str, Any]) -> dict[str, Any]:
    return _select(
        {"name": item.get("name"), "font": item.get("font"), "height": item.get("fixed_height")},
        ("name", "font", "height"),
    )


def _compact_dimstyle(item: Mapping[str, Any]) -> dict[str, Any]:
    keep = ("name", "text_height", "decimal_places", "linear_factor", "rounding", "scale", "zero_suppression")
    return _select({key: item.get(key) for key in keep}, keep)


def _compact_layout(item: Mapping[str, Any]) -> dict[str, Any]:
    return _select(
        {
            "name": item.get("name"),
            "entities": item.get("entities"),
            "modelspace": item.get("is_modelspace"),
            "paper_height": item.get("paper_height"),
            "scale": item.get("view_scale") or item.get("standard_scale"),
            "types": item.get("top_types"),
        },
        ("name", "entities", "modelspace", "paper_height", "scale", "types"),
    )


def _compact_block(item: Mapping[str, Any]) -> dict[str, Any]:
    return _select(
        {
            "name": item.get("name"),
            "refs": item.get("references"),
            "entities": item.get("entities"),
            "attributes": item.get("attribute_tags"),
            "types": item.get("entity_types"),
            "leverage": item.get("leverage"),
            "external": item.get("external"),
            "anonymous": item.get("anonymous"),
            "base": item.get("base_point"),
        },
        ("name", "refs", "entities", "attributes", "types", "leverage", "external", "anonymous", "base"),
    )


def _compact_text(item: Mapping[str, Any]) -> dict[str, Any]:
    return _select(
        {
            "layer": item.get("layer"),
            "type": item.get("kind"),
            "tag": item.get("tag"),
            "text": item.get("text"),
            "at": item.get("at"),
            "h": item.get("height"),
            "rot": item.get("rotation"),
            "handle": item.get("handle"),
        },
        ("layer", "type", "tag", "text", "at", "h", "rot", "handle"),
    )


def _compact_dimension(item: Mapping[str, Any]) -> dict[str, Any]:
    return _select(
        {
            "layer": item.get("layer"),
            "kind": item.get("kind"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "text": item.get("text"),
            "style": item.get("dimstyle"),
            "flags": item.get("flags"),
            "handle": item.get("handle"),
        },
        ("layer", "kind", "value", "unit", "text", "style", "flags", "handle"),
    )


def build_payload(model: Any, *, settings: Any | None = None, **overrides: Any) -> BuiltPayload:
    """Convenience wrapper used by the pipeline and the CLI."""
    limits = _limits_for(settings, **overrides)
    return PayloadBuilder(limits).build(model)


def _limits_for(settings: Any | None, **overrides: Any) -> PayloadLimits:
    if settings is None:
        base = PayloadLimits()
    else:
        base = PayloadLimits(
            max_tokens=settings.payload_max_tokens,
            max_layers=settings.max_layers,
            max_blocks=settings.max_blocks,
            max_text_items=settings.max_text_items,
            max_dimensions=settings.max_dimensions,
            float_precision=settings.float_precision,
        )
    if overrides:
        known = {f for f in base.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(overrides) - known
        if unknown:
            raise ValueError(f"unknown payload limit(s): {', '.join(sorted(unknown))}")
        base = PayloadLimits(**{**base.__dict__, **overrides})
    return base


def split_batches(model: Any, *, settings: Any | None = None, batch_tokens: int = 30_000) -> list[BuiltPayload]:
    """Split a huge drawing into sequential payloads (summary + detail pages).

    Used by batch mode when a single call would blow the budget: the first batch
    is always the whole-summary payload so the model has context for every
    follow-up page.
    """
    data = model.as_dict() if hasattr(model, "as_dict") else dict(model)
    summary_limits = _limits_for(settings, max_tokens=batch_tokens, include_text=False, include_dimensions=False)
    batches: list[BuiltPayload] = [PayloadBuilder(summary_limits).build(_summary_view(data))]

    for section, builder_limits in (
        ("text", _limits_for(settings, max_tokens=batch_tokens, include_tables=False)),
        ("dimensions", _limits_for(settings, max_tokens=batch_tokens, include_tables=False)),
    ):
        items = list(data.get(section) or [])
        if not items:
            continue
        chunks: list[list[Any]] = []
        current: list[Any] = []
        budget = 0
        for item in items:
            text = json.dumps(item, separators=(",", ":"), ensure_ascii=False, default=str)
            cost = estimate_tokens(text)
            if budget + cost > batch_tokens and current:
                chunks.append(current)
                current, budget = [], 0
            current.append(item)
            budget += cost
        if current:
            chunks.append(current)
        for index, chunk in enumerate(chunks, start=1):
            view = {
                "cad_schema": data.get("schema", "1.0"),
                "batch": {"section": section, "page": index, "pages": len(chunks)},
                section: chunk,
            }
            batches.append(PayloadBuilder(builder_limits).build(view))
    return batches


def _summary_view(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in ("text", "dimensions")}
