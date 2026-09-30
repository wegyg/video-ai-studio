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


class AspectRatio(str, Enum):
    """Output aspect ratios for the different social platforms."""

    VERTICAL = "9:16"    # Reels / Shorts / TikTok
    SQUARE = "1:1"       # Instagram feed
    LANDSCAPE = "16:9"   # YouTube

    def dimensions(self, base: int = 1080) -> tuple[int, int]:
        if self is AspectRatio.VERTICAL:
            return base, int(base * 16 / 9)   # 1080 x 1920
        if self is AspectRatio.SQUARE:
            return base, base                 # 1080 x 1080
        return int(base * 16 / 9), base       # 1920 x 1080


class CaptionStyle(str, Enum):
    """How captions are drawn/animated on screen."""

    STATIC = "static"      # whole caption appears at once (original)
    POP = "pop"            # words pop/scale in one-by-one
    KARAOKE = "karaoke"    # all words shown, current word highlighted


class TransitionType(str, Enum):
    """How one scene gives way to the next (ffmpeg xfade transitions)."""

    CUT = "cut"                # hard cut — the original behaviour
    CROSSFADE = "crossfade"    # the two scenes dissolve into each other
    FADE = "fade"              # through black
    FADE_WHITE = "fade_white"  # through white
    SLIDE_LEFT = "slide_left"
    SLIDE_UP = "slide_up"
    ZOOM_IN = "zoom_in"

    @property
    def xfade_name(self) -> str | None:
        """Matching ffmpeg xfade transition, or None for a hard cut."""
        return {
            TransitionType.CROSSFADE: "fade",
            TransitionType.FADE: "fadeblack",
            TransitionType.FADE_WHITE: "fadewhite",
            TransitionType.SLIDE_LEFT: "slideleft",
            TransitionType.SLIDE_UP: "slideup",
            TransitionType.ZOOM_IN: "zoomin",
        }.get(self)


TRANSITION_MIN_SEC = 0.2
TRANSITION_MAX_SEC = 1.5


class TransitionSettings(BaseModel):
    """Project-wide transition defaults. Scenes may override the type."""

    type: TransitionType = TransitionType.CROSSFADE
    duration_sec: float = Field(0.5, ge=TRANSITION_MIN_SEC, le=TRANSITION_MAX_SEC)
    fade_in: bool = True   # fade up from black at the very start
    fade_out: bool = True  # fade down to black at the very end


class TopicRequest(BaseModel):
    """Generate a promo short from a topic / marketing brief."""

    topic: str = Field(..., description="Product / brand / topic to promote")
    key_points: list[str] = Field(default_factory=list, description="Bullet points to include")
    tone: Tone = Tone.ENERGETIC
    duration_sec: int = Field(20, ge=5, le=60)
    language: str = "en"
    voice: str = "default"
    music: bool = True  # add a background music bed
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    caption_style: CaptionStyle = CaptionStyle.POP
    transition: TransitionSettings = Field(default_factory=TransitionSettings)


class ImageRequest(BaseModel):
    """Generate a promo short from uploaded product image(s)."""

    topic: str = Field(..., description="Product / brand name")
    key_points: list[str] = Field(default_factory=list)
    tone: Tone = Tone.ENERGETIC
    duration_sec: int = Field(15, ge=5, le=60)
    language: str = "en"
    voice: str = "default"
    music: bool = True
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    caption_style: CaptionStyle = CaptionStyle.POP
    transition: TransitionSettings = Field(default_factory=TransitionSettings)
    # image file paths are attached by the API layer after upload


class Scene(BaseModel):
    """A single beat of the short: one caption line + one voice line + one visual."""

    text: str  # on-screen caption
    narration: str  # what the voice says (may equal text)
    visual_query: str  # search/generation hint for the visual
    duration_sec: float = 3.0
    # Transition INTO the next scene. None = use the project default.
    transition: TransitionType | None = None


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
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    caption_style: CaptionStyle = CaptionStyle.POP
    transition: TransitionSettings = Field(default_factory=TransitionSettings)
    mode: str = "topic"  # "topic" | "image" | "video"
    image_job_id: str | None = None  # references uploaded images for image mode
    video_job_id: str | None = None  # references uploaded footage for video mode


class RenderRequest(BaseModel):
    """Render a (possibly edited) script into the final video."""

    script: Script
    tone: Tone = Tone.ENERGETIC
    language: str = "en"
    voice: str = "default"
    music: bool = True
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    caption_style: CaptionStyle = CaptionStyle.POP
    transition: TransitionSettings = Field(default_factory=TransitionSettings)
    image_job_id: str | None = None  # reuse images uploaded during image-mode script gen
    video_job_id: str | None = None  # reuse footage uploaded during video-mode script gen


class JobInfo(BaseModel):
    id: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0  # 0-100
    message: str = ""
    mode: str = "topic"  # "topic" | "image"
    providers: dict[str, str] = Field(default_factory=dict)
    video_url: str | None = None
    error: str | None = None
