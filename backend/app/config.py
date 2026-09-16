"""Runtime configuration for the orchestration backend (pydantic-settings).

Every knob can be overridden via environment variables or a local `.env`
file (see `.env.example`).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- AI engine (DeepSeek, consumed through the standard `openai` SDK) ---
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # Offline development: deterministic stubs instead of real API calls.
    # Also implied automatically when deepseek_api_key is empty.
    mock_ai: bool = False

    # --- Municipality rule (Phase 3) ------------------------------------------
    min_setback_meters: float = 1.5

    # --- Phase 1: C# geometry engine -------------------------------------------
    # Path to the published `cad-engine` binary (recommended for speed).
    cad_engine_bin: str | None = None
    # Fallback: `dotnet run --project <this dir>` when no binary is configured.
    cad_engine_project: Path = REPO_ROOT / "cad-engine" / "CadEngine"
    cad_engine_timeout_s: int = 300

    # --- Supabase / PostgreSQL (optional) ---------------------------------------
    database_url: str | None = None

    # --- HTTP --------------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str | None = r"https://.*\.e2b\.app"
    upload_max_mb: int = 200

    @property
    def ai_is_mocked(self) -> bool:
        return self.mock_ai or not self.deepseek_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
