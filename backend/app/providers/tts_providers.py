"""Text-to-speech providers.

SilentTTSProvider - no key & no network needed: emits a silent audio track sized
                    to the narration so rendering always succeeds (true offline).
GTTSProvider      - free online TTS via gTTS (no key, needs network). Preferred
                    free provider when the package + network are available.
OpenAITTSProvider - high quality voices when OPENAI_API_KEY is set.
"""

from __future__ import annotations

import asyncio
import subprocess

from app.config import Settings
from app.providers.base import TTSProvider


def _estimate_duration(text: str) -> float:
    # ~2.7 words/sec average narration pace; clamp to a sane minimum.
    words = max(len(text.split()), 1)
    return max(2.0, round(words / 2.7, 2))


class SilentTTSProvider(TTSProvider):
    """Always-available fallback. Produces a silent WAV of the estimated length."""

    name = "silent"

    async def synthesize(self, text: str, out_path: str, *, language: str, voice: str) -> str:
        dur = _estimate_duration(text)
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(dur), "-c:a", "aac", out_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        await proc.wait()
        return out_path


class GTTSProvider(TTSProvider):
    name = "gtts"

    async def synthesize(self, text: str, out_path: str, *, language: str, voice: str) -> str:
        from gtts import gTTS  # optional dependency

        def _run() -> None:
            tts = gTTS(text=text or "...", lang=(language or "en").split("-")[0])
            tts.save(out_path)

        await asyncio.get_event_loop().run_in_executor(None, _run)
        return out_path


class OpenAITTSProvider(TTSProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def synthesize(self, text: str, out_path: str, *, language: str, voice: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        chosen = voice if voice and voice != "default" else "alloy"
        resp = await client.audio.speech.create(
            model="gpt-4o-mini-tts", voice=chosen, input=text or "..."
        )
        resp.stream_to_file(out_path)
        return out_path
