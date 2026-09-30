"""Transition verification: every transition type against every aspect ratio.

For each render it reports whether it succeeded, the video/audio lengths and
their difference, and the worst caption-vs-narration offset (the risk with
xfade is that overlapping scenes shift the voice). Contact sheets around the
first scene boundary are written for the transitions named with --sheets.

Usage (from backend/, after ../scripts/setup_ffmpeg.sh && ../scripts/setup_python.sh):
    .venv/bin/python verify_transitions.py --ratios 9:16 --sheets crossfade,fade,slide_left
    .venv/bin/python verify_transitions.py --ratios 1:1,16:9
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re

from app.config import get_settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    JobInfo,
    Tone,
    TopicRequest,
    TransitionSettings,
    TransitionType,
)
from app.pipeline import Pipeline
from app.render import _probe_duration
from verify_render import contact_sheet, media_info
from verify_sync import envelope, find_lag, HOP

POINTS = ["Freshly roasted daily", "Delivered to your door", "50% off the first bag"]
TOL = 0.1


async def scene_starts(job_dir: str, pads: list[float]) -> list[float]:
    clips = sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f))
    starts, acc = [], 0.0
    for i, c in enumerate(clips):
        starts.append(acc)
        acc += await _probe_duration(os.path.join(job_dir, c)) - (pads[i] if i < len(pads) else 0.0)
    return starts


async def worst_caption_offset(job_dir: str, starts: list[float]) -> float:
    """Largest |offset| between a scene's start and where its voice lands."""
    narration = os.path.join(job_dir, "narration.m4a")
    if not os.path.exists(narration):
        return 99.0
    track = envelope(narration)
    worst = 0.0
    segs = sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"scene_\d+\.m4a", f))
    for i, seg in enumerate(segs[: len(starts)]):
        lag = find_lag(envelope(os.path.join(job_dir, seg)), track, int(starts[i] / HOP), int(1.5 / HOP))
        worst = max(worst, 99.0 if lag is None else abs(lag))
    return round(worst, 3)


async def run_case(kind: TransitionType, ratio: AspectRatio, out_root: str, sheet: bool) -> dict:
    settings = get_settings()
    # Pin the background provider: with a PEXELS_API_KEY present the registry
    # would hand back real footage, and every measurement here assumes the
    # offline gradient. Results have to be reproducible with or without a key.
    settings.visuals_provider = "gradient"
    pipe = Pipeline(settings)
    tag = f"{kind.value}_{ratio.value.replace(':', 'x')}"
    job_dir = os.path.join(out_root, tag)
    req = TopicRequest(
        topic="BrewJoy Coffee", key_points=POINTS, tone=Tone.ENERGETIC, duration_sec=14,
        aspect_ratio=ratio, caption_style=CaptionStyle.POP,
        transition=TransitionSettings(type=kind, duration_sec=0.5, fade_in=True, fade_out=True),
    )
    row: dict = {"transition": kind.value, "ratio": ratio.value}
    try:
        final = await pipe.run(JobInfo(id=tag, mode="topic"), req, job_dir)
        info = media_info(final)
        # every boundary pads by the transition duration (0.5s, frame-quantised)
        pad = 0.0 if kind is TransitionType.CUT else 0.5
        n_clips = len([f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f)])
        pads = [pad] * (n_clips - 1) + [0.0]
        starts = await scene_starts(job_dir, pads)
        row.update(
            ok=True,
            size=f"{info['w']}x{info['h']}",
            video=info["video_sec"],
            audio=info["audio_sec"],
            diff=info["diff_sec"],
            caption_err=await worst_caption_offset(job_dir, starts),
            boundary=round(starts[1], 3) if len(starts) > 1 else 0.0,
        )
        if sheet:
            b = row["boundary"]
            row["sheet"] = os.path.relpath(contact_sheet(
                final, os.path.join(out_root, f"sheet_{tag}.jpg"),
                [b - 0.30, b - 0.15, b - 0.05, b + 0.05, b + 0.15, b + 0.30], cols=6, width=200,
            ))
    except Exception as e:  # keep going so one failure doesn't hide the rest
        row.update(ok=False, error=str(e)[-200:])
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratios", default="9:16,1:1,16:9")
    ap.add_argument("--sheets", default="", help="transition types to contact-sheet")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_root = args.out_dir or os.path.join(get_settings().output_dir, "verify_transitions")
    os.makedirs(out_root, exist_ok=True)
    sheets = {s.strip() for s in args.sheets.split(",") if s.strip()}

    rows = []
    for ratio in [AspectRatio(r.strip()) for r in args.ratios.split(",")]:
        for kind in TransitionType:
            row = await run_case(kind, ratio, out_root, kind.value in sheets)
            rows.append(row)
            print(f"  {row['transition']:<11} {row['ratio']:<5} "
                  + ("ok" if row["ok"] else f"FAIL {row.get('error', '')}"))

    print("\n| transition | ratio | render | size | video | audio | diff | caption err |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["ok"]:
            verdict = "PASS" if r["diff"] <= TOL and r["caption_err"] <= TOL else "CHECK"
            print(f"| {r['transition']} | {r['ratio']} | {verdict} | {r['size']} | {r['video']}s "
                  f"| {r['audio']}s | {r['diff']}s | {r['caption_err']}s |")
        else:
            print(f"| {r['transition']} | {r['ratio']} | FAIL | - | - | - | - | - |")
    for r in rows:
        if r.get("sheet"):
            print("sheet:", r["sheet"])

    bad = [r for r in rows if not r["ok"] or r["diff"] > TOL or r["caption_err"] > TOL]
    if bad:
        raise SystemExit(f"{len(bad)} case(s) need attention")
    print(f"\nPASS: {len(rows)} renders, length diff and caption offset within {TOL}s")


if __name__ == "__main__":
    asyncio.run(main())
