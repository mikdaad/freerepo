"""Command line interface (``python main.py ...`` / ``cad2ai`` console script).

Subcommands mirror the pipeline phases so each can be run and debugged alone::

    doctor    environment + credential report (no data sent, except --check-api)
    extract   Phase 1 + 2  -> cad_model.json / payload.json
    analyze   Phase 1 + 2 + 3 -> analysis.json / analysis.md (+ manifest)
    payload   Phase 1 + 2, print the minified payload (pipe it anywhere)
    prompt    show the exact prompt that would be sent (prompt-engineering aid)
    aps       Phase 1 via Autodesk Platform Services only (upload/translate/manifest)

Exit codes (stable contract): 0 ok, 2 config/usage, 3 unsupported DWG version,
4 parse failure, 5 Autodesk failure, 6 DeepSeek failure, 1 unexpected.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from cad2ai import __version__
from cad2ai.config import KNOWN_MODELS, Settings
from cad2ai.errors import EXIT_CONFIG, EXIT_UNEXPECTED, Cad2AiError, ConfigError
from cad2ai.pipeline import Pipeline

logger = logging.getLogger("cad2ai.cli")

TASK_CHOICES = (
    "discipline_summary",
    "sheet_review",
    "bom",
    "complexity_metrics",
    "standards_compliance",
    "custom",
)


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cad2ai",
        description="Extract AutoCAD DWG data with ezdxf+odafc and analyse it with DeepSeek.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python main.py doctor\n"
            "  python main.py extract drawings/A-101.dwg --out out/a101\n"
            "  python main.py analyze drawings/A-101.dwg --task sheet_review --out out/a101\n"
            "  python main.py analyze mech.dwg --task bom --brief 'Only stainless fasteners' --thinking enabled\n"
            "  python main.py analyze A-101.dwg --dry-run            # payload only, no API call\n"
            "  python main.py aps legacy.dwg --status-only            # Autodesk fallback path\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"cad2ai {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v for INFO, -vv for DEBUG")
    parser.add_argument("--env-file", help="path to a .env file (default: search upward from the CWD)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON on stdout")
    # ``cad2ai extract f.dxf --json`` must work as well as ``cad2ai --json extract f.dxf``:
    # the same flags are re-declared on every subcommand with SUPPRESS defaults, so an
    # absent flag leaves whatever the top-level parser already decided untouched.
    globals_parser = argparse.ArgumentParser(add_help=False)
    globals_parser.add_argument("-v", "--verbose", action="count", default=argparse.SUPPRESS)
    globals_parser.add_argument("--env-file", default=argparse.SUPPRESS)
    globals_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    # -- doctor ------------------------------------------------------------
    doctor = sub.add_parser("doctor", help="report parser/converter/API availability", parents=[globals_parser])
    doctor.add_argument("--check-api", action="store_true", help="make a 1-token DeepSeek call to verify auth")
    doctor.add_argument("--check-aps", action="store_true", help="request an APS 2-legged token to verify credentials")

    # -- shared extract/analyze options ------------------------------------
    common = argparse.ArgumentParser(add_help=False)
    # Optional so that ``aps --status-only --urn ...`` works without a file.
    common.add_argument("file", nargs="?", help="input .dwg or .dxf file")
    common.add_argument("--out", help="directory for artifacts (created if missing)")
    common.add_argument(
        "--fallback",
        choices=("auto", "none", "aps"),
        default="auto",
        help="what to do when the local parse fails: auto (try APS if configured), none (fail), aps (force APS)",
    )
    common.add_argument("--backend", choices=("auto", "oda", "dxf"), default="auto", help="Phase 1 loader")
    common.add_argument("--no-audit", action="store_true", help="skip doc.audit() (faster, less diagnostics)")
    common.add_argument("--keep-dxf", help="keep the intermediate DXF produced by ODA in this directory")
    common.add_argument("--payload-tokens", type=int, help="token budget for the JSON payload (overrides .env)")
    common.add_argument("--max-text", type=int, help="cap on collected text entities")
    common.add_argument("--max-dimensions", type=int, help="cap on collected dimensions")
    common.add_argument("--max-blocks", type=int, help="cap on reported block definitions")
    common.add_argument("--max-layers", type=int, help="cap on reported layers")
    common.add_argument("--include-handles", action="store_true", help="include DXF handles (debugging; costs tokens)")
    common.add_argument("--float-precision", type=int, help="decimal places kept for coordinates (0-6)")

    # -- extract -----------------------------------------------------------
    extract = sub.add_parser("extract", parents=[globals_parser, common], help="run Phase 1 + 2 and write artifacts")
    extract.add_argument("--summary-only", action="store_true", help="print just the summary JSON")

    # -- analyze -----------------------------------------------------------
    analyze = sub.add_parser("analyze", parents=[globals_parser, common], help="run the full pipeline (Phase 1 + 2 + 3)")
    analyze.add_argument("--task", choices=TASK_CHOICES, default="discipline_summary", help="analysis job")
    analyze.add_argument("--brief", help="free-form instructions for the model (client brief)")
    analyze.add_argument("--brief-file", help="read the brief from a file ('-' for stdin)")
    analyze.add_argument("--model", help=f"DeepSeek model id (default from .env; known: {', '.join(KNOWN_MODELS)})")
    analyze.add_argument("--max-tokens", type=int, help="DEEPSEEK_MAX_TOKENS override for this call")
    analyze.add_argument("--temperature", type=float, help="sampling temperature (ignored in thinking mode)")
    analyze.add_argument(
        "--thinking",
        choices=("enabled", "disabled"),
        help="DeepSeek thinking mode (chain of thought); overrides DEEPSEEK_THINKING",
    )
    analyze.add_argument("--reasoning-effort", choices=("low", "high", "max"), help="thinking effort (enabled mode only)")
    analyze.add_argument("--no-json-mode", action="store_true", help="disable response_format=json_object (prose answers)")
    analyze.add_argument("--dry-run", action="store_true", help="build and save the payload, do not call the API")
    analyze.add_argument("--show-markdown", action="store_true", help="print the rendered markdown report")
    analyze.add_argument("--raw-manifest", action="store_true", help="also save the raw APS manifest when falling back")

    # -- payload / prompt --------------------------------------------------
    payload = sub.add_parser("payload", parents=[globals_parser, common], help="print the minified JSON payload")
    payload.add_argument("--write", help="write the payload to this file instead of stdout")
    prompt = sub.add_parser("prompt", parents=[globals_parser, common], help="print the prompt that would be sent")
    prompt.add_argument("--task", choices=TASK_CHOICES, default="discipline_summary")
    prompt.add_argument("--brief", help="free-form instructions for the model")
    prompt.add_argument("--system-only", action="store_true", help="print only the system prompt")

    # -- aps ---------------------------------------------------------------
    aps = sub.add_parser("aps", parents=[globals_parser, common], help="Autodesk Platform Services extraction only")
    aps.add_argument("--object-key", help="OSS object key to use (default: name+sha based)")
    aps.add_argument("--force", action="store_true", help="re-upload and force re-translation")
    aps.add_argument("--status-only", action="store_true", help="fetch the manifest of --urn, do not upload")
    aps.add_argument("--urn", help="encoded design URN (with --status-only)")
    aps.add_argument("--no-wait", action="store_true", help="submit the job and return without polling")
    aps.add_argument("--delete-after", action="store_true", help="delete the uploaded object when done")
    aps.add_argument("--timeout", type=float, help="translation wait timeout in seconds")
    # NOTE: --out/--json/--file come from ``common``; do not redeclare them here.

    return parser


def _require_file(args: argparse.Namespace) -> str:
    """Commands that parse a drawing need a path; ``aps --status-only`` does not."""
    path = getattr(args, "file", None)
    if not path:
        raise ConfigError(
            f"the {args.command} command needs an input file",
            hint="pass a .dwg or .dxf path, e.g. `cad2ai analyze drawings/A-101.dwg`",
        )
    return str(path)


def _settings_from_args(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if getattr(args, "payload_tokens", None):
        overrides["payload_max_tokens"] = args.payload_tokens
    if getattr(args, "max_text", None) is not None:
        overrides["max_text_items"] = args.max_text
    if getattr(args, "max_dimensions", None) is not None:
        overrides["max_dimensions"] = args.max_dimensions
    if getattr(args, "max_blocks", None) is not None:
        overrides["max_blocks"] = args.max_blocks
    if getattr(args, "max_layers", None) is not None:
        overrides["max_layers"] = args.max_layers
    if getattr(args, "include_handles", None):
        overrides["include_handles"] = True
    if getattr(args, "float_precision", None) is not None:
        overrides["float_precision"] = args.float_precision
    if getattr(args, "model", None):
        overrides["deepseek_model"] = args.model
    if getattr(args, "max_tokens", None) is not None:
        overrides["deepseek_max_tokens"] = args.max_tokens
    if getattr(args, "temperature", None) is not None:
        overrides["deepseek_temperature"] = args.temperature
    if getattr(args, "thinking", None):
        overrides["deepseek_thinking"] = args.thinking
    if getattr(args, "reasoning_effort", None):
        overrides["deepseek_reasoning_effort"] = args.reasoning_effort
    if getattr(args, "no_json_mode", False):
        overrides["deepseek_json_mode"] = False
    if getattr(args, "verbose", 0) >= 1:
        overrides["log_level"] = "DEBUG" if args.verbose >= 2 else "INFO"
    return Settings.from_env(dotenv_path=getattr(args, "env_file", None), **overrides)


def _configure_logging(settings: Settings, *, quiet: bool = False) -> None:
    level = logging.DEBUG if settings.log_level == "DEBUG" else logging.WARNING if quiet else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger("cad2ai")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def _read_brief(args: argparse.Namespace) -> str | None:
    brief = getattr(args, "brief", None)
    path = getattr(args, "brief_file", None)
    if path:
        if path == "-":
            return sys.stdin.read().strip() or None
        return Path(path).read_text(encoding="utf-8").strip() or None
    return brief


def _load_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    backend = getattr(args, "backend", None)
    if backend and backend != "auto":
        kwargs["backend"] = backend
    if getattr(args, "no_audit", False):
        kwargs["audit"] = False
    keep = getattr(args, "keep_dxf", None)
    if keep:
        kwargs["keep_converted_dxf"] = keep
    return kwargs


def _emit(args: argparse.Namespace, human: str, data: Any) -> None:
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")
    else:
        sys.stdout.write(human.rstrip() + "\n")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    from cad2ai.parser import describe_backend_availability

    report: dict[str, Any] = {
        "cad2ai_version": __version__,
        "phase1_local": describe_backend_availability(),
        "deepseek": {
            "base_url": settings.deepseek_base_url,
            "model": settings.deepseek_model,
            "model_known": settings.deepseek_model in KNOWN_MODELS,
            "api_key_present": bool(settings.deepseek_api_key),
            "thinking": settings.deepseek_thinking,
            "reasoning_effort": settings.deepseek_reasoning_effort,
            "max_tokens": settings.deepseek_max_tokens,
            "json_mode": settings.deepseek_json_mode,
            "timeout": settings.deepseek_timeout,
            "max_attempts": settings.deepseek_max_attempts,
        },
        "phase2": {
            "payload_max_tokens": settings.payload_max_tokens,
            "max_text_items": settings.max_text_items,
            "max_dimensions": settings.max_dimensions,
            "float_precision": settings.float_precision,
            "include_handles": settings.include_handles,
        },
        "autodesk_fallback": {
            "configured": bool(settings.aps_client_id and settings.aps_client_secret and settings.aps_bucket_key),
            "base_url": settings.aps_base_url,
            "bucket_key": settings.aps_bucket_key,
            "output_format": settings.aps_output_format,
        },
    }
    problems: list[str] = []
    if not report["phase1_local"]["oda_installed"]:
        problems.append("ODA File Converter not found: .dwg input will need --fallback aps or a manual DXF export")
    if not settings.deepseek_api_key:
        problems.append("DEEPSEEK_API_KEY is not set: Phase 3 (analyze without --dry-run) will fail")
    if not report["phase1_local"]["xvfb_available"] and report["phase1_local"]["platform"] == "Linux":
        problems.append("Xvfb missing on Linux: the ODA converter may try to open a GUI window")
    if not report["deepseek"]["model_known"]:
        problems.append(f"model {settings.deepseek_model!r} is not in the known list (fine if your account has it)")
    report["problems"] = problems

    if args.check_api:
        from cad2ai.ai_client import DeepSeekClient, DeepSeekConfig, RateLimitPolicy

        try:
            client = DeepSeekClient(
                DeepSeekConfig.from_settings(settings),
                policy=RateLimitPolicy.from_settings(settings),
            )
            report["deepseek"]["health"] = client.health_check()
        except Cad2AiError as exc:
            report["deepseek"]["health"] = {"error": exc.to_dict()}
    if args.check_aps:
        try:
            from cad2ai.aps import ApsClient, ApsConfig

            client = ApsClient(ApsConfig.from_settings(settings))
            report["autodesk_fallback"]["health"] = client.introspect()
        except Cad2AiError as exc:
            report["autodesk_fallback"]["health"] = {"error": exc.to_dict()}

    if getattr(args, "json", False):
        # machine-readable mode prints *only* JSON so `--json | jq` works
        sys.stdout.write(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
        return 0
    print("cad2ai environment report")
    print("=" * 60)
    print(f"version            : {__version__}")
    phase1 = report["phase1_local"]
    print(f"platform           : {phase1['platform']}   ezdxf {phase1['ezdxf_version']}")
    print(f"ODA converter      : {'found' if phase1['oda_installed'] else 'NOT FOUND'}   {phase1.get('oda_executable') or ''}")
    print(f"Xvfb (headless)    : {'found' if phase1['xvfb_available'] else 'not found'}")
    print(f"DeepSeek           : {report['deepseek']['base_url']} model={report['deepseek']['model']}"
          f" key={'set' if report['deepseek']['api_key_present'] else 'MISSING'}")
    print(f"                   thinking={report['deepseek']['thinking']} json_mode={report['deepseek']['json_mode']}"
          f" max_tokens={report['deepseek']['max_tokens']}")
    print(f"Payload budget     : {report['phase2']['payload_max_tokens']} tokens (text<={report['phase2']['max_text_items']},"
          f" dims<={report['phase2']['max_dimensions']})")
    print(f"APS fallback       : {'configured' if report['autodesk_fallback']['configured'] else 'not configured'}")
    for section in ("deepseek", "autodesk_fallback"):
        health = report[section].get("health")
        if health:
            print(f"{section} health  : {json.dumps(health, ensure_ascii=False, default=str)[:400]}")
    if problems:
        print("\nwarnings:")
        for problem in problems:
            print(f"  - {problem}")
    return 0


def cmd_extract(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = Pipeline(settings)
    out_dir = Path(args.out) if args.out else None
    target = _require_file(args)
    parsed, model, context = pipeline.extract(target, fallback=args.fallback, **_load_kwargs(args))
    built = pipeline.build_payload(model)
    if out_dir is not None:
        pipeline.write_artifacts(out_dir, model=model, built=built)
    data = {
        "summary": model.summary(),
        "payload": {
            "chars": built.chars,
            "token_estimate": built.token_estimate,
            "degraded": built.meta.get("degraded"),
            "truncations": built.meta.get("truncations"),
        },
        "backend": context.get("backend"),
        "artifacts": dict((out_dir and {"dir": str(out_dir)}) or {}),
        "warnings": list(model.warnings)[:10],
    }
    if args.summary_only and getattr(args, "json", False):
        sys.stdout.write(json.dumps(data["summary"], indent=1, ensure_ascii=False, default=str) + "\n")
        return 0
    human = (
        f"parsed {model.source.get('file') or model.source.get('name')} via {context.get('backend')}\n"
        f"units: {data['summary']['units']}  layers: {data['summary']['layers']}  blocks: {data['summary']['blocks']}"
        f"  entities: {data['summary']['entities']}\n"
        f"payload: {built.chars} chars / ~{built.token_estimate} tokens"
        + (f"  (degraded: {', '.join(built.meta['degraded'])})" if built.meta.get("degraded") else "")
        + (f"\nartifacts: {out_dir}" if out_dir else "")
    )
    _emit(args, human, data)
    return 0


def cmd_analyze(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = Pipeline(settings)
    brief = _read_brief(args)
    report = pipeline.run(
        _require_file(args),
        task=args.task,
        brief=brief,
        out_dir=args.out,
        fallback=args.fallback,
        dry_run=args.dry_run,
        include_raw_manifest=args.raw_manifest,
        **_load_kwargs(args),
    )
    data = report.summary
    if args.dry_run:
        data = {**data, "dry_run": True}
    if getattr(args, "json", False):
        payload = dict(data)
        payload["analysis"] = report.analysis
        if args.show_markdown:
            from cad2ai.pipeline import render_markdown

            payload["markdown"] = render_markdown(report.analysis) if report.analysis else None
        sys.stdout.write(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n")
        return 0

    summary = report.summary
    print(f"mode: {report.mode}   task: {report.task}   dry-run: {args.dry_run}")
    print(f"payload: {summary['payload']['chars']} chars / ~{summary['payload']['token_estimate']} tokens"
          f" (budget {summary['payload']['token_budget']})")
    if summary["payload"]["degraded"]:
        print(f"payload degraded: {', '.join(summary['payload']['degraded'])}")
    if report.usage:
        print(f"tokens: {json.dumps(report.usage, ensure_ascii=False)}")
    print(f"elapsed: {summary['latency_seconds']}s")
    if args.show_markdown and report.analysis is not None:
        from cad2ai.pipeline import render_markdown

        print("\n" + render_markdown(report.analysis))
    else:
        if report.analysis is None:
            print("\n(no analysis produced)")
        else:
            print("\n" + json.dumps(report.analysis, indent=1, ensure_ascii=False, default=str))
    if report.artifacts:
        print("\nartifacts:")
        for name, path in report.artifacts.items():
            print(f"  {name:<12} {path}")
    return 0


def cmd_payload(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = Pipeline(settings)
    _parsed, model, _context = pipeline.extract(_require_file(args), fallback=args.fallback, **_load_kwargs(args))
    built = pipeline.build_payload(model)
    if args.write:
        target = Path(args.write)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(built.json, encoding="utf-8")
        print(f"wrote {target} ({built.chars} chars, ~{built.token_estimate} tokens)", file=sys.stderr)
    else:
        sys.stdout.write(built.json + "\n")
    return 0


def cmd_prompt(args: argparse.Namespace, settings: Settings) -> int:
    from cad2ai.prompts import build_messages, build_system_prompt

    if args.system_only:
        print(build_system_prompt(output_mode="json" if settings.deepseek_json_mode else "markdown"))
        return 0
    pipeline = Pipeline(settings)
    _parsed, model, _context = pipeline.extract(_require_file(args), fallback=args.fallback, **_load_kwargs(args))
    built = pipeline.build_payload(model)
    messages = build_messages(built.json, task=args.task, brief=_read_brief(args))
    for message in messages:
        print(f"### role: {message['role']}\n")
        print(message["content"])
        print()
    return 0


def cmd_aps(args: argparse.Namespace, settings: Settings) -> int:
    from cad2ai.aps import ApsClient, ApsConfig, normalize_manifest

    if args.status_only and not args.urn:
        raise ConfigError(
            "--status-only requires --urn <encoded design urn>",
            hint="the URN is the base64url form of urn:adsk.objects:os.object:<bucket>/<key>",
        )
    if not args.status_only:
        _require_file(args)

    config_overrides: dict[str, Any] = {}
    if args.delete_after:
        config_overrides["delete_after_extract"] = True
    if args.timeout:
        config_overrides["translation_timeout"] = args.timeout
    config = ApsConfig.from_settings(settings)
    if config_overrides:
        config = ApsConfig(**{**config.__dict__, **config_overrides})
    client = ApsClient(config)

    if args.status_only:
        manifest = client.get_manifest(args.urn)
        structure = normalize_manifest(manifest)
        output = {"manifest": manifest, "structure": structure}
    else:
        extraction = client.extract(
            _require_file(args),
            object_key=args.object_key,
            wait=not args.no_wait,
            force_translation=args.force,
        )
        output = extraction.as_dict()

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "aps_manifest.json").write_text(json.dumps(output, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"wrote {out_dir / 'aps_manifest.json'}", file=sys.stderr)
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(output, indent=1, ensure_ascii=False, default=str) + "\n")
    else:
        structure = output.get("structure") or {}
        print(f"object      : {(output.get('object') or {}).get('object_key')}")
        print(f"status      : {structure.get('status') or (output.get('manifest') or {}).get('status')}")
        print(f"views       : {len(structure.get('views') or [])}")
        print(f"layers seen : {len(structure.get('layers') or [])}")
        print(f"properties  : {len(output.get('properties') or [])}")
        if output.get("warnings"):
            print("warnings:")
            for warning in output["warnings"][:10]:
                print(f"  - {warning}")
    return 0


COMMANDS = {
    "doctor": cmd_doctor,
    "extract": cmd_extract,
    "analyze": cmd_analyze,
    "payload": cmd_payload,
    "prompt": cmd_prompt,
    "aps": cmd_aps,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _settings_from_args(args)
        _configure_logging(settings, quiet=getattr(args, "json", False))
    except Cad2AiError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return exc.exit_code or EXIT_CONFIG

    handler = COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse enforces the choices
        parser.error(f"unknown command {args.command!r}")
        return 2
    try:
        return int(handler(args, settings) or 0)
    except Cad2AiError as exc:
        if getattr(args, "json", False):
            sys.stdout.write(json.dumps({"ok": False, "error": exc.to_dict()}, indent=1, ensure_ascii=False) + "\n")
        else:
            print(f"\n{type(exc).__name__}: {exc.message}", file=sys.stderr)
            if exc.hint:
                print(f"  hint: {exc.hint}", file=sys.stderr)
            if os.environ.get("CAD2AI_TRACEBACK") == "1":
                import traceback

                traceback.print_exc()
        return exc.exit_code or 1
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - a CLI must never print a bare traceback
        if os.environ.get("CAD2AI_TRACEBACK") == "1":
            raise
        if getattr(args, "json", False):
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "error": type(exc).__name__,
                            "message": str(exc)[:500],
                            "hint": "re-run with CAD2AI_TRACEBACK=1 to see the traceback, and please report it",
                            "retryable": False,
                            "exit_code": EXIT_UNEXPECTED,
                        },
                    },
                    indent=1,
                    ensure_ascii=False,
                )
                + "\n"
            )
        else:
            print(f"\nunexpected error: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            print("  hint: re-run with CAD2AI_TRACEBACK=1 for the traceback", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
