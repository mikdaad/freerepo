"""Typed error hierarchy for the whole pipeline.

Every failure the pipeline can raise is a subclass of :class:`Cad2AiError` and
carries three things the CLI and any embedding service need:

``message``
    human readable, single-sentence summary (safe to log).
``hint``
    the remediation an operator should try next (never guessed at -- only set
    where the fix is known, e.g. "downgrade the DWG to R2018").
``details``
    machine readable context (file path, DWG sentinel, HTTP status, attempt
    count, ...).  Serialised into ``run_manifest.json`` on failure.

``retryable`` tells batch wrappers whether re-queueing makes sense, and
``exit_code`` gives the CLI a stable numeric contract for CI.
"""

from __future__ import annotations

from typing import Any

# Stable CLI exit codes.  Keep in sync with README.md.
EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_UNSUPPORTED_VERSION = 3
EXIT_PARSE = 4
EXIT_AUTODESK = 5
EXIT_DEEPSEEK = 6


class Cad2AiError(Exception):
    """Base class for every expected failure raised by this package."""

    exit_code: int = EXIT_UNEXPECTED
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation used in artifacts and log records."""
        out: dict[str, Any] = {
            "error": type(self).__name__,
            "message": self.message,
            "hint": self.hint,
            "retryable": self.retryable,
            "exit_code": self.exit_code,
            "details": self.details,
        }
        # Promote the fields a queue/worker needs to decide what to do next.
        for key in ("status_code", "retry_after", "attempts", "backend"):
            value = getattr(self, key, None)
            if value is not None:
                out[key] = value
        return out

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        base = self.message
        return f"{base} (hint: {self.hint})" if self.hint else base


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigError(Cad2AiError):
    """Environment/`.env` configuration is missing or invalid."""

    exit_code = EXIT_CONFIG


class MissingEnvironmentVariableError(ConfigError):
    """A required environment variable is not set."""

    def __init__(self, name: str, *, hint: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            f"required environment variable {name!r} is not set",
            hint=hint or f"set {name} in the process environment or in ./.env",
            details={"variable": name, **(details or {})},
        )
        self.name = name


# ---------------------------------------------------------------------------
# Phase 1 -- local parsing (ezdxf + odafc)
# ---------------------------------------------------------------------------


class ParseError(Cad2AiError):
    """Base class for Phase 1 (DWG/DXF reading) failures."""

    exit_code = EXIT_PARSE


class InputFileError(ParseError):
    """The input path is missing, unreadable, empty or too large."""

    def __init__(self, message: str, *, path: Any = None, **kw: Any) -> None:
        details = kw.pop("details", {})
        details.setdefault("path", str(path) if path is not None else None)
        super().__init__(message, details=details, **kw)


class NotACadFileError(ParseError):
    """The file is not a DWG/DXF we can handle (wrong magic bytes)."""


class UnsupportedDwgVersionError(ParseError):
    """DWG version cannot be handled by the installed parser stack.

    Raised *before* invoking the ODA File Converter for versions we know are
    out of range, and *after* it when the converter rejects the file, so the
    caller always gets the same typed error regardless of which layer noticed.
    """

    exit_code = EXIT_UNSUPPORTED_VERSION

    def __init__(
        self,
        message: str,
        *,
        sentinel: str | None = None,
        release: str | None = None,
        supported: tuple[str, ...] = (),
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "dwg_sentinel": sentinel,
            "dwg_release": release,
            "supported_versions": list(supported),
        }
        payload.update(details or {})
        super().__init__(message, hint=hint, details=payload)
        self.sentinel = sentinel
        self.release = release


class DwgConverterError(ParseError):
    """The ODA File Converter (``odafc``) failed or is unavailable."""


class DwgConverterNotInstalledError(DwgConverterError):
    """`ODAFileConverter` could not be located."""

    def __init__(self, message: str = "ODA File Converter is not installed", **kw: Any) -> None:
        super().__init__(
            message,
            hint=(
                "install the ODA File Converter (https://www.opendesign.com/guestfiles/oda_file_converter), "
                "set ODA_EXECUTABLE in .env, or re-run with --fallback aps"
            ),
            **kw,
        )


class CorruptCadFileError(ParseError):
    """The file parsed but the structure is broken beyond recovery."""


class DwgSecurityError(ParseError):
    """The requested operation was refused by a safety guard (path, proxy, size)."""


# ---------------------------------------------------------------------------
# Phase 1 fallback -- Autodesk Platform Services
# ---------------------------------------------------------------------------


class AutodeskError(Cad2AiError):
    """Base class for Autodesk Platform Services (APS) failures."""

    exit_code = EXIT_AUTODESK

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
        **kw: Any,
    ) -> None:
        details = kw.pop("details", {})
        if status_code is not None:
            details.setdefault("http_status", status_code)
        if body is not None:
            details.setdefault("response_body", _truncate(body))
        super().__init__(message, details=details, **kw)
        self.status_code = status_code


class AutodeskAuthError(AutodeskError):
    """2-legged token request rejected (bad/expired credentials or scopes)."""


class AutodeskUploadError(AutodeskError):
    """Object Storage Service upload failed."""

    retryable = True


class AutodeskTranslationError(AutodeskError):
    """Model Derivative job failed for a permanent reason."""


class AutodeskTranslationTimeoutError(AutodeskTranslationError):
    """Translation did not finish inside the configured timeout."""

    retryable = True


class AutodeskRateLimitError(AutodeskError):
    """APS answered 429; honour ``retry_after`` before repeating the request."""

    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class AutodeskNotFound(AutodeskError):
    """Bucket/object/derivative URN does not exist (or was garbage collected)."""


# ---------------------------------------------------------------------------
# Phase 3 -- DeepSeek
# ---------------------------------------------------------------------------


class DeepSeekError(Cad2AiError):
    """Base class for DeepSeek API failures."""

    exit_code = EXIT_DEEPSEEK

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        attempts: int | None = None,
        **kw: Any,
    ) -> None:
        details = kw.pop("details", {})
        if status_code is not None:
            details.setdefault("http_status", status_code)
        if attempts is not None:
            details.setdefault("attempts", attempts)
        super().__init__(message, details=details, **kw)
        self.status_code = status_code
        self.attempts = attempts


class DeepSeekAuthError(DeepSeekError):
    """401 -- key missing/revoked (never retry)."""

    def __init__(self, message: str = "DeepSeek rejected the API key", **kw: Any) -> None:
        super().__init__(
            message,
            hint="check DEEPSEEK_API_KEY (https://platform.deepseek.com/api_keys); the key must not be quoted or padded",
            **kw,
        )


class DeepSeekInsufficientBalanceError(DeepSeekError):
    """402 -- account out of credit (never retry; it would burn quota)."""

    def __init__(self, message: str = "DeepSeek account has insufficient balance", **kw: Any) -> None:
        super().__init__(
            message,
            hint="top up the account at https://platform.deepseek.com/top_up, then re-run",
            **kw,
        )


class DeepSeekRateLimitError(DeepSeekError):
    """429 -- concurrency/QPS limit reached after exhausting the backoff policy."""

    retryable = True

    def __init__(
        self,
        message: str = "DeepSeek rate limit reached",
        *,
        retry_after: float | None = None,
        **kw: Any,
    ) -> None:
        details = kw.pop("details", {})
        details.setdefault("retry_after_seconds", retry_after)
        super().__init__(
            message,
            hint=(
                "lower the request rate (DEEPSEEK_MAX_ATTEMPTS/DEEPSEEK_MIN_INTERVAL_MS) or raise "
                "the account concurrency; DeepSeek limits concurrency per model"
            ),
            details=details,
            **kw,
        )
        self.retry_after = retry_after


class DeepSeekServerError(DeepSeekError):
    """5xx -- upstream problem; retryable with backoff."""

    retryable = True


class DeepSeekTransportError(DeepSeekError):
    """Network/timeout failure while talking to DeepSeek; retryable."""

    retryable = True


class DeepSeekBadRequestError(DeepSeekError):
    """400/422 -- malformed request or unsupported parameter for this model."""


class DeepSeekResponseError(DeepSeekError):
    """The response was structurally unusable (no choices, truncated, ...)."""


class DeepSeekEmptyResponseError(DeepSeekResponseError):
    """Empty ``content`` -- a known transient in DeepSeek JSON mode."""

    retryable = True


class DeepSeekTruncatedResponseError(DeepSeekResponseError):
    """``finish_reason == 'length'`` -- raise DEEPSEEK_MAX_TOKENS or shrink the payload."""


class DeepSeekJsonError(DeepSeekResponseError):
    """The model did not return parseable JSON even after repair attempts."""


def _truncate(body: Any, limit: int = 2000) -> Any:
    """Keep error bodies useful but bounded (API errors can embed big payloads)."""
    if isinstance(body, (dict, list)):
        text = str(body)
    else:
        text = str(body)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"
