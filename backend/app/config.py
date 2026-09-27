"""Application configuration and provider selection.

The app is designed to run with ZERO API keys (free mode) and progressively
upgrade to higher-quality providers as keys become available.

Provider selection strategy for each stage (script / tts / visuals):
- "auto"  : use the best available provider given configured API keys,
            falling back to the free provider when no key is present.
- "free"  : force the local/offline free provider.
- "<name>": force a specific provider (errors if its key is missing).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # --- Storage ---
    # Where generated jobs / assets / final videos are written.
    output_dir: str = "output"

    # --- Provider selection (auto | free | <provider name>) ---
    script_provider: str = "auto"
    tts_provider: str = "auto"
    visuals_provider: str = "auto"

    # --- Optional API keys (leave empty for free mode) ---
    openai_api_key: str = ""
    runway_api_key: str = ""
    kling_api_key: str = ""
    pexels_api_key: str = ""  # free stock video/photo API (optional, recommended)
    elevenlabs_api_key: str = ""

    # --- Rendering defaults (9:16 vertical short) ---
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30

    # --- Background music ---
    # When true, adds a music bed: a local track from assets/music/ if present,
    # otherwise a procedurally-synthesized ambient bed (no files needed).
    music_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
