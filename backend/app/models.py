"""Shared data models for the generation pipeline."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    SCRIPTING = "scripting"
    VOICING = "voicing"
    VISUALS = "visuals"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"


class Tone(str, Enum):
    ENERGETIC = "energetic"
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    LUXURY = "luxury"
    PLAYFUL = "playful"


class TopicRequest(BaseModel):
    """Generate a promo short from a topic / marketing brief."""

    topic: str = Field(..., description="Product / brand / topic to promote")
    key_points: list[str] = Field(default_factory=list, description="Bullet points to include")
    tone: Tone = Tone.ENERGETIC
    duration_sec: int = Field(20, ge=5, le=60)
    language: str = "en"
    voice: str = "default"
    music: bool = True  # add a background music bed


class ImageRequest(BaseModel):
    """Generate a promo short from uploaded product image(s)."""

    topic: str = Field(..., description="Product / brand name")
    key_points: list[str] = Field(default_factory=list)
    tone: Tone = Tone.ENERGETIC
    duration_sec: int = Field(15, ge=5, le=60)
    language: str = "en"
    voice: str = "default"
    music: bool = True
    # image file paths are attached by the API layer after upload


class Scene(BaseModel):
    """A single beat of the short: one caption line + one voice line + one visual."""

    text: str  # on-screen caption
    narration: str  # what the voice says (may equal text)
    visual_query: str  # search/generation hint for the visual
    duration_sec: float = 3.0


class Script(BaseModel):
    title: str
    hook: str
    scenes: list[Scene]
    cta: str  # call to action

    @property
    def full_narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)


class ScriptDraft(BaseModel):
    """Returned by the script-generation step for the editing timeline."""

    script: Script
    tone: Tone
    language: str = "en"
    voice: str = "default"
    music: bool = True
    mode: str = "topic"  # "topic" | "image"
    image_job_id: str | None = None  # references uploaded images for image mode


class RenderRequest(BaseModel):
    """Render a (possibly edited) script into the final video."""

    script: Script
    tone: Tone = Tone.ENERGETIC
    language: str = "en"
    voice: str = "default"
    music: bool = True
    image_job_id: str | None = None  # reuse images uploaded during image-mode script gen


class JobInfo(BaseModel):
    id: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0  # 0-100
    message: str = ""
    mode: str = "topic"  # "topic" | "image"
    providers: dict[str, str] = Field(default_factory=dict)
    video_url: str | None = None
    error: str | None = None
