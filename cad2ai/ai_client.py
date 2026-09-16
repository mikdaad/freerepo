"""Phase 3 -- DeepSeek API client (OpenAI-compatible).

DeepSeek exposes the OpenAI Chat Completions contract, so this module uses the
official ``openai`` SDK pointed at ``https://api.deepseek.com`` and
authenticates with ``DEEPSEEK_API_KEY``.  Everything else here is what
production use actually needs and the SDK does not give you for free:

* **Rate-limit handling.**  ``openai.RateLimitError`` (HTTP 429) is retried with
  capped exponential backoff *plus* jitter, honouring ``Retry-After`` when the
  API sends it.  Concurrency is bounded by a semaphore and spaced by a minimum
  inter-request interval, because DeepSeek throttles on concurrency per key --
  naive parallelism makes throughput worse, not better.
* **Deterministic failure classes.**  401 (bad key), 402 (no balance), 400/422
  (bad request) and 5xx (upstream) map to distinct
  :mod:`cad2ai.errors` types with different ``retryable`` flags, so a batch
  runner knows whether to re-queue or to page a human.
* **JSON contract.**  ``response_format={"type": "json_object"}`` plus a repair
  path (strip markdown fences, trim to the outermost braces, retry once on the
  documented "empty content" JSON-mode hiccup) so downstream code gets a dict.
* **Budget awareness.**  prompt/completion token usage and cached-token counts
  are recorded per call and aggregated, and the caller can ask for the request to
  be *rejected before sending* if the payload exceeds a token budget.

No request is logged with its body: payloads can contain project-sensitive
geometry, so logs carry sizes/hashes only.
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from cad2ai.errors import (
    ConfigError,
    DeepSeekAuthError,
    DeepSeekBadRequestError,
    DeepSeekEmptyResponseError,
    DeepSeekError,
    DeepSeekInsufficientBalanceError,
    DeepSeekJsonError,
    DeepSeekRateLimitError,
    DeepSeekServerError,
    DeepSeekTransportError,
    DeepSeekTruncatedResponseError,
)
from cad2ai.payload import estimate_tokens

logger = logging.getLogger("cad2ai.ai")

__all__ = [
    "ChatResult",
    "DeepSeekClient",
    "DeepSeekConfig",
    "RateLimitPolicy",
    "UsageSnapshot",
]

#: Text patterns in a 400 body that are worth specialising.
_TOKEN_LIMIT_HINTS = ("context length", "maximum context", "too long", "reduce the length", "input tokens")
_MODEL_HINTS = ("model", "does not exist", "not a valid model")


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeepSeekConfig:
    """Everything the transport needs, resolved from :class:`~cad2ai.config.Settings`."""

    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    max_tokens: int = 8000
    temperature: float = 0.0
    top_p: float | None = None
    timeout: float = 180.0
    json_mode: bool = True
    thinking: str = "disabled"
    reasoning_effort: str | None = None
    seed: int | None = None
    user: str | None = None
    max_prompt_tokens: int = 900_000
    empty_content_retries: int = 2
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Any, **overrides: Any) -> "DeepSeekConfig":
        config = cls(
            api_key=settings.require_deepseek_key(),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            max_tokens=settings.deepseek_max_tokens,
            temperature=settings.deepseek_temperature,
            timeout=settings.deepseek_timeout,
            json_mode=settings.deepseek_json_mode,
            thinking=settings.deepseek_thinking,
            reasoning_effort=settings.deepseek_reasoning_effort,
            max_prompt_tokens=max(settings.payload_max_tokens * 4, 128_000),
            empty_content_retries=settings.deepseek_empty_content_retries,
            extra_headers=dict(getattr(settings, "deepseek_extra_headers", {}) or {}),
        )
        if overrides:
            unknown = set(overrides) - set(cls.__dataclass_fields__)
            if unknown:
                raise ConfigError(f"unknown DeepSeek config option(s): {', '.join(sorted(unknown))}")
            config = cls(**{**config.__dict__, **overrides})
        return config

    @property
    def thinking_enabled(self) -> bool:
        return str(self.thinking).lower() == "enabled"

    def request_params(self) -> dict[str, Any]:
        """Model/decoding parameters for one completion."""
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if self.seed is not None:
            params["seed"] = self.seed
        if self.user:
            params["user"] = self.user
        if self.json_mode:
            # DeepSeek requires the word "json" in the prompt (our system prompt
            # states the schema explicitly) for reliable JSON output.
            params["response_format"] = {"type": "json_object"}
        body: dict[str, Any] = {}
        if self.thinking_enabled:
            body["thinking"] = {"type": "enabled"}
            if self.reasoning_effort:
                params["reasoning_effort"] = self.reasoning_effort
            # temperature/presence/frequency penalties are ignored by the API in
            # thinking mode: drop them so billing/reasoning logs stay honest.
            params.pop("temperature", None)
        if body:
            params["extra_body"] = body
        return params


@dataclass(frozen=True)
class RateLimitPolicy:
    """Backoff policy for retried calls (429/5xx/transport)."""

    max_attempts: int = 5
    min_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.25
    #: never exceed this even if Retry-After asks for more (keeps CI sane)
    max_retry_after: float = 120.0
    #: minimum gap between consecutive requests on this client (seconds)
    min_interval: float = 0.0

    @classmethod
    def from_settings(cls, settings: Any) -> "RateLimitPolicy":
        return cls(
            max_attempts=max(1, int(settings.deepseek_max_attempts)),
            min_delay=float(settings.deepseek_retry_min_delay),
            max_delay=float(settings.deepseek_retry_max_delay),
            min_interval=max(0.0, float(settings.deepseek_min_interval_ms or 0) / 1000.0),
        )

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        """Seconds to wait before attempt ``attempt`` (1-based)."""
        if retry_after is not None and retry_after > 0:
            base = min(float(retry_after), self.max_retry_after)
        else:
            base = min(self.max_delay, self.min_delay * (self.multiplier ** max(0, attempt - 1)))
        spread = base * self.jitter
        return max(0.0, base + (random.uniform(-spread, spread) if spread else 0.0))


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class UsageSnapshot:
    """Token accounting for one call (or aggregated across calls)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def merge(self, other: "UsageSnapshot") -> "UsageSnapshot":
        return UsageSnapshot(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )

    @property
    def cache_hit_ratio(self) -> float | None:
        if not self.prompt_tokens:
            return None
        return round(self.cached_tokens / self.prompt_tokens, 3)

    def as_dict(self) -> dict[str, Any]:
        out = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.cached_tokens:
            out["cached_prompt_tokens"] = self.cached_tokens
            out["cache_hit_ratio"] = self.cache_hit_ratio
        if self.reasoning_tokens:
            out["reasoning_tokens"] = self.reasoning_tokens
        return out


@dataclass
class ChatResult:
    """A successful completion: text, parsed JSON, and provenance."""

    content: str
    data: Any = None
    usage: UsageSnapshot = field(default_factory=UsageSnapshot)
    model: str = ""
    id: str | None = None
    created: int | None = None
    finish_reason: str | None = None
    reasoning_content: str = ""
    attempts: int = 1
    latency_seconds: float = 0.0
    parsed: bool = False
    repair_notes: list[str] = field(default_factory=list)
    batch: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.content) and (self.data is not None or not self.repair_notes)

    def json_or_raise(self) -> Any:
        if self.data is None:
            raise DeepSeekJsonError(
                "the model reply did not contain usable JSON",
                details={"content_prefix": self.content[:400]},
            )
        return self.data

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "id": self.id,
            "created": self.created,
            "finish_reason": self.finish_reason,
            "attempts": self.attempts,
            "latency_seconds": round(self.latency_seconds, 3),
            "usage": self.usage.as_dict(),
            "parsed": self.parsed,
            "repair_notes": self.repair_notes,
            "reasoning_chars": len(self.reasoning_content),
            "batch": self.batch,
        }


@dataclass
class RequestSpec:
    """One request for :meth:`DeepSeekClient.complete_many`."""

    messages: Sequence[Mapping[str, str]]
    label: str = ""
    overrides: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSON repair
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json_object(text: str) -> tuple[Any | None, list[str]]:
    """Parse JSON out of a model reply, repairing common formatting damage.

    Order of attempts: literal parse -> strip markdown fences -> trim to the
    outermost ``{...}``/``[...]`` -> drop trailing commas -> return ``None`` with
    notes describing what was tried (the caller decides whether to retry).
    """
    notes: list[str] = []
    if not text or not text.strip():
        return None, ["empty content"]
    candidates: list[tuple[str, str]] = [("raw", text.strip())]
    stripped = _FENCE.sub("", text.strip())
    if stripped != text.strip():
        notes.append("stripped markdown fences")
        candidates.append(("defenced", stripped))
    for label, value in list(candidates):
        span = _outermost_span(value, "{", "}")
        if span is not None:
            trimmed = value[span[0] : span[1] + 1]
            if trimmed != value:
                notes.append(f"trimmed to outermost braces ({label})")
            candidates.append((f"span:{label}", trimmed))
            # Concatenated or trailing-prose replies: the first *balanced* object.
            first = _first_balanced(value)
            if first is not None and first != trimmed:
                notes.append("took the first complete JSON object")
                candidates.append((f"first:{label}", first))
            for source_label, source in list(candidates):
                if not source_label.startswith(("span:", "first:", "defenced", "raw")):
                    continue
                no_trailing = re.sub(r",(\s*[}\]])", r"\1", source)
                if no_trailing != source:
                    if "removed trailing commas" not in notes:
                        notes.append("removed trailing commas")
                    candidates.append(("untrimmed", no_trailing))
            break
    for label, value in candidates:
        try:
            return json.loads(value), notes if label != "raw" else []
        except json.JSONDecodeError:
            continue
    return None, notes or ["no JSON object found"]


def _outermost_span(text: str, opener: str, closer: str) -> tuple[int, int] | None:
    start = text.find(opener)
    end = text.rfind(closer)
    return (start, end) if start != -1 and end > start else None


def _first_balanced(text: str, opener: str = "{", closer: str = "}") -> str | None:
    """Return the first balanced ``{...}`` block, honouring strings and escapes.

    Models occasionally answer with two objects back to back, or with an object
    followed by prose; ``rfind`` then grabs too much.
    """
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class DeepSeekClient:
    """Small, explicit wrapper over ``openai.OpenAI`` for DeepSeek chat calls."""

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        policy: RateLimitPolicy | None = None,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_usage: Callable[[UsageSnapshot], None] | None = None,
    ) -> None:
        self.config = config
        self.policy = policy or RateLimitPolicy()
        self._sleep = sleep
        self._on_usage = on_usage
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._concurrency = threading.Semaphore(4)
        self._usage_total = UsageSnapshot()
        self._client = client if client is not None else self._build_client()

    # ------------------------------------------------------------------ setup
    def _build_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise DeepSeekError(
                "the 'openai' package is required for Phase 3 (pip install openai)",
                hint="DeepSeek speaks the OpenAI API; the SDK provides the transport",
            ) from exc
        if not self.config.api_key:
            raise ConfigError("DEEPSEEK_API_KEY is empty", hint="set it in the environment or in ./.env")
        kwargs: dict[str, Any] = {
            "api_key": self.config.api_key,
            "base_url": self.config.base_url,
            "timeout": self.config.timeout,
            # We own the backoff policy (Retry-After, concurrency pacing), so the
            # SDK's implicit retries must be off to avoid multiplying attempts.
            "max_retries": 0,
        }
        if self.config.extra_headers:
            kwargs["default_headers"] = dict(self.config.extra_headers)
        return OpenAI(**kwargs)

    @property
    def total_usage(self) -> UsageSnapshot:
        return self._usage_total

    def estimate_prompt_tokens(self, messages: Iterable[Mapping[str, Any]]) -> int:
        return sum(estimate_tokens(str(message.get("content") or "")) for message in messages)

    # -------------------------------------------------------------- completion
    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        json_mode: bool | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
        thinking: str | None = None,
        label: str = "",
        extra: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        """Run one chat completion with retries, pacing and JSON parsing."""
        params = self._params(json_mode=json_mode, max_tokens=max_tokens, temperature=temperature, model=model, thinking=thinking, extra=extra)
        prompt_tokens = self.estimate_prompt_tokens(messages)
        if prompt_tokens > self.config.max_prompt_tokens:
            raise DeepSeekBadRequestError(
                f"payload too large before sending: ~{prompt_tokens} tokens exceeds the {self.config.max_prompt_tokens} token guard",
                hint="lower CAD2AI_MAX_PAYLOAD_TOKENS or raise the per-section caps instead of truncating JSON text",
                details={"estimated_prompt_tokens": prompt_tokens, "label": label},
            )
        attempts_allowed = max(1, self.policy.max_attempts)
        empty_retries_left = max(0, self.config.empty_content_retries) if params.get("response_format") else 0
        start = time.monotonic()
        last_error: DeepSeekError | None = None
        attempts_used = 0

        for attempt in range(1, attempts_allowed + 1):
            attempts_used = attempt
            self._pace()
            try:
                raw = self._client.chat.completions.create(messages=list(messages), **params)
            except Exception as exc:  # noqa: BLE001 - SDK exceptions are mapped below
                error, retryable = self._classify(exc, attempt=attempt, model=str(params.get("model")))
                if not retryable:
                    raise error from exc
                if attempt >= attempts_allowed:
                    logger.error("DeepSeek call failed after %s attempt(s): %s", attempt, error.message)
                    raise error from exc
                delay = error.retry_after if isinstance(error, DeepSeekRateLimitError) else None
                wait = self.policy.delay_for(attempt, retry_after=delay)
                logger.warning(
                    "DeepSeek %s (attempt %s/%s, label=%s): %s -- backing off %.1fs",
                    type(error).__name__,
                    attempt,
                    attempts_allowed,
                    label or "-",
                    error.message,
                    wait,
                )
                last_error = error
                self._sleep(wait)
                continue

            result = self._parse_response(
                raw,
                attempts=attempt,
                latency=time.monotonic() - start,
                json_mode=bool(params.get("response_format")),
                model=str(params.get("model")),
            )
            if result is None:
                # Empty content in JSON mode: documented transient DeepSeek
                # behaviour -- retry a couple of times without burning the whole
                # backoff budget.
                if empty_retries_left > 0:
                    empty_retries_left -= 1
                    wait = self.policy.delay_for(attempt)
                    logger.warning("DeepSeek returned empty JSON content; retrying in %.1fs (label=%s)", wait, label or "-")
                    self._sleep(wait)
                    continue
                raise DeepSeekEmptyResponseError(
                    "DeepSeek returned an empty completion",
                    hint=(
                        "JSON mode can occasionally return empty content; retry, or simplify the output "
                        "schema / raise max_tokens"
                    ),
                    details={"attempts": attempt, "label": label},
                )
            result.attempts = attempt
            with self._lock:
                self._usage_total = self._usage_total.merge(result.usage)
            if self._on_usage is not None:
                try:
                    self._on_usage(result.usage)
                except Exception:  # pragma: no cover - callback must not break the run
                    logger.debug("usage callback failed", exc_info=True)
            return result

        if last_error is not None:
            raise last_error
        raise DeepSeekTransportError(
            "DeepSeek call did not produce a response",
            details={"attempts": attempts_used, "label": label},
        )

    def complete_json(self, messages: Sequence[Mapping[str, str]], **kwargs: Any) -> tuple[Any, ChatResult]:
        """Convenience wrapper returning ``(parsed_json, result)``."""
        kwargs.setdefault("json_mode", True)
        result = self.complete(messages, **kwargs)
        return result.json_or_raise(), result

    def complete_many(
        self,
        requests: Sequence[RequestSpec],
        *,
        concurrency: int = 2,
        fail_fast: bool = False,
    ) -> list[tuple[str, ChatResult | DeepSeekError]]:
        """Run several completions with bounded concurrency.

        DeepSeek throttles per key on concurrency, so the default is deliberately
        low (2) and :class:`RateLimitPolicy` adds jitter.  Errors are returned
        alongside successes unless ``fail_fast`` is set.
        """
        if not requests:
            return []
        results: list[tuple[str, ChatResult | DeepSeekError] | None] = [None] * len(requests)
        workers = max(1, min(concurrency, len(requests)))
        semaphore = threading.Semaphore(workers)

        def run(index: int, spec: RequestSpec) -> None:
            with semaphore:
                try:
                    results[index] = (
                        spec.label or f"request-{index + 1}",
                        self.complete(spec.messages, label=spec.label, **dict(spec.overrides)),
                    )
                except DeepSeekError as exc:
                    if fail_fast:
                        raise
                    results[index] = (spec.label or f"request-{index + 1}", exc)
                except Exception as exc:  # noqa: BLE001 - unexpected: normalise
                    error, _ = self._classify(exc, attempt=1, model=self.config.model)
                    if fail_fast:
                        raise error from exc
                    results[index] = (spec.label or f"request-{index + 1}", error)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="deepseek") as pool:
            futures = [pool.submit(run, index, spec) for index, spec in enumerate(requests)]
            for future in futures:
                future.result()
        return [item for item in results if item is not None]

    def health_check(self) -> dict[str, Any]:
        """Cheap reachability/auth probe (a 3-token ping)."""
        params = self._params(json_mode=False, max_tokens=8, temperature=0.0)
        params.pop("response_format", None)
        params.pop("extra_body", None)
        params.pop("reasoning_effort", None)
        params["temperature"] = 0.0
        try:
            raw = self._client.chat.completions.create(
                messages=[{"role": "user", "content": "reply with the single word: ok"}],
                **params,
            )
        except Exception as exc:  # noqa: BLE001
            error, _ = self._classify(exc, attempt=1, model=self.config.model)
            return {"reachable": False, "error": error.to_dict()}
        content = ""
        try:
            content = (raw.choices[0].message.content or "").strip()
        except Exception:  # pragma: no cover - malformed SDK object
            pass
        return {
            "reachable": True,
            "model": getattr(raw, "model", self.config.model),
            "reply_prefix": content[:40],
            "base_url": self.config.base_url,
        }

    # ------------------------------------------------------------------ helpers
    def _params(
        self,
        *,
        json_mode: bool | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
        thinking: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(self.config.request_params())
        if model:
            params["model"] = model
        if max_tokens is not None:
            params["max_tokens"] = int(max_tokens)
        if temperature is not None and not (thinking or self.config.thinking).lower().startswith("en"):
            params["temperature"] = float(temperature)
        if json_mode is not None:
            if json_mode:
                params["response_format"] = {"type": "json_object"}
            else:
                params.pop("response_format", None)
        if thinking is not None:
            enabled = str(thinking).lower() == "enabled"
            if enabled:
                body = dict(params.get("extra_body") or {})
                body["thinking"] = {"type": "enabled"}
                params["extra_body"] = body
                params.pop("temperature", None)
            else:
                params.pop("extra_body", None)
        if extra:
            params.update(dict(extra))
        return params

    def _pace(self) -> None:
        """Enforce the minimum inter-request interval (thread-safe)."""
        interval = self.policy.min_interval
        if interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._last_request_at + interval - now
            if wait > 0:
                self._sleep(wait)
            self._last_request_at = time.monotonic()

    def _parse_response(
        self,
        raw: Any,
        *,
        attempts: int,
        latency: float,
        json_mode: bool,
        model: str,
    ) -> ChatResult | None:
        """Convert an SDK response into a :class:`ChatResult` (``None`` = empty)."""
        usage = UsageSnapshot()
        usage_obj = getattr(raw, "usage", None)
        if usage_obj is not None:
            usage = UsageSnapshot(
                prompt_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage_obj, "total_tokens", 0) or 0),
            )
            details = getattr(usage_obj, "prompt_tokens_details", None)
            usage.cached_tokens = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
            completion_details = getattr(usage_obj, "completion_tokens_details", None)
            usage.reasoning_tokens = (
                int(getattr(completion_details, "reasoning_tokens", 0) or 0) if completion_details is not None else 0
            )
        choices = getattr(raw, "choices", None) or []
        if not choices:
            return ChatResult(
                content="",
                usage=usage,
                model=str(getattr(raw, "model", model) or model),
                id=getattr(raw, "id", None),
                attempts=attempts,
                latency_seconds=latency,
                repair_notes=["no choices in response"],
            )
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = (getattr(message, "content", None) or "").strip()
        reasoning = str(getattr(message, "reasoning_content", None) or "")
        finish_reason = getattr(choice, "finish_reason", None)
        result = ChatResult(
            content=content,
            usage=usage,
            model=str(getattr(raw, "model", model) or model),
            id=getattr(raw, "id", None),
            created=getattr(raw, "created", None),
            finish_reason=finish_reason,
            reasoning_content=reasoning,
            attempts=attempts,
            latency_seconds=latency,
        )
        if not content:
            if finish_reason == "length":
                raise DeepSeekTruncatedResponseError(
                    "DeepSeek hit max_tokens before producing any content",
                    hint="raise DEEPSEEK_MAX_TOKENS or shrink the payload/expected output",
                    details={"max_tokens": self.config.max_tokens},
                )
            return None
        if finish_reason == "length":
            raise DeepSeekTruncatedResponseError(
                "DeepSeek response was truncated by max_tokens (finish_reason=length)",
                hint=(
                    "raise DEEPSEEK_MAX_TOKENS, or reduce the number of findings requested; "
                    "truncated JSON is not repaired into a partial object"
                ),
                details={"max_tokens": self.config.max_tokens, "content_chars": len(content)},
            )
        if json_mode:
            data, notes = extract_json_object(content)
            if data is None:
                raise DeepSeekJsonError(
                    "could not parse JSON from the model reply: " + ", ".join(notes),
                    hint=(
                        "the reply did not follow the requested JSON schema; retry once, or lower "
                        "CAD2AI_MAX_PAYLOAD_TOKENS so the model has room to answer"
                    ),
                    details={"attempts_hint": attempts, "content_prefix": content[:600]},
                )
            result.data = data
            result.parsed = True
            result.repair_notes = notes
        return result

    def _classify(self, exc: Exception, *, attempt: int, model: str) -> tuple[DeepSeekError, bool]:
        """Map SDK/transport exceptions to typed errors and a retry decision."""
        try:
            import openai
        except ImportError:  # pragma: no cover - openai is required to be here anyway
            return DeepSeekTransportError(f"DeepSeek call failed: {type(exc).__name__}: {exc}", attempts=attempt), True

        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        text = str(exc)
        lowered = text.lower()
        retry_after = _retry_after_from(exc)
        details = {"exception": type(exc).__name__, "message": text[:500], "attempt": attempt}

        if isinstance(exc, openai.RateLimitError) or status == 429:
            return (
                DeepSeekRateLimitError(
                    "DeepSeek rate limit reached (HTTP 429)",
                    retry_after=retry_after,
                    status_code=429,
                    attempts=attempt,
                    details=details,
                ),
                True,
            )
        if isinstance(exc, openai.AuthenticationError) or status == 401:
            return (
                DeepSeekAuthError(
                    f"DeepSeek rejected the API key (HTTP 401): {text[:200]}",
                    status_code=401,
                    details=details,
                ),
                False,
            )
        if status == 402:
            return (
                DeepSeekInsufficientBalanceError(
                    "DeepSeek account has insufficient balance (HTTP 402)",
                    status_code=402,
                    details=details,
                ),
                False,
            )
        if isinstance(exc, openai.APITimeoutError) or isinstance(exc, openai.APIConnectionError):
            return (
                DeepSeekTransportError(
                    f"could not reach DeepSeek ({type(exc).__name__}): {text[:200]}",
                    hint="check DNS/egress/proxy configuration; retries are already in progress",
                    attempts=attempt,
                    details=details,
                ),
                True,
            )
        if status in (500, 502, 503, 504) or isinstance(exc, openai.InternalServerError):
            return (
                DeepSeekServerError(
                    f"DeepSeek server error (HTTP {status or '?'}): {text[:200]}",
                    status_code=status,
                    attempts=attempt,
                    details=details,
                ),
                True,
            )
        if status in (400, 404, 422) or isinstance(exc, (openai.BadRequestError, openai.NotFoundError, openai.UnprocessableEntityError)):
            hint = None
            if any(hint_text in lowered for hint_text in _TOKEN_LIMIT_HINTS):
                hint = "the prompt exceeded the model context: lower CAD2AI_MAX_PAYLOAD_TOKENS"
            elif any(hint_text in lowered for hint_text in _MODEL_HINTS):
                hint = f"set DEEPSEEK_MODEL to a model your account can access (tried {model!r})"
            elif "json" in lowered:
                hint = "JSON mode needs the word 'json' plus a schema example in the prompt (see cad2ai.prompts)"
            return (
                DeepSeekBadRequestError(
                    f"DeepSeek rejected the request (HTTP {status or '400'}): {text[:300]}",
                    hint=hint,
                    status_code=status,
                    attempts=attempt,
                    details=details,
                ),
                False,
            )
        return (
            DeepSeekError(
                f"DeepSeek call failed: {type(exc).__name__}: {text[:300]}",
                hint="unexpected API condition; see details",
                status_code=status,
                attempts=attempt,
                details=details,
            ),
            bool(status and status >= 500),
        )


def _retry_after_from(exc: Exception) -> float | None:
    """Extract ``Retry-After`` from an SDK exception's response, if present."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:  # pragma: no cover - exotic header containers
        return None
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        try:  # HTTP date form
            from email.utils import parsedate_to_datetime

            when = parsedate_to_datetime(str(raw))
            value = max(0.0, when.timestamp() - time.time())
        except Exception:
            return None
    return max(0.0, value)
