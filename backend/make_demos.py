"""Customer demo clips: one per Phase 4 feature.

Three 15-second 9:16 shorts for a posture-correction clinic, in Korean, with a
confident/professional tone and background music:

  demo_transition.mp4  a different transition at each of the four scene joins
  demo_panning.mp4     a different camera motion in each scene
  demo_graphics.mp4    text box + circle highlight + logo + NEW sticker together

Scene lengths are held at the target so the total lands on 15s: the pipeline
stretches a scene when its narration is longer than the scene, so every line here
was measured first and kept under the limit.

Usage (from backend/):
    .venv/bin/python make_demos.py
    .venv/bin/python make_demos.py --only graphics --sheets
"""

from __future__ import annotations

import argparse
import asyncio
import os

import httpx

from PIL import Image, ImageDraw

from app.config import get_settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    JobInfo,
    MotionIntensity,
    MotionSettings,
    MotionType,
    Overlay,
    OverlayKind,
    Scene,
    Script,
    ShapeKind,
    StickerPreset,
    Tone,
    TopicRequest,
    TransitionSettings,
    TransitionType,
)
from app.pipeline import Pipeline
from app.providers.base import VisualAsset, VisualsProvider
from app.providers.visual_providers import PexelsVisualProvider, _normalize_video
from app.render import _find_font, _probe_duration
from verify_render import contact_sheet

TARGET = 15.0
NAVY = "#123A6B"      # trustworthy, not shouty
ACCENT = "#1E9BD7"


def make_logo(path: str) -> str:
    """A stand-in clinic wordmark, drawn here so the demo needs no asset files."""
    from PIL import ImageFont

    w, h = 760, 200
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=44, fill=(18, 58, 107, 245))
    text = "바른자세 클리닉"
    font_path = _find_font(text)
    font = ImageFont.truetype(font_path, 74) if font_path else ImageFont.load_default()
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    d.text(((w - (x1 - x0)) / 2 - x0, (h - (y1 - y0)) / 2 - y0), text, font=font,
           fill=(255, 255, 255, 255))
    d.rounded_rectangle([46, h - 40, w - 46, h - 30], radius=5, fill=(30, 155, 215, 255))
    img.save(path, "PNG")
    return path


def scene(text: str, secs: float, clip_id: int, *,
          transition: TransitionType | None = None,
          motion: MotionType | None = None) -> Scene:
    """One beat, pinned to a specific Pexels clip.

    The stock clip is named by id rather than by search term. Searching returns a
    different clip per scene index with no regard for what is in it, which on the
    approved terms produced bare-skin massage close-ups — unusable for a clinic
    promo. Ids were chosen by eye from the candidates for the approved terms (see
    CLIP_SOURCE), and pinning them also makes a re-render reproducible.
    """
    return Scene(text=text, narration=text, visual_query=f"pexels:{clip_id}",
                 duration_sec=secs, transition=transition, motion=motion)


# Which approved search term each pinned clip came from, and why it was picked.
# Terms: physiotherapy, posture, spine, wellness clinic, stretching, foot care.
CLIP_SOURCE = {
    6800263: "posture #0 — woman in athletic top, back view, clothed",
    29807500: "physiotherapy #3 — resistance-band exercise on a mat",
    5030439: "spine #2 — clinician reading a spinal x-ray",
    7579338: "wellness clinic #2 — doctor with stethoscope and chart",
    8313358: "wellness clinic #3 — consultation in a bright room",
    7299337: "spine #0 — hands on lower back, activewear, outdoors",
    30352917: "physiotherapy #5 — rehab bars, arm exercise",
    6939994: "stretching #3 — pilates studio, equipment in frame",
    6296149: "stretching #4 — guided floor stretch, detailed room",
    7754850: "foot care #2 — gloved clinical foot examination",
    8313074: "wellness clinic #0 — treatment couch, calm and bright",
}


class CuratedPexelsProvider(VisualsProvider):
    """Fetches the exact Pexels clip named in `visual_query` as `pexels:<id>`.

    Falls back to the stock provider for anything not pinned, so the class stays
    usable if a scene is added without choosing a clip for it.
    """

    name = "pexels-curated"

    def __init__(self, settings) -> None:
        self._s = settings
        self._fallback = PexelsVisualProvider(settings)

    async def get_visual(self, query: str, out_path: str, *, width: int, height: int,
                         existing_images: list[str] | None = None,
                         index: int = 0) -> VisualAsset:
        if not query.startswith("pexels:"):
            return await self._fallback.get_visual(
                query, out_path, width=width, height=height,
                existing_images=existing_images, index=index)
        clip_id = query.split(":", 1)[1]
        headers = {"Authorization": self._s.pexels_api_key}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"https://api.pexels.com/videos/videos/{clip_id}",
                                 headers=headers)
            r.raise_for_status()
            files = sorted(
                [f for f in r.json().get("video_files", []) if f.get("height")],
                key=lambda f: f["height"], reverse=True,
            )
            portrait = [f for f in files if f["height"] >= f.get("width", 0)]
            # prefer a portrait file no taller than ~1920 to avoid a needless 4K pull
            sized = [f for f in (portrait or files) if f["height"] <= 2200]
            chosen = (sized or portrait or files)[0]
            raw = out_path + ".src.mp4"
            async with client.stream("GET", chosen["link"]) as resp:
                resp.raise_for_status()
                with open(raw, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
        clip = out_path + ".clip.mp4"
        await _normalize_video(raw, clip, width, height, max_sec=6.0)
        try:
            os.remove(raw)
        except OSError:
            pass
        return VisualAsset(path=clip, kind="video")


def demo_transition() -> tuple[Script, TopicRequest]:
    """Five scenes, so all four transitions get a join to themselves."""
    d = TARGET / 5
    script = Script(
        title="바른자세 클리닉",
        hook="혹시 거북목인가요",
        scenes=[
            scene("혹시 거북목인가요", d, 6800263, transition=TransitionType.CROSSFADE),
            scene("어깨가 자주 뭉치나요", d, 29807500, transition=TransitionType.FADE),
            scene("원인부터 찾습니다", d, 5030439, transition=TransitionType.SLIDE_LEFT),
            scene("일대일 맞춤 교정", d, 7579338, transition=TransitionType.ZOOM_IN),
            scene("첫 검사 무료입니다", d, 8313358),
        ],
        cta="첫 검사 무료입니다",
    )
    req = TopicRequest(
        topic="체형교정센터 홍보", tone=Tone.PROFESSIONAL, duration_sec=15,
        language="ko", music=True, aspect_ratio=AspectRatio.VERTICAL,
        caption_style=CaptionStyle.POP,
        transition=TransitionSettings(type=TransitionType.CROSSFADE, duration_sec=0.5),
        # a gentle push everywhere, so the transitions stay the subject
        motion=MotionSettings(type=MotionType.ZOOM_IN, intensity=MotionIntensity.WEAK),
    )
    return script, req


def demo_panning() -> tuple[Script, TopicRequest]:
    """Four scenes, one camera motion each."""
    d = TARGET / 4
    script = Script(
        title="바른자세 클리닉",
        hook="골반이 틀어졌나요",
        scenes=[
            # clips with plenty of detail, so the camera has something to move across
            scene("골반이 틀어졌나요", d, 7299337, motion=MotionType.ZOOM_IN),
            scene("전문 교정사와 함께", d, 30352917, motion=MotionType.PAN_LEFT),
            scene("자세 검사는 무료", d, 6939994, motion=MotionType.PAN_UP),
            scene("바른 자세로 바뀝니다", d, 6296149, motion=MotionType.AUTO),
        ],
        cta="바른 자세로 바뀝니다",
    )
    req = TopicRequest(
        topic="체형교정센터 홍보", tone=Tone.PROFESSIONAL, duration_sec=15,
        language="ko", music=True, aspect_ratio=AspectRatio.VERTICAL,
        caption_style=CaptionStyle.POP,
        transition=TransitionSettings(type=TransitionType.CROSSFADE, duration_sec=0.5),
        motion=MotionSettings(type=MotionType.AUTO, intensity=MotionIntensity.MEDIUM),
    )
    return script, req


def demo_graphics(logo_path: str) -> tuple[Script, TopicRequest]:
    """Four scenes carrying all four overlay kinds at once."""
    d = TARGET / 4
    script = Script(
        title="바른자세 클리닉",
        hook="통증 없이 편하게",
        scenes=[
            scene("통증 없이 편하게", d, 7754850),
            scene("십년 경력 전문가", d, 7579338),
            # scene 2 carries the circle highlight, so a clothed back view that the
            # ring can sensibly point at
            scene("자세 검사는 무료", d, 6800263),
            scene("지금 예약하세요", d, 8313074),
        ],
        cta="지금 예약하세요",
    )
    req = TopicRequest(
        topic="체형교정센터 홍보", tone=Tone.PROFESSIONAL, duration_sec=15,
        language="ko", music=True, aspect_ratio=AspectRatio.VERTICAL,
        caption_style=CaptionStyle.POP,
        transition=TransitionSettings(type=TransitionType.CROSSFADE, duration_sec=0.5),
        motion=MotionSettings(type=MotionType.AUTO, intensity=MotionIntensity.WEAK),
        overlays=[
            # clinic mark, top-right, for the whole clip
            Overlay(kind=OverlayKind.LOGO, logo_path=logo_path, x_pct=70, y_pct=9,
                    size_pct=46, opacity=0.95),
            # standing offer, just under the mark
            Overlay(kind=OverlayKind.TEXT, text="첫 검사 무료", x_pct=50, y_pct=21,
                    size_pct=6.5, color="#FFFFFF", background_box=True, box_color=NAVY),
            # NEW badge announces the programme on the opening scene
            Overlay(kind=OverlayKind.STICKER, sticker=StickerPreset.NEW, x_pct=20,
                    y_pct=33, size_pct=15, color=ACCENT, scene_index=0),
            # ring the area being talked about, on the third scene
            Overlay(kind=OverlayKind.SHAPE, shape=ShapeKind.CIRCLE, x_pct=57, y_pct=45,
                    width_pct=34, color=ACCENT, thickness_pct=0.9, scene_index=2),
        ],
    )
    return script, req


async def render(name: str, script: Script, req: TopicRequest, out_root: str,
                 sheet: bool) -> dict:
    settings = get_settings()
    pipe = Pipeline(settings)
    if settings.pexels_api_key:
        pipe.registry.visuals = lambda: CuratedPexelsProvider(settings)  # type: ignore[method-assign]
    job_dir = os.path.join(out_root, name)
    final = await pipe.run(JobInfo(id=f"demo_{name}", mode="topic"), req, job_dir,
                           script=script)
    dest = os.path.join(out_root, f"demo_{name}.mp4")
    os.replace(final, dest)
    dur = await _probe_duration(dest)
    row = {
        "name": f"demo_{name}.mp4",
        "duration": round(dur, 2),
        "size_mb": round(os.path.getsize(dest) / 1e6, 2),
        "visuals": pipe.registry.visuals().name,
        "path": dest,
    }
    if sheet:
        row["sheet"] = contact_sheet(
            dest, os.path.join(out_root, f"sheet_{name}.jpg"),
            [dur * f for f in (0.06, 0.2, 0.34, 0.48, 0.62, 0.78, 0.92)],
            cols=7, width=180,
        )
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="transition | panning | graphics")
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    settings = get_settings()
    out_root = args.out_dir or os.path.join(settings.output_dir, "demos")
    os.makedirs(out_root, exist_ok=True)
    logo = make_logo(os.path.join(out_root, "logo.png"))

    wanted = [w.strip() for w in args.only.split(",") if w.strip()] or \
             ["transition", "panning", "graphics"]
    builders = {
        "transition": demo_transition,
        "panning": demo_panning,
        "graphics": lambda: demo_graphics(logo),
    }

    key = "set" if settings.pexels_api_key else "MISSING"
    print(f"Pexels API key: {key} -> stock footage "
          f"{'enabled' if settings.pexels_api_key else 'unavailable, falling back to gradients'}")

    rows = []
    for name in wanted:
        script, req = builders[name]()
        rows.append(await render(name, script, req, out_root, args.sheets))
        print(f"  {rows[-1]['name']}: {rows[-1]['duration']}s, {rows[-1]['size_mb']} MB, "
              f"visuals={rows[-1]['visuals']}")

    print("\n| clip | length | size | background |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| {r['name']} | {r['duration']}s | {r['size_mb']} MB | {r['visuals']} |")
    for r in rows:
        if r.get("sheet"):
            print("sheet:", os.path.relpath(r["sheet"]))

    off = [r for r in rows if abs(r["duration"] - TARGET) > 0.6]
    if off:
        raise SystemExit("FAIL: " + "; ".join(
            f"{r['name']} is {r['duration']}s, not {TARGET}s" for r in off))
    print(f"\nPASS: {len(rows)} clip(s) at {TARGET}s +/- 0.6s")


if __name__ == "__main__":
    asyncio.run(main())
