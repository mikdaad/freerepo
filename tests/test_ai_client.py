"""Phase 3: DeepSeek client -- retries, rate limits, JSON handling, usage."""

from __future__ import annotations

import json
import types

import openai
import pytest

from cad2ai.ai_client import (
    ChatResult,
    DeepSeekClient,
    DeepSeekConfig,
    RateLimitPolicy,
    RequestSpec,
    UsageSnapshot,
    extract_json_object,
)
from cad2ai.errors import (
    DeepSeekAuthError,
    DeepSeekBadRequestError,
    DeepSeekEmptyResponseError,
    DeepSeekError,
    DeepSeekInsufficientBalanceError,
    DeepSeekJsonError,
    DeepSeekRateLimitError,
    DeepSeekTransportError,
    DeepSeekTruncatedResponseError,
)
from conftest import FakeCompletion, FakeLLM

MESSAGES = [
    {"role": "system", "content": "You are a CAD analyst. Reply in json."},
    {"role": "user", "content": json.dumps({"layers": [{"name": "A-WALL", "entities": 12}]})},
]


class _Request:
    method = "POST"
    url = "https://api.deepseek.com/chat/completions"
    headers: dict[str, str] = {}


def _response(status_code: int, headers: dict[str, str] | None = None, text: str = ""):
    response = types.SimpleNamespace()
    response.status_code = status_code
    response.headers = headers or {}
    response.text = text
    response.request = _Request()
    return response


def api_error(cls, message: str, status: int, headers: dict[str, str] | None = None):
    return cls(message, response=_response(status, headers), body=None)


def connection_error(message: str = "connection reset"):
    return openai.APIConnectionError(message=message, request=_Request())


def timeout_error():
    return openai.APITimeoutError(_Request())


@pytest.fixture
def config() -> DeepSeekConfig:
    return DeepSeekConfig(api_key="sk-test-0000", model="deepseek-flash", max_tokens=4000, json_mode=True)


def make_client(config, *, script=None, default=None, policy=None, sleeps=None):
    """Client + fake transport + the list its sleeps are recorded in."""
    import dataclasses

    if isinstance(config, DeepSeekConfig):
        config = dataclasses.replace(config)  # unwrap so tests can tweak fields
    llm = FakeLLM(script or [], default=default)
    recorded = sleeps if sleeps is not None else []
    client = DeepSeekClient(
        config,
        policy=policy or RateLimitPolicy(max_attempts=3, min_delay=0.5, max_delay=2.0, jitter=0.0),
        client=llm,
        sleep=recorded.append,
    )
    return client, llm, recorded


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_config_from_settings(settings):
    config = DeepSeekConfig.from_settings(settings)
    assert config.api_key == "sk-test-0000"
    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-flash"
    assert config.json_mode is True
    assert config.max_prompt_tokens >= settings.payload_max_tokens * 4
    with pytest.raises(Exception, match="unknown DeepSeek config option"):
        DeepSeekConfig.from_settings(settings, tempreture=1)


def test_request_params_json_mode_and_thinking():
    plain = DeepSeekConfig(api_key="k", thinking="disabled")
    params = plain.request_params()
    assert params["response_format"] == {"type": "json_object"}
    assert params["temperature"] == 0.0
    assert "extra_body" not in params

    thinking = DeepSeekConfig(api_key="k", thinking="enabled", reasoning_effort="high", temperature=0.7)
    params = thinking.request_params()
    assert params["extra_body"] == {"thinking": {"type": "enabled"}}
    assert params["reasoning_effort"] == "high"
    assert "temperature" not in params, "thinking mode ignores sampling temperature"


def test_optional_params_are_omitted_unless_set():
    params = DeepSeekConfig(api_key="k").request_params()
    assert "top_p" not in params and "seed" not in params and "user" not in params
    params = DeepSeekConfig(api_key="k", top_p=0.95, seed=7, user="acct-42").request_params()
    assert params["top_p"] == 0.95 and params["seed"] == 7 and params["user"] == "acct-42"


def test_sdk_client_is_built_without_implicit_retries(monkeypatch):
    captured = {}

    class Recorder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", Recorder)
    client = DeepSeekClient(
        DeepSeekConfig(api_key="sk-abc", base_url="https://proxy.example/v1", timeout=42.0, extra_headers={"X-Tag": "job"})
    )
    assert captured == {
        "api_key": "sk-abc",
        "base_url": "https://proxy.example/v1",
        "timeout": 42.0,
        "max_retries": 0,
        "default_headers": {"X-Tag": "job"},
    }
    assert isinstance(client._client, Recorder)


def test_missing_key_is_a_config_error():
    from cad2ai.errors import ConfigError

    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY is empty"):
        DeepSeekClient(DeepSeekConfig(api_key=""))


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_complete_returns_parsed_json_and_usage(config):
    payload = {"summary": "ok", "findings": []}
    client, llm, _ = make_client(
        config,
        script=[{
            "kind": "json",
            "data": payload,
        }],
    )
    data, result = client.complete_json(MESSAGES)
    assert data == payload
    assert result.parsed is True and result.ok is True
    assert result.usage.prompt_tokens == 1000 and result.usage.total_tokens == 1200
    assert result.attempts == 1
    assert llm.calls[0]["messages"] == MESSAGES
    assert llm.calls[0]["model"] == "deepseek-flash"
    assert llm.calls[0]["max_tokens"] == 4000
    assert client.total_usage.prompt_tokens == 1000


def test_usage_accumulates_and_callback_fires(config):
    seen: list[UsageSnapshot] = []
    llm = FakeLLM([], default=lambda: FakeCompletion('{"a":1}', prompt_tokens=111))
    client = DeepSeekClient(
        config,
        policy=RateLimitPolicy(max_attempts=2, jitter=0.0),
        client=llm,
        sleep=lambda seconds: None,
        on_usage=seen.append,
    )
    for _ in range(3):
        client.complete(MESSAGES)
    assert client.total_usage.prompt_tokens == 333
    assert [item.prompt_tokens for item in seen] == [111, 111, 111]


def test_result_serialisation_is_json_safe(config):
    client, _, _ = make_client(config, script=[{"kind": "json", "data": {"a": 1}}])
    result = client.complete(MESSAGES)
    blob = json.dumps(result.as_dict())
    assert "prompt_tokens" in blob
    assert result.as_dict()["usage"]["total_tokens"] == 1200


# ---------------------------------------------------------------------------
# JSON repair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        '{"a":1}',
        '```json\n{"a":1}\n```',
        '```{"a": 1}```',
        'Here is the answer:\n{"a":1,"b":[1,2,]}\nHope that helps.',
        '{"a":1}\n{"b":2}',
    ],
)
def test_extract_json_object_repairs_common_damage(content):
    data, notes = extract_json_object(content)
    assert isinstance(data, dict)
    assert data.get("a") == 1
    if content != '{"a":1}':
        assert notes, "repaired input must report what was done"


def test_extract_json_object_gives_up_gracefully():
    data, notes = extract_json_object("no json here at all")
    assert data is None
    assert notes


def test_fenced_json_is_accepted_by_complete(config):
    client, _, _ = make_client(config, script=[FakeCompletion("```json\n{\"findings\": []}\n```")])
    result = client.complete(MESSAGES)
    assert result.data == {"findings": []}
    assert result.repair_notes


def test_unparsable_reply_is_a_typed_error(config):
    client, _, _ = make_client(config, script=[FakeCompletion("I cannot answer that.")])
    with pytest.raises(DeepSeekJsonError) as excinfo:
        client.complete(MESSAGES)
    assert "did not follow the requested JSON schema" in excinfo.value.hint


# ---------------------------------------------------------------------------
# rate limits & retries
# ---------------------------------------------------------------------------


def test_rate_limit_honours_retry_after_then_succeeds(config):
    client, llm, sleeps = make_client(
        config,
        script=[
            api_error(openai.RateLimitError, "Too Many Requests", 429, {"retry-after": "7"}),
            {"kind": "json", "data": {"ok": True}},
        ],
    )
    result = client.complete(MESSAGES)
    assert result.data == {"ok": True}
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert 5.0 <= sleeps[0] <= 9.0, "Retry-After (7s) must drive the backoff, with jitter"


def test_rate_limit_retries_exhausted(config):
    client, llm, sleeps = make_client(
        config,
        script=[api_error(openai.RateLimitError, "Too Many Requests", 429, {"retry-after": "1"})] * 3,
    )
    with pytest.raises(DeepSeekRateLimitError) as excinfo:
        client.complete(MESSAGES)
    error = excinfo.value
    assert error.status_code == 429
    assert error.retryable is True
    assert error.attempts == 3
    assert len(llm.calls) == 3, "must not exceed max_attempts"
    assert len(sleeps) == 2, "no sleep after the final attempt"


def test_exponential_backoff_without_retry_after(config):
    policy = RateLimitPolicy(max_attempts=4, min_delay=1.0, max_delay=10.0, multiplier=3.0, jitter=0.0)
    client, llm, sleeps = make_client(
        config,
        script=[api_error(openai.InternalServerError, "bad gateway", 502)] * 3 + [{"kind": "json", "data": {}}],
        policy=policy,
    )
    client.complete(MESSAGES)
    assert sleeps == [1.0, 3.0, 9.0]


def test_retry_after_is_capped(config):
    policy = RateLimitPolicy(max_attempts=2, max_retry_after=15.0, jitter=0.0)
    client, _, sleeps = make_client(
        config,
        script=[api_error(openai.RateLimitError, "busy", 429, {"retry-after": "3600"}), {"kind": "json", "data": {}}],
        policy=policy,
    )
    client.complete(MESSAGES)
    assert sleeps == [15.0], "a one-hour Retry-After must be clamped for a batch job"


def test_server_errors_are_retried(config):
    client, llm, _ = make_client(
        config,
        script=[
            api_error(openai.InternalServerError, "upstream failure", 500),
            {"kind": "json", "data": {"recovered": True}},
        ],
    )
    assert client.complete(MESSAGES).data == {"recovered": True}
    assert len(llm.calls) == 2


def test_transport_errors_are_retried(config):
    client, llm, sleeps = make_client(
        config,
        script=[connection_error(), timeout_error(), {"kind": "json", "data": {}}],
    )
    assert client.complete(MESSAGES).data == {}
    assert len(sleeps) == 2


def test_transport_exhaustion_reports_transport_error(config):
    client, _, _ = make_client(config, script=[connection_error()] * 3)
    with pytest.raises(DeepSeekTransportError) as excinfo:
        client.complete(MESSAGES)
    assert "DNS" in (excinfo.value.hint or "")


def test_auth_error_is_not_retried(config):
    client, llm, sleeps = make_client(config, script=[api_error(openai.AuthenticationError, "bad key", 401)])
    with pytest.raises(DeepSeekAuthError) as excinfo:
        client.complete(MESSAGES)
    assert len(llm.calls) == 1 and sleeps == []
    assert excinfo.value.retryable is False
    assert excinfo.value.exit_code == 6


def test_insufficient_balance_is_not_retried(config):
    client, llm, _ = make_client(config, script=[api_error(openai.APIStatusError, "insufficient balance", 402)])
    with pytest.raises(DeepSeekInsufficientBalanceError):
        client.complete(MESSAGES)
    assert len(llm.calls) == 1


def test_context_length_hint(config):
    client, _, _ = make_client(
        config,
        script=[api_error(openai.BadRequestError, "This model's maximum context length is 8192 tokens", 400)],
    )
    with pytest.raises(DeepSeekBadRequestError) as excinfo:
        client.complete(MESSAGES)
    assert "CAD2AI_MAX_PAYLOAD_TOKENS" in excinfo.value.hint


def test_unknown_model_hint(config):
    client, _, _ = make_client(
        config,
        script=[api_error(openai.BadRequestError, "The model `deepseek-r1` does not exist", 400)],
    )
    with pytest.raises(DeepSeekBadRequestError) as excinfo:
        client.complete(MESSAGES)
    assert "DEEPSEEK_MODEL" in excinfo.value.hint


def test_422_json_mode_hint(config):
    client, _, _ = make_client(
        config,
        script=[api_error(openai.UnprocessableEntityError, "response_format json_object requires json in prompt", 422)],
    )
    with pytest.raises(DeepSeekBadRequestError) as excinfo:
        client.complete(MESSAGES)
    assert "JSON mode" in excinfo.value.hint


def test_unclassified_status_defaults_to_no_retry(config):
    client, llm, _ = make_client(config, script=[api_error(openai.APIStatusError, "teapot", 418)])
    with pytest.raises(DeepSeekError) as excinfo:
        client.complete(MESSAGES)
    assert excinfo.value.status_code == 418
    assert len(llm.calls) == 1


# ---------------------------------------------------------------------------
# degenerate responses
# ---------------------------------------------------------------------------


def test_truncated_response_is_an_error_not_partial_json(config):
    client, _, _ = make_client(config, script=[FakeCompletion('{"a": 1, "b": ', finish_reason="length")])
    with pytest.raises(DeepSeekTruncatedResponseError) as excinfo:
        client.complete(MESSAGES)
    assert "DEEPSEEK_MAX_TOKENS" in excinfo.value.hint


def test_empty_truncated_response_is_detected(config):
    client, _, _ = make_client(config, script=[FakeCompletion("", finish_reason="length")])
    with pytest.raises(DeepSeekTruncatedResponseError, match="before producing any content"):
        client.complete(MESSAGES)


def test_empty_json_content_is_retried_then_reported(config):
    import dataclasses

    config = dataclasses.replace(config, empty_content_retries=2)
    client, llm, sleeps = make_client(config, script=[FakeCompletion(""), FakeCompletion(None), FakeCompletion("   ")])
    with pytest.raises(DeepSeekEmptyResponseError):
        client.complete(MESSAGES)
    assert len(llm.calls) == 3
    assert len(sleeps) == 2


def test_empty_json_content_recovers(config):
    import dataclasses

    config = dataclasses.replace(config, empty_content_retries=2)
    client, llm, _ = make_client(config, script=[FakeCompletion(""), {"kind": "json", "data": {"a": 1}}])
    assert client.complete(MESSAGES).data == {"a": 1}
    assert len(llm.calls) == 2


def test_reasoning_content_is_kept_out_of_the_answer(config):
    client, _, _ = make_client(
        config,
        script=[FakeCompletion('{"a":1}', reasoning="I considered many layers ...")],
    )
    result = client.complete(MESSAGES)
    assert result.reasoning_content.startswith("I considered")
    assert result.as_dict()["reasoning_chars"] > 0


def test_missing_choices_is_reported(config):
    raw = types.SimpleNamespace(choices=[], usage=None, model="deepseek-flash", id=None)
    client, _, _ = make_client(config, script=[raw])
    result = client.complete(MESSAGES)
    assert result.content == ""
    assert "no choices" in result.repair_notes[0]


# ---------------------------------------------------------------------------
# guards & batching
# ---------------------------------------------------------------------------


def test_prompt_budget_guard_runs_before_the_request(config):
    import dataclasses

    config = dataclasses.replace(config, max_prompt_tokens=10)
    client, llm, _ = make_client(config, script=[{"kind": "json", "data": {}}])
    with pytest.raises(DeepSeekBadRequestError, match="payload too large before sending"):
        client.complete(MESSAGES)
    assert llm.calls == []


def test_estimation_helper(config):
    client, _, _ = make_client(config)
    assert client.estimate_prompt_tokens(MESSAGES) > 0


def test_min_interval_pacing(config):
    policy = RateLimitPolicy(max_attempts=2, min_interval=0.5, jitter=0.0)
    sleeps: list[float] = []
    client, _, _ = make_client(
        config,
        default={"kind": "json", "data": {"a": 1}},
        policy=policy,
        sleeps=sleeps,
    )
    for _ in range(3):
        client.complete(MESSAGES)
    assert len(sleeps) == 2, "first call is unpaced, later calls wait for the interval"
    assert all(value == pytest.approx(0.5, abs=0.2) for value in sleeps)


def test_complete_many_reports_errors_per_label(config):
    specs = [
        RequestSpec(messages=MESSAGES, label="sheet-1"),
        RequestSpec(messages=MESSAGES, label="sheet-2"),
        RequestSpec(messages=MESSAGES, label="sheet-3", overrides={"max_tokens": 128}),
    ]
    client, llm, _ = make_client(
        config,
        script=[
            {"kind": "json", "data": {"n": 1}},
            api_error(openai.RateLimitError, "busy", 429, {"retry-after": "1"}),
            {"kind": "json", "data": {"n": 3}},
        ],
        policy=RateLimitPolicy(max_attempts=1, jitter=0.0),
        default={"kind": "json", "data": {"n": 0}},
    )
    results = dict(client.complete_many(specs, concurrency=2))
    assert results["sheet-1"].data == {"n": 1}
    assert isinstance(results["sheet-2"], DeepSeekRateLimitError)
    assert results["sheet-3"].data is not None
    assert llm.calls[2]["max_tokens"] == 128 or any(call["max_tokens"] == 128 for call in llm.calls)


def test_complete_many_fail_fast_raises(config):
    specs = [RequestSpec(messages=MESSAGES, label=f"b{i}") for i in range(4)]
    client, _, _ = make_client(
        config,
        script=[api_error(openai.AuthenticationError, "bad key", 401)] * 4,
        policy=RateLimitPolicy(max_attempts=1, jitter=0.0),
    )
    with pytest.raises(DeepSeekAuthError):
        client.complete_many(specs, concurrency=1, fail_fast=True)


def test_complete_many_empty_input(config):
    client, _, _ = make_client(config)
    assert client.complete_many([]) == []


def test_health_check_reports_reachability(config):
    client, _, _ = make_client(config, script=[FakeCompletion("ok", prompt_tokens=9)])
    report = client.health_check()
    assert report["reachable"] is True
    assert report["reply_prefix"] == "ok"
    assert report["base_url"] == "https://api.deepseek.com"

    broken, _, _ = make_client(config, script=[api_error(openai.AuthenticationError, "bad key", 401)])
    report = broken.health_check()
    assert report["reachable"] is False
    assert report["error"]["error"] == "DeepSeekAuthError"


# ---------------------------------------------------------------------------
# policies / value objects
# ---------------------------------------------------------------------------


def test_policy_from_settings(settings):
    policy = RateLimitPolicy.from_settings(settings)
    assert policy.max_attempts == settings.deepseek_max_attempts == 5
    assert policy.min_delay == 1.0 and policy.max_delay == 60.0
    assert policy.min_interval == 0.0
    paced = RateLimitPolicy.from_settings(
        settings.__class__.from_env(environ={"DEEPSEEK_MIN_INTERVAL_MS": "1500", "DEEPSEEK_MAX_ATTEMPTS": "2"})
    )
    assert paced.min_interval == 1.5 and paced.max_attempts == 2
    # a zero/negative interval is clamped, never inverted
    assert RateLimitPolicy.from_settings(
        settings.__class__.from_env(environ={"DEEPSEEK_MIN_INTERVAL_MS": "-5"})
    ).min_interval == 0.0


def test_delay_for_bounds_and_clamps():
    policy = RateLimitPolicy(max_attempts=6, min_delay=1.0, max_delay=8.0, multiplier=2.0, jitter=0.0)
    assert [policy.delay_for(attempt) for attempt in range(1, 6)] == [1.0, 2.0, 4.0, 8.0, 8.0]
    assert policy.delay_for(1, retry_after=2.5) == 2.5
    assert policy.delay_for(1, retry_after=0) == 1.0


def test_usage_snapshot_math():
    usage = UsageSnapshot(prompt_tokens=100, completion_tokens=20, total_tokens=120, cached_tokens=40)
    assert usage.cache_hit_ratio == pytest.approx(0.4)
    merged = usage.merge(UsageSnapshot(prompt_tokens=100, completion_tokens=5, total_tokens=105, cached_tokens=0))
    assert merged.prompt_tokens == 200 and merged.total_tokens == 225 and merged.cached_tokens == 40
    assert merged.cache_hit_ratio == pytest.approx(0.2)
    assert UsageSnapshot().cache_hit_ratio is None
    assert set(merged.as_dict()) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_prompt_tokens",
        "cache_hit_ratio",
    }
    assert UsageSnapshot(prompt_tokens=1, completion_tokens=1, total_tokens=2).as_dict() == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }  # zero-only extras are not reported


def test_chat_result_json_or_raise():
    result = ChatResult(content="not json", data=None)
    with pytest.raises(DeepSeekJsonError):
        result.json_or_raise()
    assert ChatResult(content="{}", data={}).ok is True
