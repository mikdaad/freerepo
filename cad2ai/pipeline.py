"""End-to-end orchestration: DWG -> structured JSON -> DeepSeek -> artifacts.

``Pipeline.run`` is the single entry point used by ``main.py`` and by embedding
services.  It is deterministic about *what it writes* so runs are auditable:

::

    <out_dir>/
        cad_model.json      pretty Phase 2 model (developer-facing, full detail)
        payload.json        the exact minified JSON handed to the model
        analysis.json       parsed Phase 3 JSON reply
        analysis.md         human-readable rendering of analysis.json
        ai_meta.json        model/latency/token-usage metadata for the call
        run_manifest.json   provenance: masked config, backend, timings,
                            calibrations, warnings, errors

Dependency injection: ``load``, ``build_model``, ``client_factory`` and
``aps_factory`` are constructor arguments -- which is how the tests execute the
whole pipeline with no ODA converter, no network and no credentials.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cad2ai import __version__
from cad2ai.config import Settings
from cad2ai.errors import Cad2AiError, ConfigError, ParseError
from cad2ai.payload import PayloadBuilder, PayloadLimits
from cad2ai.prompts import build_messages, resolve_task

logger = logging.getLogger("cad2ai.pipeline")

__all__ = ["Pipeline", "PipelineReport", "analyze_file", "extract", "render_markdown"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PipelineReport:
    """Everything a caller needs to know about one run."""

    ok: bool = True
    mode: str = "oda"
    task: str = ""
    payload: str = ""
    payload_meta: dict[str, Any] = field(default_factory=dict)
    model: Any = None
    parsed: Any = None
    analysis: Any = None
    chat_result: Any = None
    context: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    started_at: str = field(default_factory=_now)

    @property
    def usage(self) -> dict[str, Any] | None:
        usage = getattr(self.chat_result, "usage", None)
        return usage.as_dict() if usage is not None else None

    @property
    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "mode": self.mode,
            "task": self.task,
            "model": self.model.summary() if hasattr(self.model, "summary") else None,
            "payload": {
                "chars": self.payload_meta.get("chars"),
                "token_estimate": self.payload_meta.get("token_estimate"),
                "token_budget": self.payload_meta.get("token_budget"),
                "degraded": self.payload_meta.get("degraded"),
                "truncations": self.payload_meta.get("truncations"),
                "budget_exceeded_by": self.payload_meta.get("budget_exceeded_by"),
                "tokenizer_calibration": self.payload_meta.get("tokenizer_calibration"),
                "prompt_tokens_actual": self.payload_meta.get("prompt_tokens_actual"),
            },
            "usage": self.usage,
            "latency_seconds": round(sum(self.timings.values()), 3),
            "artifacts": dict(self.artifacts),
            "warnings": list(self.warnings)[:10],
        }
        if self.error:
            out["error"] = self.error
        return out

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.summary)
        payload["started_at"] = self.started_at
        payload["cad2ai_version"] = __version__
        payload["timings_ms"] = {key: round(value * 1000, 1) for key, value in self.timings.items()}
        if self.parsed is not None and hasattr(self.parsed, "summary"):
            payload["parse"] = self.parsed.summary()
        if self.chat_result is not None and hasattr(self.chat_result, "as_dict"):
            payload["ai"] = self.chat_result.as_dict()
        if self.context:
            payload["context"] = self.context
        return payload


def _default_client(settings: Settings) -> Any:
    from cad2ai.ai_client import DeepSeekClient, DeepSeekConfig, RateLimitPolicy

    return DeepSeekClient(
        DeepSeekConfig.from_settings(settings),
        policy=RateLimitPolicy.from_settings(settings),
    )


class Pipeline:
    """Three-phase pipeline with an Autodesk fallback and a DeepSeek client."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        load: Callable[..., Any] | None = None,
        build_model: Callable[..., Any] | None = None,
        client_factory: Callable[[Settings], Any] | None = None,
        aps_factory: Callable[[Settings], Any] | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self._load = load
        self._build_model = build_model
        self._client_factory = client_factory or _default_client
        self._aps_factory = aps_factory
        self._client: Any = None

    # ------------------------------------------------------------------ phases
    def load(self, path: str | Path, **kwargs: Any) -> Any:
        """Phase 1: local parse via ``ezdxf`` + ``odafc`` (or a plain DXF read)."""
        loader = self._load
        if loader is None:
            from cad2ai.parser import load_drawing

            loader = load_drawing
        return loader(path, settings=self.settings, **kwargs)

    def build_model(self, parsed: Any) -> Any:
        """Phase 2: CadModel extraction."""
        builder = self._build_model
        if builder is None:
            from cad2ai.structurer import build_cad_model

            builder = build_cad_model
        return builder(parsed, settings=self.settings)

    def payload_limits(self, **overrides: Any) -> PayloadLimits:
        base = PayloadLimits(
            max_tokens=self.settings.payload_max_tokens,
            max_layers=self.settings.max_layers,
            max_blocks=self.settings.max_blocks,
            max_text_items=self.settings.max_text_items,
            max_dimensions=self.settings.max_dimensions,
            float_precision=self.settings.float_precision,
        )
        if overrides:
            unknown = set(overrides) - set(base.__dataclass_fields__)
            if unknown:
                raise ConfigError(f"unknown payload option(s): {', '.join(sorted(unknown))}")
            base = PayloadLimits(**{**base.__dict__, **overrides})
        return base

    def build_payload(self, model: Any, **overrides: Any) -> Any:
        """Phase 2b: minified, token-budgeted payload."""
        return PayloadBuilder(self.payload_limits(**overrides)).build(model)

    def client(self) -> Any:
        """Phase 3 client, built lazily and cached (so usage totals accumulate).

        Accepts either a factory (``callable(settings) -> client``) or a ready
        client object, which keeps tests free of any ``DeepSeekClient`` wiring.
        """
        if self._client is None:
            factory = self._client_factory
            self._client = factory if hasattr(factory, "complete") else factory(self.settings)
        return self._client

    def extract(self, path: str | Path, *, fallback: str = "auto", **load_kwargs: Any) -> tuple[Any, Any, dict[str, Any]]:
        """Phase 1 + 2 with backend selection.

        Returns ``(parsed_or_None, cad_model, context)``.  ``context`` records the
        backend actually used, and the local failure that triggered a fallback.
        """
        context: dict[str, Any] = {"fallback": fallback, "attempts": []}
        file_path = Path(path)
        try:
            parsed = self.load(file_path, **load_kwargs)
            model = self.build_model(parsed)
            context["attempts"].append({"backend": "oda/dxf", "ok": True})
            context["backend"] = getattr(getattr(parsed, "backend", None), "value", "unknown")
            return parsed, model, context
        except ParseError as exc:
            context["attempts"].append({"backend": "oda/dxf", "ok": False, "error": exc.to_dict()})
            if fallback in ("none", "off"):
                raise
            if not self._aps_configured():
                raise ParseError(
                    f"{exc.message}",
                    hint=(
                        (exc.hint or "")
                        + " | no APS credentials configured, so the cloud fallback is unavailable: "
                        "either install/point at the ODA File Converter (ODA_EXECUTABLE) or set "
                        "APS_CLIENT_ID/APS_CLIENT_SECRET/APS_BUCKET_KEY"
                    ).strip(" |"),
                    details=exc.details,
                ) from exc
            logger.warning("local parse failed (%s); using the Autodesk Model Derivative fallback", exc.message)
            model_aps, aps_context = self.extract_via_aps(file_path)
            context["aps"] = aps_context
            context["backend"] = "aps-model-derivative"
            return None, model_aps, context

    def _aps_configured(self) -> bool:
        return bool(self.settings.aps_client_id and self.settings.aps_client_secret and self.settings.aps_bucket_key)

    def extract_via_aps(self, path: str | Path) -> tuple[Any, dict[str, Any]]:
        """Phase 1 fallback: upload, translate, and normalise the JSON manifest."""
        from cad2ai import dwg_version
        from cad2ai.aps import ApsClient, ApsConfig, cad_model_from_aps

        started = time.perf_counter()
        if self._aps_factory is not None:
            client = self._aps_factory(self.settings)
        else:
            client = ApsClient(ApsConfig.from_settings(self.settings))
        extraction = client.extract(path)
        try:
            # The local sniff only decorates the model with the DWG version; a
            # file the cloud accepted must not fail the run because a header
            # could not be read.
            sentinel, info = dwg_version.sniff_result(path)
        except Cad2AiError as exc:
            logger.debug("could not sniff the DWG header after the APS extraction: %s", exc)
            sentinel, info = None, None
        model = cad_model_from_aps(
            extraction,
            source_path=path,
            dwg_version=info.as_dict() if info else ({"sentinel": sentinel, "known": False} if sentinel else None),
            generated_at=_now(),
        )
        context = {
            "backend": "aps-model-derivative",
            "seconds": round(time.perf_counter() - started, 2),
            "object": extraction.object.as_dict() if extraction.object else None,
            "views": len(extraction.views),
            "properties": len(extraction.properties),
            "manifest_status": (extraction.manifest or {}).get("status"),
            # kept so ``--include-raw-manifest`` can write the untouched manifest
            "manifest": extraction.manifest,
            "warnings": list(extraction.warnings),
        }
        return model, context

    # ------------------------------------------------------------------- run
    def run(
        self,
        path: str | Path,
        *,
        task: str = "discipline_summary",
        brief: str | None = None,
        out_dir: str | Path | None = None,
        fallback: str = "auto",
        dry_run: bool = False,
        include_raw_manifest: bool = False,
        **load_kwargs: Any,
    ) -> PipelineReport:
        """Run all three phases (Phase 3 is skipped when ``dry_run`` is set)."""
        report = PipelineReport(task=str(task))
        timings: dict[str, float] = {}
        target_dir = Path(out_dir) if out_dir else None
        stage = time.perf_counter()
        try:
            parsed, model, context = self.extract(path, fallback=fallback, **load_kwargs)
            timings["extract"] = time.perf_counter() - stage
            report.parsed = parsed
            report.model = model
            report.context = context
            report.mode = str(context.get("backend") or ("aps" if context.get("aps") else "oda"))
            report.warnings = list(getattr(model, "warnings", []) or [])
            report.timings = dict(timings)

            stage = time.perf_counter()
            built = self.build_payload(model)
            timings["payload"] = time.perf_counter() - stage
            report.payload = built.json
            report.payload_meta = built.meta
            if not built.fits_budget:
                report.warnings.append(
                    "payload exceeds CAD2AI_MAX_PAYLOAD_TOKENS by "
                    f"{built.meta.get('budget_exceeded_by')} tokens even after degradation; "
                    "raise the budget or split the drawing per sheet"
                )
            report.timings = dict(timings)

            if target_dir is not None:
                self._write_payload_artifacts(
                    target_dir,
                    model=model,
                    built=built,
                    report=report,
                    raw_manifest=extraction_manifest(context) if include_raw_manifest else None,
                )

            if dry_run:
                logger.info(
                    "dry run: skipping the DeepSeek call (%d chars / ~%d tokens)",
                    built.chars,
                    built.token_estimate,
                )
                if target_dir is not None:
                    self._write_manifest(target_dir, report=report)
                return report

            stage = time.perf_counter()
            messages = build_messages(
                built.json,
                task=resolve_task(task),
                brief=brief,
                context=_run_context(model, report),
            )
            result = self.client().complete(messages, label=str(task))
            timings["deepseek"] = time.perf_counter() - stage
            report.chat_result = result
            report.analysis = result.data
            report.timings = dict(timings)
            self._calibrate(report, result)
            if target_dir is not None:
                self._write_analysis_artifacts(target_dir, report=report)
            return report
        except Cad2AiError as exc:
            report.ok = False
            report.error = exc.to_dict()
            report.timings = dict(timings)
            logger.error("pipeline failed: %s", exc)
            if target_dir is not None:
                self._write_manifest(target_dir, report=report)
            raise
        except Exception as exc:  # noqa: BLE001 - wrap so callers get one error type
            report.ok = False
            report.error = {
                "error": type(exc).__name__,
                "message": str(exc)[:500],
                "hint": "unexpected failure; re-run with CAD2AI_LOG_LEVEL=DEBUG",
                "retryable": False,
                "exit_code": 1,
                "details": {},
            }
            report.timings = dict(timings)
            if target_dir is not None:
                self._write_manifest(target_dir, report=report)
            raise

    # -------------------------------------------------------------- artefacts
    def write_artifacts(
        self,
        out_dir: str | Path,
        *,
        model: Any,
        built: Any,
        report: PipelineReport | None = None,
        raw_manifest: Mapping[str, Any] | None = None,
    ) -> PipelineReport:
        """Public helper: write ``cad_model.json`` + ``payload.json`` (used by the CLI)."""
        target = Path(out_dir)
        own_report = report if report is not None else PipelineReport()
        self._write_payload_artifacts(target, model=model, built=built, report=own_report, raw_manifest=raw_manifest)
        return own_report

    @staticmethod
    def _calibrate(report: PipelineReport, result: Any) -> None:
        """Re-calibrate the heuristic token estimator against the API's usage.

        ``meta.token_estimate`` drives budgeting on the *next* run; without this
        the estimate would be pure guesswork forever.
        """
        actual = getattr(getattr(result, "usage", None), "prompt_tokens", 0) or 0
        estimate = int(report.payload_meta.get("token_estimate") or 0)
        if actual and estimate:
            report.payload_meta["tokenizer_calibration"] = round(actual / estimate, 3)
            report.payload_meta["prompt_tokens_actual"] = actual

    def _write_payload_artifacts(
        self,
        out_dir: Path,
        *,
        model: Any,
        built: Any,
        report: PipelineReport,
        raw_manifest: Mapping[str, Any] | None,
    ) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        model_path = out_dir / "cad_model.json"
        data = model.as_dict() if hasattr(model, "as_dict") else dict(model)
        model_path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        payload_path = out_dir / "payload.json"
        payload_path.write_text(built.json, encoding="utf-8")
        report.artifacts.update({"cad_model": str(model_path), "payload": str(payload_path)})
        if raw_manifest is not None:
            manifest_path = out_dir / "aps_manifest.json"
            manifest_path.write_text(json.dumps(dict(raw_manifest), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            report.artifacts["aps_manifest"] = str(manifest_path)

    def _write_analysis_artifacts(self, out_dir: Path, *, report: PipelineReport) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        if report.analysis is not None:
            analysis_path = out_dir / "analysis.json"
            analysis_path.write_text(json.dumps(report.analysis, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            report.artifacts["analysis"] = str(analysis_path)
            markdown_path = out_dir / "analysis.md"
            markdown_path.write_text(render_markdown(report.analysis), encoding="utf-8")
            report.artifacts["analysis_md"] = str(markdown_path)
        if report.chat_result is not None:
            meta_path = out_dir / "ai_meta.json"
            meta = report.chat_result.as_dict() if hasattr(report.chat_result, "as_dict") else {}
            meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            report.artifacts["ai_meta"] = str(meta_path)
        self._write_manifest(out_dir, report=report)

    def _write_manifest(self, out_dir: Path, *, report: PipelineReport) -> None:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = report.as_dict()
            manifest["config"] = self.settings.to_safe_dict()
            (out_dir / "run_manifest.json").write_text(
                json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8"
            )
            report.artifacts["run_manifest"] = str(out_dir / "run_manifest.json")
        except OSError as exc:  # pragma: no cover - disk trouble must not mask the result
            logger.warning("could not write run_manifest.json: %s", exc)


def extraction_manifest(context: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Pull the raw APS manifest out of the run context (for artifacts)."""
    aps = context.get("aps")
    if isinstance(aps, Mapping):
        return aps.get("manifest") or {key: value for key, value in aps.items() if key != "manifest"}
    return None


def _run_context(model: Any, report: PipelineReport) -> dict[str, Any]:
    document = getattr(model, "document", None)
    units = None
    if isinstance(document, Mapping):
        units = (document.get("units") or {}).get("name")
    source = getattr(model, "source", None)
    lossless = bool(source.get("lossless", True)) if isinstance(source, Mapping) else True
    return {"units": units, "backend": report.mode, "lossless": lossless}


# ---------------------------------------------------------------------------
# markdown rendering of the model's JSON answer
# ---------------------------------------------------------------------------


def render_markdown(data: Any) -> str:
    """Render the model's JSON answer as markdown (loses nothing, reads well)."""
    lines = ["# DeepSeek analysis", ""]
    _render_value(data, lines, level=0)
    lines += ["", "---", "_Generated by cad2ai. Every finding cites a payload path in `evidence`._"]
    return "\n".join(lines)


def _render_value(value: Any, lines: list[str], *, level: int) -> None:
    bullet = "  " * level
    if isinstance(value, Mapping):
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            if isinstance(item, (Mapping, list)) and item:
                if isinstance(item, list) and all(not isinstance(entry, (Mapping, list)) for entry in item):
                    lines.append(f"{bullet}- **{key}**: {_inline_list(item)}")
                else:
                    lines.append(f"{bullet}- **{key}**")
                    _render_value(item, lines, level=level + 1)
            else:
                lines.append(f"{bullet}- **{key}**: {_scalar(item)}")
    elif isinstance(value, list):
        for index, item in enumerate(value, start=1):
            if isinstance(item, Mapping):
                label = (
                    item.get("title")
                    or item.get("name")
                    or item.get("rule")
                    or item.get("layer")
                    or item.get("risk")
                    or item.get("item")
                    or f"item {index}"
                )
                lines.append(f"{bullet}- **{_scalar(label)}**{_tag_suffix(item)}")
                _render_value({key: val for key, val in item.items() if key not in ("title", "name")}, lines, level=level + 1)
            elif isinstance(item, (list, tuple)):
                lines.append(f"{bullet}- item {index}")
                _render_value(item, lines, level=level + 1)
            else:
                lines.append(f"{bullet}- {_scalar(item)}")
    else:
        lines.append(f"{bullet}- {_scalar(value)}")


def _tag_suffix(item: Mapping[str, Any]) -> str:
    for key in ("severity", "status"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return f"  `{value}`"
    return ""


def _inline_list(items: Iterable[Any]) -> str:
    return ", ".join(_scalar(item) for item in items)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_scalar(item) for item in value)
    return str(value).strip()


# ---------------------------------------------------------------------------
# module-level convenience functions
# ---------------------------------------------------------------------------


def extract(
    path: str | Path,
    *,
    settings: Settings | None = None,
    fallback: str = "auto",
    **load_kwargs: Any,
) -> tuple[Any, Any]:
    """Phases 1 + 2 only: return ``(parsed_or_None, cad_model)``."""
    pipeline = Pipeline(settings or Settings.from_env())
    parsed, model, _ = pipeline.extract(path, fallback=fallback, **load_kwargs)
    return parsed, model


def analyze_file(
    path: str | Path,
    *,
    task: str = "discipline_summary",
    brief: str | None = None,
    out_dir: str | Path | None = None,
    settings: Settings | None = None,
    fallback: str = "auto",
    dry_run: bool = False,
    **load_kwargs: Any) -> PipelineReport:
    """One-shot helper: run the full pipeline and return the report."""
    pipeline = Pipeline(settings or Settings.from_env())
    return pipeline.run(path, task=task, brief=brief, out_dir=out_dir, fallback=fallback, dry_run=dry_run, **load_kwargs)


def cleanup_dir(path: str | Path, *, keep: Iterable[str] = ()) -> list[str]:
    """Remove intermediates a caller does not want kept (CLI ``--clean``)."""
    target = Path(path)
    if not target.is_dir():
        return []
    keep_set = set(keep)
    removed: list[str] = []
    for entry in target.iterdir():
        if entry.name in keep_set:
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed.append(entry.name)
        except OSError:  # pragma: no cover
            logger.debug("could not remove %s", entry)
    return removed
