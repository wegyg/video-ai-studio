"""Provider registry: resolves the concrete provider for each stage.

Resolution rules per stage (see config.py):
- "free"        -> the offline/free provider.
- "<name>"      -> that specific provider (raises if key missing).
- "auto"        -> best available given configured keys, else free fallback.

The registry NEVER raises in "auto" mode: the app is guaranteed to run with
zero API keys. Selected provider names are surfaced to the UI per job.
"""

from __future__ import annotations

import importlib.util

from app.config import Settings
from app.providers.base import ScriptProvider, TTSProvider, VideoGenProvider, VisualsProvider
from app.providers.script_providers import FreeScriptProvider, OpenAIScriptProvider
from app.providers.tts_providers import GTTSProvider, OpenAITTSProvider, SilentTTSProvider
from app.providers.videogen_providers import FalVideoGenProvider, RunwayVideoGenProvider
from app.providers.visual_providers import GradientVisualProvider, PexelsVisualProvider


def _has_module(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    # --- Script ---------------------------------------------------------
    def script(self) -> ScriptProvider:
        choice = self.s.script_provider
        if choice == "openai" or (
            choice == "auto" and self.s.openai_api_key and _has_module("openai")
        ):
            if self.s.openai_api_key and _has_module("openai"):
                return OpenAIScriptProvider(self.s)
        return FreeScriptProvider()

    # --- TTS ------------------------------------------------------------
    def tts(self) -> TTSProvider:
        choice = self.s.tts_provider
        if choice == "openai" or (
            choice == "auto" and self.s.openai_api_key and _has_module("openai")
        ):
            if self.s.openai_api_key and _has_module("openai"):
                return OpenAITTSProvider(self.s)
        if choice == "gtts" or choice == "auto":
            if _has_module("gtts"):
                return GTTSProvider()
        if choice == "silent":
            return SilentTTSProvider()
        # ultimate always-available fallback
        return SilentTTSProvider()

    # --- Visuals --------------------------------------------------------
    def visuals(self) -> VisualsProvider:
        choice = self.s.visuals_provider
        if choice == "pexels" or (choice == "auto" and self.s.pexels_api_key):
            if self.s.pexels_api_key:
                return PexelsVisualProvider(self.s)
        return GradientVisualProvider()

    # --- Video generation (premium image-to-video) ---------------------
    def videogen(self) -> VideoGenProvider | None:
        """Returns a premium image-to-video provider, or None (free tier -> the
        pipeline uses Ken Burns instead). Never raises in auto/off."""
        choice = self.s.videogen_provider
        if choice == "off":
            return None
        if choice == "fal" or (choice == "auto" and self.s.fal_api_key):
            if self.s.fal_api_key:
                return FalVideoGenProvider(self.s)
        if choice == "runway" or (choice == "auto" and self.s.runway_api_key):
            if self.s.runway_api_key:
                return RunwayVideoGenProvider(self.s)
        return None

    def summary(self) -> dict[str, str]:
        vg = self.videogen()
        return {
            "script": self.script().name,
            "tts": self.tts().name,
            "visuals": self.visuals().name,
            "videogen": vg.name if vg else "kenburns",
        }
