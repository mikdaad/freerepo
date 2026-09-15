"""Configuration: .env loading, validation, masking, requirement guards."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cad2ai.config import DEFAULT_BASE_URL, DEFAULT_MODEL, KNOWN_MODELS, Settings
from cad2ai.errors import ConfigError, MissingEnvironmentVariableError


def test_defaults_are_safe_without_env():
    settings = Settings.from_env(environ={})
    assert settings.deepseek_base_url == DEFAULT_BASE_URL == "https://api.deepseek.com"
    assert settings.deepseek_model == DEFAULT_MODEL
    assert settings.deepseek_api_key is None
    assert settings.deepseek_json_mode is True
    assert settings.payload_max_tokens == 120_000
    assert settings.max_file_mb == 512.0
    assert settings.allow_legacy_versions is False


def test_env_values_are_typed():
    settings = Settings.from_env(
        environ={
            "DEEPSEEK_API_KEY": "sk-abcdef0123456789",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
            "DEEPSEEK_MAX_TOKENS": "12345",
            "DEEPSEEK_JSON_MODE": "false",
            "CAD2AI_MAX_FILE_MB": "12.5",
            "CAD2AI_INCLUDE_HANDLES": "yes",
            "APS_OUTPUT_FORMAT": "SVF",
            "DEEPSEEK_REASONING_EFFORT": "HIGH",
        }
    )
    assert settings.deepseek_max_tokens == 12345
    assert settings.deepseek_json_mode is False
    assert settings.max_file_mb == 12.5
    assert settings.include_handles is True
    assert settings.aps_output_format == "svf"  # normalised
    assert settings.deepseek_reasoning_effort == "high"  # normalised
    assert settings.uses_known_model is True


def test_base_url_trailing_slash_is_stripped():
    settings = Settings.from_env(environ={"DEEPSEEK_BASE_URL": "https://proxy.internal/v1/"})
    assert settings.deepseek_base_url == "https://proxy.internal/v1"


def test_bad_values_are_rejected_with_names():
    with pytest.raises(ConfigError, match="DEEPSEEK_MAX_TOKENS must be an integer"):
        Settings.from_env(environ={"DEEPSEEK_MAX_TOKENS": "lots"})
    with pytest.raises(ConfigError, match="DEEPSEEK_JSON_MODE must be a boolean"):
        Settings.from_env(environ={"DEEPSEEK_JSON_MODE": "maybe"})
    with pytest.raises(ConfigError, match="DEEPSEEK_THINKING must be one of"):
        Settings.from_env(environ={"DEEPSEEK_THINKING": "sometimes"})
    with pytest.raises(ConfigError, match="APS_OUTPUT_FORMAT must be one of"):
        Settings.from_env(environ={"APS_OUTPUT_FORMAT": "obj"})
    with pytest.raises(ConfigError, match="CAD2AI_MAX_PAYLOAD_TOKENS must be >= 512"):
        Settings.from_env(environ={"CAD2AI_MAX_PAYLOAD_TOKENS": "10"})
    with pytest.raises(ConfigError, match="CAD2AI_MAX_FILE_MB must be > 0"):
        Settings.from_env(environ={"CAD2AI_MAX_FILE_MB": "0"})


def test_unknown_override_is_a_config_error():
    with pytest.raises(ConfigError, match="unknown setting"):
        Settings.from_env(environ={}, deepseek_api_kek="oops")


def test_overrides_win_over_env():
    settings = Settings.from_env(environ={"DEEPSEEK_MODEL": "deepseek-flash"}, deepseek_model="deepseek-v4-pro")
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert Settings.from_env(environ={"DEEPSEEK_MODEL": "deepseek-flash"}, deepseek_model=None).deepseek_model == "deepseek-flash"


def test_thinking_property_and_models():
    assert Settings.from_env(environ={"DEEPSEEK_THINKING": "enabled"}).thinking_enabled is True
    assert Settings.from_env(environ={}).thinking_enabled is False
    assert Settings.from_env(environ={"DEEPSEEK_MODEL": "gpt-4o"}).uses_known_model is False
    assert DEFAULT_MODEL in KNOWN_MODELS


def test_require_helpers():
    settings = Settings.from_env(environ={})
    with pytest.raises(MissingEnvironmentVariableError) as excinfo:
        settings.require_deepseek_key()
    assert "DEEPSEEK_API_KEY" in str(excinfo.value)
    assert "platform.deepseek.com" in excinfo.value.hint
    assert excinfo.value.exit_code == 2

    with pytest.raises(MissingEnvironmentVariableError) as excinfo:
        settings.require_aps_credentials()
    assert excinfo.value.details["missing"] == ["APS_CLIENT_ID", "APS_CLIENT_SECRET", "APS_BUCKET_KEY"]

    complete = Settings.from_env(
        environ={"APS_CLIENT_ID": "id", "APS_CLIENT_SECRET": "secret", "APS_BUCKET_KEY": "bucket"}
    )
    assert complete.require_aps_credentials() == ("id", "secret", "bucket")


def test_safe_dict_masks_secrets():
    settings = Settings.from_env(
        environ={
            "DEEPSEEK_API_KEY": "sk-supersecretvalue123",
            "APS_CLIENT_SECRET": "abcdefghijklmnop",
            "APS_CLIENT_ID": "my-client-id",
        }
    )
    safe = settings.to_safe_dict()
    assert "supersecret" not in json.dumps(safe)
    assert safe["deepseek_api_key"].endswith("123")
    assert safe["deepseek_api_key"].startswith("***")
    assert safe["aps_client_secret"].startswith("***")
    assert safe["aps_client_id"] == "my-client-id"  # ids are not secrets
    assert safe["log_level"] == "INFO"


def test_dotenv_file_is_read(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=sk-from-dotenv-000111\nDEEPSEEK_MODEL=deepseek-v4-pro\nCAD2AI_MAX_PAYLOAD_TOKENS=9000\n",
        encoding="utf-8",
    )
    script = (
        "import json,sys;"
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r});"
        "from cad2ai.config import Settings;"
        f"s=Settings.from_env(dotenv_path={str(env_file)!r});"
        "print(json.dumps({'key':s.deepseek_api_key,'model':s.deepseek_model,'tok':s.payload_max_tokens}))"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"key": "sk-from-dotenv-000111", "model": "deepseek-v4-pro", "tok": 9000}


def test_settings_are_immutable():
    settings = Settings.from_env(environ={})
    with pytest.raises(Exception):
        settings.deepseek_model = "nope"  # type: ignore[misc]

# ---------------------------------------------------------------------------
# --env-file handling
# ---------------------------------------------------------------------------


def test_explicit_env_file_is_read_even_after_the_default_lookup(tmp_path, monkeypatch):
    """Memoisation is per path, so ``--env-file`` always wins over a stale cache."""
    from cad2ai.config import Settings, reset_dotenv_cache

    clean = {k: v for k, v in os.environ.items() if not k.startswith("CAD2AI_")}
    monkeypatch.setattr(os, "environ", clean)
    reset_dotenv_cache()
    (tmp_path / "a.env").write_text("CAD2AI_MAX_PAYLOAD_TOKENS=900\n", encoding="utf-8")
    (tmp_path / "b.env").write_text("CAD2AI_MAX_PAYLOAD_TOKENS=1500\n", encoding="utf-8")
    assert Settings.from_env(dotenv_path=tmp_path / "a.env").payload_max_tokens == 900
    # the second file is a different path: it is read, but the process env set by
    # the first load still wins (that is the documented precedence)
    assert Settings.from_env(dotenv_path=tmp_path / "b.env").payload_max_tokens == 900
    reset_dotenv_cache()
    clean2 = {k: v for k, v in os.environ.items() if not k.startswith("CAD2AI_")}
    monkeypatch.setattr(os, "environ", clean2)
    assert Settings.from_env(dotenv_path=tmp_path / "b.env").payload_max_tokens == 1500
    reset_dotenv_cache()


def test_missing_env_file_is_a_config_error(tmp_path):
    from cad2ai.config import Settings, reset_dotenv_cache

    reset_dotenv_cache()
    with pytest.raises(ConfigError, match="does not exist"):
        Settings.from_env(dotenv_path=tmp_path / "ghost.env")
    reset_dotenv_cache()


def test_process_environment_beats_the_dotenv_file(tmp_path, monkeypatch):
    from cad2ai.config import Settings, reset_dotenv_cache

    reset_dotenv_cache()
    monkeypatch.setenv("CAD2AI_MAX_PAYLOAD_TOKENS", "2048")
    (tmp_path / ".env").write_text("CAD2AI_MAX_PAYLOAD_TOKENS=700\n", encoding="utf-8")
    assert Settings.from_env(dotenv_path=tmp_path / ".env").payload_max_tokens == 2048
    assert Settings.from_env(dotenv_path=tmp_path / ".env", payload_max_tokens=1024).payload_max_tokens == 1024
    reset_dotenv_cache()
