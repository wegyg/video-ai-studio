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
        """Output size for this ratio, both sides even.

        yuv420p subsamples chroma by two, so libx264 refuses an odd width or
        height. Most bases divide cleanly — 1080 gives 1920, 720 gives 1280 — but
        480 works out to 853.33 and truncating that produced an odd 853 and a
        render that died with "Generic error in an external library". Rounding to
        the nearest even number keeps any base usable.
        """
        def even(value: float) -> int:
            return max(2, round(value / 2) * 2)

        long_side = even(base * 16 / 9)
        base = even(base)
        if self is AspectRatio.VERTICAL:
            return base, long_side            # 1080 x 1920
        if self is AspectRatio.SQUARE:
            return base, base                 # 1080 x 1080
        return long_side, base                # 1920 x 1080


class CaptionStyle(str, Enum):
    """How captions are drawn/animated on screen."""

    STATIC = "static"      # whole caption appears at once (original)
    POP = "pop"            # words pop/scale in one-by-one
    KARAOKE = "karaoke"    # all words shown, current word highlighted


class MotionType(str, Enum):
    """Camera movement applied to a scene background (Ken Burns family)."""

    NONE = "none"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    AUTO = "auto"  # a different direction per scene, never twice in a row


class MotionIntensity(str, Enum):
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class MotionSettings(BaseModel):
    """Project-wide camera-movement defaults. Scenes may override both fields."""

    type: MotionType = MotionType.AUTO
    intensity: MotionIntensity = MotionIntensity.MEDIUM


# What AUTO cycles through. No entry repeats next to another (including the wrap).
AUTO_MOTION_CYCLE: list[MotionType] = [
    MotionType.ZOOM_IN,
    MotionType.PAN_LEFT,
    MotionType.ZOOM_OUT,
    MotionType.PAN_RIGHT,
    MotionType.PAN_UP,
    MotionType.PAN_DOWN,
]


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
    motion: MotionSettings = Field(default_factory=MotionSettings)
    overlays: list[Overlay] = Field(default_factory=list)


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
    motion: MotionSettings = Field(default_factory=MotionSettings)
    overlays: list[Overlay] = Field(default_factory=list)
    # image file paths are attached by the API layer after upload


class OverlayKind(str, Enum):
    """What a graphic overlay is."""

    TEXT = "text"        # a line of text, optionally on a background box
    SHAPE = "shape"      # label box / arrow / circle / highlight bar
    LOGO = "logo"        # an uploaded PNG
    STICKER = "sticker"  # one of the built-in badges, drawn in code


class ShapeKind(str, Enum):
    LABEL_BOX = "label_box"          # rounded outline to frame part of the picture
    ARROW = "arrow"                  # points at something
    CIRCLE = "circle"                # rings a detail
    HIGHLIGHT_BAR = "highlight_bar"  # solid bar to underline a claim


class StickerPreset(str, Enum):
    """Ten badges drawn with PIL. Nothing is fetched, so nothing is licensed."""

    NEW = "new"
    SALE = "sale"
    HOT = "hot"
    BEST = "best"
    FREE = "free"
    SOLD_OUT = "sold_out"
    CHECK = "check"
    STAR = "star"
    ARROW_DOWN = "arrow_down"
    PERCENT = "percent"


# A graphic fades in and out over this long by default. Same ffmpeg `fade` family
# the start/end fades use, so overlays feel like the rest of the edit.
OVERLAY_FADE_SEC = 0.3


class Overlay(BaseModel):
    """A graphic laid over the video.

    Position and size are percentages of the frame, never pixels, so the same
    overlay lands in the same visual spot in 9:16, 1:1 and 16:9. `x_pct`/`y_pct`
    are the CENTRE of the graphic, which is what makes the 9-grid presets line up.

    Timing is either a scene (`scene_index`) or an explicit window on the finished
    timeline (`start_sec`/`end_sec`). With neither, the overlay covers the whole
    video.
    """

    kind: OverlayKind
    # --- placement (percent of frame, centre-anchored) ---
    x_pct: float = Field(50.0, ge=0.0, le=100.0)
    y_pct: float = Field(50.0, ge=0.0, le=100.0)
    # --- timing ---
    scene_index: int | None = Field(None, ge=0)
    start_sec: float | None = Field(None, ge=0.0)
    end_sec: float | None = Field(None, ge=0.0)
    fade_sec: float = Field(OVERLAY_FADE_SEC, ge=0.0, le=2.0)
    # --- shared look ---
    color: str = "#FFFFFF"        # hex, used for text / shape / sticker
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    # --- text ---
    text: str = ""
    size_pct: float = Field(6.0, gt=0.0, le=100.0)  # text height / sticker+logo width
    background_box: bool = False   # draw a filled box behind the text
    box_color: str = "#000000"
    # --- shape ---
    shape: ShapeKind = ShapeKind.LABEL_BOX
    width_pct: float = Field(40.0, gt=0.0, le=100.0)
    height_pct: float = Field(12.0, gt=0.0, le=100.0)
    thickness_pct: float = Field(0.8, gt=0.0, le=20.0)  # stroke weight, % of frame width
    # --- logo ---
    # Clients send `logo_id`, handed out by the logo upload endpoint. The API
    # turns it into `logo_path` itself and always overwrites whatever arrived in
    # that field, so a request cannot point the renderer at an arbitrary file.
    logo_id: str | None = None
    logo_path: str | None = None
    # --- sticker ---
    sticker: StickerPreset = StickerPreset.NEW
    # Turns the graphic about its centre. Mostly for arrows: the arrow is drawn
    # pointing right, so 90 aims it down, 270 up.
    rotation_deg: float = Field(0.0, ge=-360.0, le=360.0)

    def window(self, scene_starts: list[float], scene_durations: list[float],
               total: float) -> tuple[float, float]:
        """Absolute (start, end) on the finished timeline."""
        if self.scene_index is not None and self.scene_index < len(scene_starts):
            i = self.scene_index
            return scene_starts[i], scene_starts[i] + scene_durations[i]
        start = self.start_sec if self.start_sec is not None else 0.0
        end = self.end_sec if self.end_sec is not None else total
        return start, max(start, end)


class Scene(BaseModel):
    """A single beat of the short: one caption line + one voice line + one visual."""

    text: str  # on-screen caption
    narration: str  # what the voice says (may equal text)
    visual_query: str  # search/generation hint for the visual
    duration_sec: float = 3.0
    # Transition INTO the next scene. None = use the project default.
    transition: TransitionType | None = None
    # Camera movement for this scene. None = use the project default.
    motion: MotionType | None = None
    motion_intensity: MotionIntensity | None = None


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
    motion: MotionSettings = Field(default_factory=MotionSettings)
    overlays: list[Overlay] = Field(default_factory=list)
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
    motion: MotionSettings = Field(default_factory=MotionSettings)
    overlays: list[Overlay] = Field(default_factory=list)
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
