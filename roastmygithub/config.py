"""Settings loaded from the environment (and a local .env file)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    github_token: str = ""  # empty: fall back to `gh auth token`
    magic_hour_api_key: str = ""

    llm_api_key: str = ""
    llm_model: str = ""
    llm_provider: str | None = None  # inferred from the model id when unset
    llm_effort: str | None = None
    llm_base_url: str | None = None
    llm_usd_per_mtok_in: float | None = None
    llm_usd_per_mtok_out: float | None = None

    # IANA name, e.g. America/Toronto. Used for commits that carry no UTC offset of their own.
    roast_timezone: str | None = None

    # Shown on the end card under "Make yours".
    roast_repo_url: str = "github.com/1SS28/roastmygithub"

    magic_hour_plan: str = "auto"
    magic_hour_credits_per_usd: float | None = None
    roastmygithub_cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "roastmygithub")

    @property
    def cache_dir(self) -> Path:
        self.roastmygithub_cache_dir.mkdir(parents=True, exist_ok=True)
        return self.roastmygithub_cache_dir
