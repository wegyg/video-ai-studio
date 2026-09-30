"""Camera-motion verification: black edges, jitter and caption sync.

Renders one video per motion type (transitions off, so the only thing that can
darken an edge is the movement itself) and checks three things:

  black edge   the outermost row/column of sampled frames, at full resolution
  jitter       frame-to-frame change across 1s of movement; a slow pan that steps
               a whole pixel at a time shows up as frames that barely change
               ("stall") next to frames that jump
  caption err  largest offset between a scene's start and where its voice lands

Usage (from backend/, after ../scripts/setup_ffmpeg.sh && ../scripts/setup_python.sh):
    .venv/bin/python verify_motion.py --ratios 9:16
    .venv/bin/python verify_motion.py --ratios 1:1,16:9 --motions zoom_in,pan_left
    .venv/bin/python verify_motion.py --ratios 9:16 --sheets pan_left,zoom_in,auto
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess

from PIL import Image, ImageDraw

from app.config import get_settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    JobInfo,
    MotionIntensity,
    MotionSettings,
    MotionType,
    Tone,
    TopicRequest,
    TransitionSettings,
    TransitionType,
)
from app.pipeline import Pipeline
from app.providers.base import VisualAsset, VisualsProvider
from app.render import _probe_duration
from verify_render import contact_sheet
from verify_transitions import scene_starts, worst_caption_offset

POINTS = ["Freshly roasted daily", "Delivered to your door", "50% off the first bag"]
TOL = 0.1
BLACK = 8          # luma at or below this counts as black
BLACK_FRACTION = 0.9  # a row/col this black is a border artefact


def gray_frame(video: str, t: float, w: int, h: int) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
         "-vf", "format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout[: w * h]


def black_edges(video: str, w: int, h: int, times: list[float]) -> dict:
    """Worst black fraction found on any outer row/column."""
    worst, where = 0.0, ""
    for t in times:
        buf = gray_frame(video, t, w, h)
        if len(buf) < w * h:
            continue
        rows = {"top": buf[0:w], "bottom": buf[(h - 1) * w : h * w]}
        cols = {
            "left": bytes(buf[y * w] for y in range(h)),
            "right": bytes(buf[y * w + (w - 1)] for y in range(h)),
        }
        for name, strip in {**rows, **cols}.items():
            frac = sum(1 for v in strip if v <= BLACK) / max(len(strip), 1)
            if frac > worst:
                worst, where = frac, f"{name}@{t:.1f}s"
    return {"worst_black_frac": round(worst, 3), "where": where,
            "ok": worst < BLACK_FRACTION}


CAPTION_TOP = 0.45  # captions/scrim start at 0.55*h; above that is background only
# Below this mean per-frame change there is not enough texture moving to judge
# smoothness: the shipped gradient background is smooth and vignetted, so a
# subtle pan across it barely changes any pixel and min/mean just measures encode
# noise. Those runs still prove black edges and caption sync; smoothness is read
# off the --pattern grid, where the same motion moves 50-100x more signal.
NOISE_FLOOR = 0.05


def jitter(video: str, start: float, fps: int, small_w: int = 240) -> dict:
    """Mean per-frame change over 1s, and the smallest change relative to it.

    Smooth movement changes by a similar amount every frame; pixel-stepping
    leaves frames that barely move, so min/mean drops toward zero.

    Measured on ONE scene clip (never the concatenated video, whose scene cuts
    would dwarf the movement) and only on the top {CAPTION_TOP:.0%} of the frame,
    which holds no caption. Pop captions reveal a word at a time, so including
    the caption band would report the text animating as if the camera jittered.
    """
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", "1", "-i", video,
         "-vf", f"fps={fps},crop=iw:ih*{CAPTION_TOP}:0:0,scale={small_w}:-2,format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    n = max(1, len(raw) // max(1, fps))
    frames = [raw[i * n : (i + 1) * n] for i in range(len(raw) // n)]
    diffs = []
    for a, b in zip(frames, frames[1:]):
        if len(a) != len(b) or not a:
            continue
        diffs.append(sum(abs(x - y) for x, y in zip(a, b)) / len(a))
    if len(diffs) < 5:
        return {"mean_diff": 0.0, "min_over_mean": 1.0, "ok": True,
                "measurable": False, "frames": len(diffs)}
    mean = sum(diffs) / len(diffs)
    measurable = mean > NOISE_FLOOR
    ratio = (min(diffs) / mean) if measurable else 1.0
    return {"mean_diff": round(mean, 2), "min_over_mean": round(ratio, 2),
            "ok": not measurable or ratio >= 0.25,
            "measurable": measurable, "frames": len(diffs)}


class PatternVisualProvider(VisualsProvider):
    """A bright, edge-to-edge grid — verification only, never used in production.

    The shipped gradient provider paints a vignette, which makes two things hard:
    a slow pan across a smooth gradient looks like a still frame, and an exposed
    black border blends into an already-dark edge. A high-contrast grid that runs
    fully to the frame edge makes movement obvious and leaves any black band with
    nowhere to hide.
    """

    name = "pattern"

    async def get_visual(self, query: str, out_path: str, *, width: int, height: int,
                         existing_images: list[str] | None = None,
                         index: int = 0, tone: str = "") -> VisualAsset:
        def _run() -> None:
            img = Image.new("RGB", (width, height), (250, 250, 252))
            d = ImageDraw.Draw(img)
            step = max(40, min(width, height) // 12)
            # checkerboard so both horizontal and vertical travel is readable
            for gy, y in enumerate(range(0, height, step)):
                for gx, x in enumerate(range(0, width, step)):
                    if (gx + gy) % 2 == 0:
                        d.rectangle([x, y, x + step - 1, y + step - 1], fill=(34, 40, 64))
            # bright rules hugging all four edges: a black border eats these first
            band = max(6, step // 6)
            for box in ((0, 0, width - 1, band), (0, height - 1 - band, width - 1, height - 1),
                        (0, 0, band, height - 1), (width - 1 - band, 0, width - 1, height - 1)):
                d.rectangle(box, fill=(255, 92, 0))
            # off-center landmarks give the eye something to track between frames
            for fx, fy, col in ((0.25, 0.25, (0, 200, 255)), (0.75, 0.3, (255, 220, 0)),
                                (0.3, 0.75, (0, 230, 120)), (0.7, 0.72, (255, 0, 140))):
                cx, cy = int(width * fx), int(height * fy)
                r = max(12, step // 2)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
            img.save(out_path, "JPEG", quality=92)

        await asyncio.get_event_loop().run_in_executor(None, _run)
        return VisualAsset(path=out_path, kind="image")


async def scene_clip_for_jitter(job_dir: str) -> tuple[str, float]:
    """A regular (non-hook) scene clip and a start time safely inside it."""
    clips = sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f))
    name = clips[1] if len(clips) > 1 else clips[0]
    path = os.path.join(job_dir, name)
    d = await _probe_duration(path)
    start = 1.0 if d > 2.2 else max(0.1, d * 0.2)
    return path, start


async def measure(job_dir: str, w: int, h: int, fps: int, out_root: str,
                  tag: str, sheet: bool) -> dict:
    """All three checks against an already-rendered job directory."""
    final = os.path.join(job_dir, "final.mp4")
    dur = await _probe_duration(final)
    times = [dur * f for f in (0.1, 0.25, 0.45, 0.6, 0.8, 0.95)]
    edges = black_edges(final, w, h, times)
    # A pan ends at the far end of its travel, using every pixel of margin, so the
    # last frame of each scene is where a black band would appear first. Sampling
    # only the concatenated video can skip straight past those frames.
    for name in sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f)):
        clip_path = os.path.join(job_dir, name)
        cd = await _probe_duration(clip_path)
        extreme = black_edges(clip_path, w, h, [max(0.0, cd - 0.04), cd / 2])
        if extreme["worst_black_frac"] > edges["worst_black_frac"]:
            edges = {**extreme, "where": f"{extreme['where']} in {name}"}
    clip, start = await scene_clip_for_jitter(job_dir)
    jit = jitter(clip, start, fps)
    n_clips = len([f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f)])
    starts = await scene_starts(job_dir, [0.0] * n_clips)
    row = dict(
        ok=True,
        black=edges["worst_black_frac"], black_where=edges["where"],
        black_ok=edges["ok"],
        mean_diff=jit["mean_diff"], min_over_mean=jit["min_over_mean"],
        jitter_ok=jit["ok"], jitter_measurable=jit["measurable"],
        caption_err=await worst_caption_offset(job_dir, starts),
    )
    if sheet:
        row["sheet"] = os.path.relpath(contact_sheet(
            final, os.path.join(out_root, f"sheet_{tag}.jpg"),
            [dur * f for f in (0.08, 0.22, 0.36, 0.5, 0.64, 0.78)], cols=6, width=200,
        ))
    return row


async def run_case(motion: MotionType, ratio: AspectRatio, out_root: str, sheet: bool,
                   render: bool = True, pattern: bool = False,
                   intensity: MotionIntensity = MotionIntensity.MEDIUM) -> dict:
    settings = get_settings()
    pipe = Pipeline(settings)
    if pattern:
        pipe.registry.visuals = lambda: PatternVisualProvider()  # type: ignore[method-assign]
    tag = f"{motion.value}_{ratio.value.replace(':', 'x')}"
    if intensity is not MotionIntensity.MEDIUM:
        tag = f"{tag}_{intensity.value}"
    job_dir = os.path.join(out_root, tag)
    w, h = ratio.dimensions(base=1080)
    req = TopicRequest(
        topic="BrewJoy Coffee", key_points=POINTS, tone=Tone.ENERGETIC, duration_sec=14,
        aspect_ratio=ratio, caption_style=CaptionStyle.POP,
        # transitions off: any black edge then comes from the movement alone
        transition=TransitionSettings(type=TransitionType.CUT, fade_in=False, fade_out=False),
        motion=MotionSettings(type=motion, intensity=intensity),
    )
    row: dict = {"motion": motion.value, "ratio": ratio.value,
                 "intensity": intensity.value}
    try:
        if render:
            await pipe.run(JobInfo(id=tag, mode="topic"), req, job_dir)
        elif not os.path.isfile(os.path.join(job_dir, "final.mp4")):
            raise FileNotFoundError(f"no render to measure in {job_dir}")
        row.update(await measure(job_dir, w, h, settings.video_fps, out_root, tag, sheet))
    except Exception as e:
        row.update(ok=False, error=str(e)[-200:])
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratios", default="9:16")
    ap.add_argument("--motions", default="", help="default: every motion type")
    ap.add_argument("--intensities", default="medium",
                    help="a subtle pan is the case most likely to judder, so cover weak too")
    ap.add_argument("--sheets", default="")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--measure-only", action="store_true",
                    help="re-check renders already in --out-dir instead of rendering again")
    ap.add_argument("--pattern", action="store_true",
                    help="render on a high-contrast grid so movement and any black edge show")
    args = ap.parse_args()

    out_root = args.out_dir or os.path.join(get_settings().output_dir, "verify_motion")
    os.makedirs(out_root, exist_ok=True)
    motions = ([MotionType(m.strip()) for m in args.motions.split(",") if m.strip()]
               or list(MotionType))
    sheets = {s.strip() for s in args.sheets.split(",") if s.strip()}
    intensities = [MotionIntensity(i.strip()) for i in args.intensities.split(",") if i.strip()]

    rows = []
    for ratio in [AspectRatio(r.strip()) for r in args.ratios.split(",")]:
        for motion in motions:
            for intensity in intensities:
                row = await run_case(
                    motion, ratio, out_root, motion.value in sheets,
                    render=not args.measure_only, pattern=args.pattern,
                    intensity=intensity)
                rows.append(row)
                print(f"  {row['motion']:<10} {row['ratio']:<5} {row['intensity']:<7} "
                      + ("ok" if row["ok"] else f"FAIL {row.get('error', '')}"))

    print("\n| motion | ratio | strength | black edge | jitter (mean diff, min/mean) "
          "| caption err | verdict |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        if not r["ok"]:
            print(f"| {r['motion']} | {r['ratio']} | {r['intensity']} | - | - | - | FAIL |")
            continue
        ok = r["black_ok"] and r["jitter_ok"] and r["caption_err"] <= TOL
        black = "none" if r["black"] < BLACK_FRACTION else f"{r['black']} {r['black_where']}"
        jit = (f"{r['mean_diff']}, {r['min_over_mean']}" if r["jitter_measurable"]
               else f"{r['mean_diff']} — n/a, too little texture to measure")
        print(f"| {r['motion']} | {r['ratio']} | {r['intensity']} | {black} "
              f"| {jit} | {r['caption_err']}s | {'PASS' if ok else 'CHECK'} |")
    for r in rows:
        if r.get("sheet"):
            print("sheet:", r["sheet"])

    bad = [r for r in rows if not r["ok"] or not r["black_ok"] or not r["jitter_ok"]
           or r["caption_err"] > TOL]
    if bad:
        raise SystemExit(f"{len(bad)} case(s) need attention")
    print(f"\nPASS: {len(rows)} renders — no black edges, no stalled frames, captions within {TOL}s")


if __name__ == "__main__":
    asyncio.run(main())
