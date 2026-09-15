"""Runtime configuration: `.env` loading, validation, and defaults.

Precedence (highest wins): explicit ``overrides`` -> process environment ->
``./.env`` -> built-in defaults.  Secrets are never printed; use
:meth:`Settings.to_safe_dict` for anything that reaches logs or artifacts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

from cad2ai.errors import ConfigError, MissingEnvironmentVariableError

__all__ = ["Settings", "load_dotenv_once", "KNOWN_MODELS"]

# DeepSeek renames models fairly often (deepseek-chat/deepseek-reasoner ->
# deepseek-v4-* -> deepseek-flash).  The list only drives a warning, never a
# hard failure, so a rename does not take a pipeline down.
KNOWN_MODELS: tuple[str, ...] = (
    "deepseek-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-chat",
    "deepseek-reasoner",
)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n", ""}

_dotenv_loaded: set[str] = set()
#: key used for the implicit "search upward from the CWD" lookup
_DOTENV_AUTO = "<auto>"


def reset_dotenv_cache() -> None:
    """Forget which ``.env`` files were loaded (tests / long-lived processes)."""
    _dotenv_loaded.clear()


def load_dotenv_once(path: str | os.PathLike[str] | None = None, *, override: bool = False) -> bool:
    """Load a ``.env`` file, at most once per process *per path*.

    Returns ``True`` when a file was found and parsed.  Memoising per path (rather
    than globally) matters: ``cad2ai --env-file prod.env`` must work even if
    something earlier in the process already ran the default upward lookup.
    ``python-dotenv`` is imported lazily so a process that only passes an explicit
    environment never needs it.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - dotenv is in requirements.txt
        return False
    explicit = path is not None and str(path).strip() != ""
    if explicit:
        target = str(path)
    else:
        try:
            target = find_dotenv(filename=".env", usecwd=True) or ""
        except OSError:  # pragma: no cover - unreadable CWD
            target = ""
    if not target:
        return False
    key = target if explicit else _DOTENV_AUTO
    if key in _dotenv_loaded:
        return False
    _dotenv_loaded.add(key)
    if explicit and not Path(target).is_file():
        raise ConfigError(
            f"--env-file points at a file that does not exist: {target}",
            hint="pass the path to an existing .env file, or omit --env-file to search upward from the CWD",
        )
    try:
        return bool(load_dotenv(target, override=override))
    except OSError as exc:  # pragma: no cover - unreadable .env should not be fatal
        raise ConfigError(f"could not read --env-file {target}: {exc}") from exc


def _lookup(name: str, environ: Mapping[str, str] | None) -> str | None:
    if environ is not None:
        value = environ.get(name)
        return value if value not in (None, "") else None
    value = os.environ.get(name)
    return value if value not in (None, "") else None


def _str(name: str, default: str | None, environ: Mapping[str, str] | None) -> str | None:
    value = _lookup(name, environ)
    return value.strip() if value is not None else default


def _int(name: str, default: int, environ: Mapping[str, str] | None) -> int:
    raw = _lookup(name, environ)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float, environ: Mapping[str, str] | None) -> float:
    raw = _lookup(name, environ)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _bool(name: str, default: bool, environ: Mapping[str, str] | None) -> bool:
    raw = _lookup(name, environ)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigError(f"{name} must be a boolean-ish value (1/0, true/false), got {raw!r}")


def _choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    """Immutable, fully validated configuration for all three phases."""

    # --- Phase 3: DeepSeek -------------------------------------------------
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_BASE_URL
    deepseek_model: str = DEFAULT_MODEL
    deepseek_max_tokens: int = 8000
    deepseek_temperature: float = 0.0
    deepseek_thinking: str = "disabled"
    deepseek_reasoning_effort: str | None = None
    deepseek_timeout: float = 180.0
    deepseek_max_attempts: int = 5
    deepseek_retry_min_delay: float = 1.0
    deepseek_retry_max_delay: float = 60.0
    deepseek_min_interval_ms: int = 0
    deepseek_extra_headers: Mapping[str, str] = field(default_factory=dict)
    #: JSON mode is on by default: the pipeline consumes structured output.
    deepseek_json_mode: bool = True
    #: When JSON mode returns empty content, retry this many extra times.
    deepseek_empty_content_retries: int = 2

    # --- Phase 1: local DWG parsing ---------------------------------------
    oda_executable: str | None = None
    oda_target_version: str = "ACAD2018"
    #: also accept DWG generations ezdxf can only partly represent (R13/R14)
    allow_legacy_versions: bool = False
    max_file_mb: float = 512.0
    #: wall-clock guard for a single ODA File Converter invocation (seconds)
    oda_timeout: float = 300.0

    # --- Phase 2: payload budgeting ---------------------------------------
    payload_max_tokens: int = 120_000
    max_text_items: int = 800
    max_dimensions: int = 400
    max_blocks: int = 120
    max_layers: int = 200
    float_precision: int = 3
    include_handles: bool = False

    # --- Phase 1 fallback: Autodesk Platform Services ---------------------
    aps_client_id: str | None = None
    aps_client_secret: str | None = None
    aps_base_url: str = "https://developer.api.autodesk.com"
    aps_bucket_key: str | None = None
    aps_policy_key: str = "transient"
    aps_scopes: str = "data:read data:write data:create bucket:create bucket:read"
    aps_output_format: str = "svf2"
    aps_translation_timeout: float = 900.0
    aps_max_upload_part_mb: int = 8
    aps_timeout: float = 60.0

    # --- misc --------------------------------------------------------------
    log_level: str = "INFO"

    # ------------------------------------------------------------------ ctors
    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        dotenv_path: str | os.PathLike[str] | None = None,
        **overrides: Any,
    ) -> "Settings":
        """Build settings from ``.env`` + process environment + ``overrides``."""
        if environ is None:
            load_dotenv_once(dotenv_path)
        env = environ

        kwargs: dict[str, Any] = {
            "deepseek_api_key": _str("DEEPSEEK_API_KEY", None, env),
            "deepseek_base_url": (_str("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL, env) or DEFAULT_BASE_URL).rstrip("/"),
            "deepseek_model": _str("DEEPSEEK_MODEL", DEFAULT_MODEL, env) or DEFAULT_MODEL,
            "deepseek_max_tokens": _int("DEEPSEEK_MAX_TOKENS", 8000, env),
            "deepseek_temperature": _float("DEEPSEEK_TEMPERATURE", 0.0, env),
            "deepseek_thinking": (_str("DEEPSEEK_THINKING", "disabled", env) or "disabled").lower(),
            "deepseek_reasoning_effort": _str("DEEPSEEK_REASONING_EFFORT", None, env),
            "deepseek_timeout": _float("DEEPSEEK_TIMEOUT", 180.0, env),
            "deepseek_max_attempts": _int("DEEPSEEK_MAX_ATTEMPTS", 5, env),
            "deepseek_retry_min_delay": _float("DEEPSEEK_RETRY_MIN_DELAY", 1.0, env),
            "deepseek_retry_max_delay": _float("DEEPSEEK_RETRY_MAX_DELAY", 60.0, env),
            "deepseek_min_interval_ms": _int("DEEPSEEK_MIN_INTERVAL_MS", 0, env),
            "deepseek_json_mode": _bool("DEEPSEEK_JSON_MODE", True, env),
            "oda_executable": _str("ODA_EXECUTABLE", None, env),
            "oda_target_version": _str("ODA_TARGET_VERSION", "ACAD2018", env) or "ACAD2018",
            "allow_legacy_versions": _bool("CAD2AI_ALLOW_LEGACY_VERSIONS", False, env),
            "max_file_mb": _float("CAD2AI_MAX_FILE_MB", 512.0, env),
            "oda_timeout": _float("CAD2AI_ODA_TIMEOUT", 300.0, env),
            "payload_max_tokens": _int("CAD2AI_MAX_PAYLOAD_TOKENS", 120_000, env),
            "max_text_items": _int("CAD2AI_MAX_TEXT_ITEMS", 800, env),
            "max_dimensions": _int("CAD2AI_MAX_DIMENSIONS", 400, env),
            "max_blocks": _int("CAD2AI_MAX_BLOCKS", 120, env),
            "max_layers": _int("CAD2AI_MAX_LAYERS", 200, env),
            "float_precision": _int("CAD2AI_FLOAT_PRECISION", 3, env),
            "include_handles": _bool("CAD2AI_INCLUDE_HANDLES", False, env),
            "aps_client_id": _str("APS_CLIENT_ID", None, env),
            "aps_client_secret": _str("APS_CLIENT_SECRET", None, env),
            "aps_base_url": (_str("APS_BASE_URL", "https://developer.api.autodesk.com", env) or "").rstrip("/"),
            "aps_bucket_key": _str("APS_BUCKET_KEY", None, env),
            "aps_policy_key": _str("APS_POLICY_KEY", "transient", env) or "transient",
            "aps_scopes": _str("APS_SCOPES", "data:read data:write data:create bucket:create bucket:read", env)
            or "data:read data:write data:create bucket:create bucket:read",
            "aps_output_format": (_str("APS_OUTPUT_FORMAT", "svf2", env) or "svf2").lower(),
            "aps_translation_timeout": _float("APS_TRANSLATION_TIMEOUT", 900.0, env),
            "aps_max_upload_part_mb": _int("APS_MAX_UPLOAD_PART_MB", 8, env),
            "log_level": (_str("CAD2AI_LOG_LEVEL", "INFO", env) or "INFO").upper(),
        }
        kwargs.update({k: v for k, v in overrides.items() if v is not None})
        unknown = set(kwargs) - {f.name for f in fields(cls)}
        if unknown:  # guards against typos in overrides
            raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")
        settings = cls(**kwargs)
        settings._validate()
        return settings

    def _validate(self) -> None:
        if self.deepseek_max_tokens <= 0:
            raise ConfigError("DEEPSEEK_MAX_TOKENS must be > 0")
        if not 0.0 <= self.deepseek_temperature <= 2.0:
            raise ConfigError("DEEPSEEK_TEMPERATURE must be within 0..2")
        _choice("DEEPSEEK_THINKING", self.deepseek_thinking, ("enabled", "disabled"))
        if self.deepseek_reasoning_effort is not None:
            _choice(
                "DEEPSEEK_REASONING_EFFORT",
                self.deepseek_reasoning_effort.lower(),
                ("low", "medium", "high", "max"),
            )
            object.__setattr__(self, "deepseek_reasoning_effort", self.deepseek_reasoning_effort.lower())
        if self.deepseek_max_attempts < 1:
            raise ConfigError("DEEPSEEK_MAX_ATTEMPTS must be >= 1")
        if self.payload_max_tokens < 512:
            raise ConfigError("CAD2AI_MAX_PAYLOAD_TOKENS must be >= 512 tokens")
        if not 0 <= self.float_precision <= 6:
            raise ConfigError("CAD2AI_FLOAT_PRECISION must be between 0 and 6")
        _choice("APS_OUTPUT_FORMAT", self.aps_output_format, ("svf2", "svf"))
        if self.max_file_mb <= 0:
            raise ConfigError("CAD2AI_MAX_FILE_MB must be > 0")
        if self.oda_timeout <= 0:
            raise ConfigError("CAD2AI_ODA_TIMEOUT must be > 0")

    # -------------------------------------------------------------- accessors
    @property
    def thinking_enabled(self) -> bool:
        return self.deepseek_thinking == "enabled"

    @property
    def uses_known_model(self) -> bool:
        return self.deepseek_model in KNOWN_MODELS

    def require_deepseek_key(self) -> str:
        if not self.deepseek_api_key:
            raise MissingEnvironmentVariableError(
                "DEEPSEEK_API_KEY",
                hint="create a key at https://platform.deepseek.com/api_keys and put it in ./.env",
            )
        return self.deepseek_api_key

    def require_aps_credentials(self) -> tuple[str, str, str]:
        missing = [
            name
            for name, value in (
                ("APS_CLIENT_ID", self.aps_client_id),
                ("APS_CLIENT_SECRET", self.aps_client_secret),
                ("APS_BUCKET_KEY", self.aps_bucket_key),
            )
            if not value
        ]
        if missing:
            raise MissingEnvironmentVariableError(
                missing[0],
                details={"missing": missing},
                hint=(
                    "the APS fallback needs APS_CLIENT_ID, APS_CLIENT_SECRET and APS_BUCKET_KEY "
                    "(create a Server-to-Server app at https://aps.autodesk.com -> My Applications)"
                ),
            )
        return self.aps_client_id or "", self.aps_client_secret or "", self.aps_bucket_key or ""

    def to_safe_dict(self) -> dict[str, Any]:
        """Config snapshot with secrets masked -- safe for artifacts/logs."""
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None or isinstance(value, (int, float, str, bool)) or isinstance(value, Mapping):
                out[f.name] = _mask(f.name, value)
            else:  # pragma: no cover - all fields are scalars today
                out[f.name] = str(value)
        return out


def _mask(name: str, value: Any) -> Any:
    secret_markers = ("api_key", "secret", "token")
    if not isinstance(value, str) or not any(marker in name for marker in secret_markers):
        return value
    if not value:
        return ""
    return f"***{value[-4:]}" if len(value) > 8 else "***"
