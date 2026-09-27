"""Provider interfaces (adapter pattern).

Every AI stage is expressed as an abstract provider so that a free/offline
implementation and a paid-API implementation are interchangeable. A registry
picks the concrete provider at runtime based on config + available API keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from app.models import ImageRequest, Script, TopicRequest


@dataclass
class VisualAsset:
    """A scene background: either a still image or a ready-to-use video clip."""

    path: str
    kind: Literal["image", "video"] = "image"


class ScriptProvider(ABC):
    """Turns a brief into a structured, scene-by-scene short-form script."""

    name: str = "base"

    @abstractmethod
    async def generate(self, req: TopicRequest | ImageRequest) -> Script: ...


class TTSProvider(ABC):
    """Turns narration text into an audio file. Returns the output path."""

    name: str = "base"

    @abstractmethod
    async def synthesize(self, text: str, out_path: str, *, language: str, voice: str) -> str: ...


class VisualsProvider(ABC):
    """Produces a background image/clip for a scene. Returns the output path.

    `existing_images` lets the image-to-video mode feed uploaded product photos
    in so providers can reuse them instead of fetching/generating new visuals.
    """

    name: str = "base"

    @abstractmethod
    async def get_visual(
        self,
        query: str,
        out_path: str,
        *,
        width: int,
        height: int,
        existing_images: list[str] | None = None,
        index: int = 0,
    ) -> VisualAsset:
        """Return a VisualAsset. `out_path` is a suggested path (extension may
        change for video). Providers should always produce SOMETHING usable."""
        ...


class VideoGenProvider(ABC):
    """Premium tier: animate a still image (or a text prompt) into a real video
    clip using a generative model (Runway, Kling, etc.). Returns the clip path.

    Implementations are async and may poll a remote job. They should raise on
    failure so the pipeline can gracefully fall back to the Ken Burns path.
    """

    name: str = "base"

    @abstractmethod
    async def animate(
        self,
        image_path: str,
        out_path: str,
        *,
        prompt: str,
        duration_sec: float,
        width: int,
        height: int,
    ) -> str: ...
