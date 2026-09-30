"""Graphic overlays: all four kinds, three ratios, one video each.

Each overlay is given a colour nothing else in the frame uses, so it can be found
again in the rendered pixels. That turns the two claims worth proving into
measurements rather than eyeballing:

  present    every kind actually reaches the screen
  consistent because positions are percentages, an overlay sits at the same
             RELATIVE spot in 9:16, 1:1 and 16:9 — so the centroid of its colour,
             expressed as a fraction of width/height, has to match across ratios
  timed      an overlay pinned to one scene appears in that scene and nowhere else

Usage (from backend/):
    .venv/bin/python verify_overlays.py
    .venv/bin/python verify_overlays.py --ratios 9:16 --sheets
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess

from PIL import Image

from app.config import get_settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    JobInfo,
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
from app.render import _probe_duration
from verify_render import contact_sheet


class FlatVisualProvider(VisualsProvider):
    """A plain mid-grey background — verification only.

    The shipped gradient provider picks a pleasant colour per scene, and one of
    those turned out to be an orange-brown close enough to a marker colour to be
    counted as an overlay, which failed the scene-timing check for a reason that
    had nothing to do with overlays. Backgrounds are not what this file tests, so
    it holds them flat and unsaturated and leaves the markers unmistakable.
    """

    name = "flat"

    async def get_visual(self, query: str, out_path: str, *, width: int, height: int,
                         existing_images: list[str] | None = None,
                         index: int = 0, tone: str = "") -> VisualAsset:
        Image.new("RGB", (width, height), (96, 96, 100)).save(out_path, "JPEG", quality=92)
        return VisualAsset(path=out_path, kind="image")

# Marker colours, one per overlay. Picked far apart and away from the caption
# palette (white text, red accent) so a match is unambiguous.
TEXT_C = (255, 0, 255)     # magenta
SHAPE_C = (0, 255, 0)      # green
LOGO_C = (0, 255, 255)     # cyan
STICKER_C = (255, 255, 0)  # yellow
SCENE_C = (255, 128, 0)    # orange — the scene-pinned one

TOL = 70          # per-channel slack: h264 chroma subsampling shifts pure colours
MIN_PIXELS = 40   # fewer than this and we have found noise, not a graphic
POS_TOL = 0.03    # centroid may differ by 3% of the frame between ratios


def rgb_frame(video: str, t: float, w: int, h: int) -> Image.Image:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
         "-vf", "format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout[: w * h * 3]
    return Image.frombytes("RGB", (w, h), raw)


def find_colour(img: Image.Image, target: tuple[int, int, int]) -> tuple[int, float, float]:
    """Pixel count and centroid (as fractions of the frame) for one marker colour."""
    w, h = img.size
    px = img.load()
    n, sx, sy = 0, 0, 0
    # every 2nd pixel: plenty for a centroid, four times less work
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if (abs(r - target[0]) <= TOL and abs(g - target[1]) <= TOL
                    and abs(b - target[2]) <= TOL):
                n += 1
                sx += x
                sy += y
    if n == 0:
        return 0, -1.0, -1.0
    return n, (sx / n) / w, (sy / n) / h


def build_overlays(logo_path: str) -> list[Overlay]:
    """One of every kind, plus a scene-pinned sticker to check timing."""
    return [
        Overlay(kind=OverlayKind.TEXT, text="50% OFF", x_pct=50, y_pct=15, size_pct=7,
                color="#FF00FF", background_box=True, box_color="#101010"),
        Overlay(kind=OverlayKind.SHAPE, shape=ShapeKind.CIRCLE, x_pct=28, y_pct=42,
                width_pct=26, height_pct=16, color="#00FF00", thickness_pct=1.2),
        Overlay(kind=OverlayKind.LOGO, logo_path=logo_path, x_pct=72, y_pct=42,
                size_pct=18),
        Overlay(kind=OverlayKind.STICKER, sticker=StickerPreset.SALE, x_pct=50,
                y_pct=85, size_pct=22, color="#FFFF00"),
        # only on the middle scene: proves scene pinning and that the window does
        # not leak into its neighbours
        Overlay(kind=OverlayKind.STICKER, sticker=StickerPreset.STAR, x_pct=80,
                y_pct=68, size_pct=14, color="#FF8000", scene_index=1),
    ]


def make_logo(path: str) -> str:
    """A plain cyan block: unmistakable in the frame, and it is a real PNG upload."""
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.new("RGBA", (600, 240), (*LOGO_C, 255)).save(path)
    return path


def make_script() -> Script:
    return Script(
        title="Overlay check",
        hook="One",
        scenes=[
            Scene(text="One", narration="One", visual_query="a", duration_sec=3.0),
            Scene(text="Two", narration="Two", visual_query="b", duration_sec=3.0),
            Scene(text="Three", narration="Three", visual_query="c", duration_sec=3.0),
        ],
        cta="Three",
    )


async def scene_windows(job_dir: str) -> list[tuple[float, float]]:
    """(start, end) of each scene on the finished timeline, measured not assumed."""
    out, acc = [], 0.0
    for name in sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f)):
        d = await _probe_duration(os.path.join(job_dir, name))
        out.append((acc, acc + d))
        acc += d
    return out


async def run_ratio(ratio: AspectRatio, out_root: str, sheet: bool) -> dict:
    settings = get_settings()
    settings.tts_provider = "silent"
    pipe = Pipeline(settings)
    pipe.registry.visuals = lambda: FlatVisualProvider()  # type: ignore[method-assign]
    tag = ratio.value.replace(":", "x")
    job_dir = os.path.join(out_root, tag)
    w, h = ratio.dimensions(base=1080)
    logo = make_logo(os.path.join(out_root, "logo.png"))
    req = TopicRequest(
        topic="Overlay check", tone=Tone.ENERGETIC, duration_sec=9,
        aspect_ratio=ratio, caption_style=CaptionStyle.POP,
        # cuts and no camera movement: overlay positions are then the only thing
        # that could move, so a mismatch can only be the overlays' fault
        transition=TransitionSettings(type=TransitionType.CUT, fade_in=False, fade_out=False),
        motion=MotionSettings(type=MotionType.NONE),
        overlays=build_overlays(logo),
    )
    final = await pipe.run(JobInfo(id=f"ov_{tag}", mode="topic"), req, job_dir,
                           script=make_script())
    windows = await scene_windows(job_dir)
    dur = await _probe_duration(final)

    # sample inside the middle scene: every overlay, including the pinned one, is up
    mid = (windows[1][0] + windows[1][1]) / 2
    img = rgb_frame(final, mid, w, h)
    found = {
        "text": find_colour(img, TEXT_C),
        "shape": find_colour(img, SHAPE_C),
        "logo": find_colour(img, LOGO_C),
        "sticker": find_colour(img, STICKER_C),
        "scene_pinned": find_colour(img, SCENE_C),
    }
    # and in the outer scenes, where only the pinned one should be gone
    first = rgb_frame(final, (windows[0][0] + windows[0][1]) / 2, w, h)
    last = rgb_frame(final, (windows[2][0] + windows[2][1]) / 2, w, h)
    pinned_elsewhere = max(find_colour(first, SCENE_C)[0], find_colour(last, SCENE_C)[0])
    always_on_first = find_colour(first, STICKER_C)[0]

    # Fade: the pinned overlay arrives at scene 1's start with a 0.3s ramp, so a
    # frame taken just as it appears is still mostly background and matches the
    # marker colour far less than a frame once it is fully up.
    s1 = windows[1][0]
    fade_early = find_colour(rgb_frame(final, s1 + 0.04, w, h), SCENE_C)[0]
    fade_full = find_colour(rgb_frame(final, s1 + 0.6, w, h), SCENE_C)[0]

    # And the always-on overlay must NOT fade again at that same boundary: it is
    # cued on every scene it crosses, so a per-scene fade would make it blink.
    boundary_always = find_colour(rgb_frame(final, s1 + 0.04, w, h), STICKER_C)[0]

    row = {
        "ratio": ratio.value, "size": f"{w}x{h}", "duration": round(dur, 3),
        "found": found, "pinned_elsewhere": pinned_elsewhere,
        "always_on_first": always_on_first,
        "fade_early": fade_early, "fade_full": fade_full,
        "boundary_always": boundary_always,
    }
    if sheet:
        row["sheet"] = os.path.relpath(contact_sheet(
            final, os.path.join(out_root, f"sheet_{tag}.jpg"),
            [windows[0][0] + 0.6, mid, windows[2][1] - 0.6], cols=3, width=300,
        ))
    return row


def sampler(out_root: str) -> list[str]:
    """Draw every kind and every sticker onto one sheet each.

    No video, no ffmpeg — this is the PIL layer on its own, which is the quickest
    way to see that all ten badges and all four shapes still draw correctly.
    """
    from app.graphics import render_overlay_png
    from app.render import _find_font

    font = _find_font()
    w, h = 540, 960

    def sheet(items: list[Overlay], name: str, cols: int) -> str:
        tiles = []
        for i, ov in enumerate(items):
            png = os.path.join(out_root, f"_sample_{i}.png")
            drawn = render_overlay_png(ov, w, h, png, font)
            # mid grey: both light and dark graphics stay visible against it
            bg = Image.new("RGB", (w, h), (90, 95, 110))
            if drawn:
                layer = Image.open(drawn)
                bg.paste(layer, (0, 0), layer)
            tiles.append(bg)
        rows = (len(tiles) + cols - 1) // cols
        tw, th = 270, 480
        out = Image.new("RGB", (tw * cols, th * rows), (20, 20, 24))
        for i, tile in enumerate(tiles):
            out.paste(tile.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
        path = os.path.join(out_root, name)
        out.save(path, "JPEG", quality=88)
        return path

    kinds = [
        Overlay(kind=OverlayKind.TEXT, text="50% OFF", x_pct=50, y_pct=20, size_pct=9),
        Overlay(kind=OverlayKind.TEXT, text="Limited time", x_pct=50, y_pct=50, size_pct=7,
                background_box=True, box_color="#7C5CFF"),
        Overlay(kind=OverlayKind.SHAPE, shape=ShapeKind.LABEL_BOX, x_pct=50, y_pct=40,
                width_pct=70, height_pct=20, color="#00E0FF"),
        Overlay(kind=OverlayKind.SHAPE, shape=ShapeKind.ARROW, x_pct=50, y_pct=50,
                width_pct=45, height_pct=12, color="#FFD400", rotation_deg=270),
        Overlay(kind=OverlayKind.SHAPE, shape=ShapeKind.CIRCLE, x_pct=50, y_pct=45,
                width_pct=50, color="#FF3B5C"),
        Overlay(kind=OverlayKind.SHAPE, shape=ShapeKind.HIGHLIGHT_BAR, x_pct=50, y_pct=70,
                width_pct=60, height_pct=5, color="#00E676", opacity=0.75),
    ]
    stickers = [
        Overlay(kind=OverlayKind.STICKER, sticker=p, x_pct=50, y_pct=50, size_pct=34,
                color="#FF3B5C")
        for p in StickerPreset
    ]
    return [sheet(kinds, "sheet_kinds.jpg", 6), sheet(stickers, "sheet_stickers.jpg", 5)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratios", default="9:16,1:1,16:9")
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--sampler", action="store_true",
                    help="draw every kind and sticker to a sheet, without rendering video")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    if args.sampler:
        root = args.out_dir or os.path.join(get_settings().output_dir, "verify_overlays")
        os.makedirs(root, exist_ok=True)
        for p in sampler(root):
            print("sampler:", os.path.relpath(p))
        return

    out_root = args.out_dir or os.path.join(get_settings().output_dir, "verify_overlays")
    os.makedirs(out_root, exist_ok=True)
    ratios = [AspectRatio(r.strip()) for r in args.ratios.split(",") if r.strip()]

    rows = []
    for ratio in ratios:
        rows.append(await run_ratio(ratio, out_root, args.sheets))
        print(f"  {ratio.value} rendered")

    kinds = ["text", "shape", "logo", "sticker", "scene_pinned"]
    print("\n| overlay | " + " | ".join(r["ratio"] for r in rows) + " | position spread |")
    print("|---" * (len(rows) + 2) + "|")
    problems = []
    for kind in kinds:
        cells, xs, ys = [], [], []
        for r in rows:
            n, cx, cy = r["found"][kind]
            if n < MIN_PIXELS:
                cells.append("**MISSING**")
                problems.append(f"{kind} not visible in {r['ratio']} ({n} px)")
            else:
                cells.append(f"{n} px @ {cx * 100:.1f}%, {cy * 100:.1f}%")
                xs.append(cx)
                ys.append(cy)
        spread = "-"
        if len(xs) > 1:
            dx, dy = max(xs) - min(xs), max(ys) - min(ys)
            spread = f"x {dx * 100:.1f}%, y {dy * 100:.1f}%"
            if dx > POS_TOL or dy > POS_TOL:
                problems.append(
                    f"{kind} moves between ratios: x spread {dx * 100:.1f}%, "
                    f"y spread {dy * 100:.1f}% (limit {POS_TOL * 100:.0f}%)")
        print(f"| {kind} | " + " | ".join(cells) + f" | {spread} |")

    print("\n| ratio | size | length | pinned sticker outside its scene | always-on sticker in scene 1 |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['ratio']} | {r['size']} | {r['duration']}s | {r['pinned_elsewhere']} px "
              f"| {r['always_on_first']} px |")
        if r["pinned_elsewhere"] >= MIN_PIXELS:
            problems.append(
                f"{r['ratio']}: scene-pinned overlay leaked outside its scene "
                f"({r['pinned_elsewhere']} px)")
        if r["always_on_first"] < MIN_PIXELS:
            problems.append(f"{r['ratio']}: whole-video overlay missing from scene 1")
    print("\n| ratio | arriving graphic: 0.04s in | fully up at 0.6s "
          "| whole-video graphic across the same boundary |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| {r['ratio']} | {r['fade_early']} px | {r['fade_full']} px "
              f"| {r['boundary_always']} px |")
        if r["fade_early"] >= r["fade_full"] * 0.5:
            problems.append(
                f"{r['ratio']}: graphic did not fade in — {r['fade_early']} px at 0.04s "
                f"vs {r['fade_full']} px once up")
        if r["boundary_always"] < MIN_PIXELS:
            problems.append(
                f"{r['ratio']}: whole-video graphic blinked at a scene boundary "
                f"({r['boundary_always']} px)")

    for r in rows:
        if r.get("sheet"):
            print("sheet:", r["sheet"])

    if problems:
        raise SystemExit("FAIL: " + "; ".join(problems))
    print(f"\nPASS: 4 overlay kinds + scene pinning across {len(rows)} ratio(s) — "
          f"all visible, positions within {POS_TOL * 100:.0f}% of each other, timing respected")


if __name__ == "__main__":
    asyncio.run(main())
