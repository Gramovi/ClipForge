"""Application configuration (environment variables / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core ---------------------------------------------------------------
    app_name: str = "ClipForge"
    environment: Literal["development", "production", "test"] = "development"
    secret_key: str = Field(default="change-me-in-production-please", min_length=16)
    database_url: str = "postgresql+psycopg://clipforge:clipforge@localhost:5432/clipforge"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = Path("./data")
    shared_dir: Path = REPO_SHARED_DIR
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_days: int = 14
    allow_registration: bool = True

    # --- uploads ------------------------------------------------------------
    max_upload_bytes: int = 5 * 1024**3  # 5 GB
    upload_chunk_bytes: int = 8 * 1024**2  # 8 MB (suggested to the client)
    max_video_seconds: int = 4 * 3600
    allow_url_import: bool = True

    # --- transcription ------------------------------------------------------
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"  # auto | cpu | cuda
    whisper_compute_type: str = "auto"  # auto | int8 | float16 | int8_float16
    whisper_cpu_threads: int = 0  # 0 = auto
    whisper_beam_size: int = 5
    whisper_models_dir: Path | None = None

    # --- LLM ----------------------------------------------------------------
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_effort: Literal["low", "medium", "high"] = "medium"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 16384
    llm_max_retries: int = 4
    llm_timeout_seconds: int = 600
    llm_window_minutes: float = 12.0
    llm_window_overlap_minutes: float = 1.5
    llm_concurrency: int = 2

    # --- rendering ----------------------------------------------------------
    x264_preset: str = "slow"
    x264_crf: int = 18
    audio_bitrate: str = "192k"
    render_threads: int = 0
    face_sample_fps: float = 5.0
    render_on_process: bool = True  # render every clip during processing

    # --- job runtime --------------------------------------------------------
    job_timeout_seconds: int = 6 * 3600

    @property
    def fonts_dir(self) -> Path:
        return self.shared_dir / "fonts"

    @property
    def presets_file(self) -> Path:
        return self.shared_dir / "caption-presets.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def public_dict(self) -> dict[str, Any]:
        """Settings safe to expose to the frontend. Never includes secrets."""
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.anthropic_model if self.llm_provider == "anthropic" else self.ollama_model,
            "whisper_model": self.whisper_model,
            "max_upload_bytes": self.max_upload_bytes,
            "upload_chunk_bytes": self.upload_chunk_bytes,
            "allow_url_import": self.allow_url_import,
            "x264_preset": self.x264_preset,
            "x264_crf": self.x264_crf,
            "allow_registration": self.allow_registration,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
