"""Narration-sync verification: does each scene's voice start with its captions?

Renders a 5-scene promo once, then builds the narration track BOTH ways from the
same per-scene audio files and measures each scene's speech onset:

  legacy  = concat_audio()    — segments glued back-to-back (old behaviour)
  placed  = build_narration() — each segment laid at its scene's start time

Scene starts come from the rendered clips themselves, so frame quantisation is
included. Per scene we compare where the voice *should* start
(scene start + the segment's own leading silence) with where it actually starts
in the track, measured with ffmpeg's silencedetect.

Usage (from backend/, after ../scripts/setup_ffmpeg.sh && ../scripts/setup_python.sh):
    .venv/bin/python verify_sync.py
"""

from __future__ import annotations

import asyncio
import os
import array
import math
import re
import subprocess

from app.config import get_settings
from app.models import AspectRatio, CaptionStyle, JobInfo, Tone, TopicRequest
from app.pipeline import Pipeline
from app.render import Renderer, _probe_duration

TOL = 0.1  # completion criterion: every scene within 0.1s
SR = 8000  # analysis sample rate
HOP = 0.01  # envelope frame = 10ms


def envelope(path: str) -> list[float]:
    """RMS envelope (one value per 10ms) of a file, via a mono 8kHz decode.

    Thresholded silence detection is too sensitive to the noise floor for a
    0.1s verdict, so placement is measured by correlating waveform energy.
    """
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    pcm = array.array("h")
    pcm.frombytes(raw[: len(raw) - (len(raw) % 2)])
    step = int(SR * HOP)
    env: list[float] = []
    for i in range(0, len(pcm) - step, step):
        acc = 0
        for v in pcm[i : i + step]:
            acc += v * v
        env.append(math.sqrt(acc / step) / 32768.0)
    return env


def find_lag(seg: list[float], track: list[float], expect_frame: int, window_frames: int) -> float | None:
    """Offset (seconds) of the segment inside the track, searched around expect_frame.

    Positive = the voice starts later than the captions.
    """
    use = min(len(seg), int(2.0 / HOP))  # first 2s of the segment is plenty
    if use < 10:
        return None
    seg_part = seg[:use]
    seg_energy = math.sqrt(sum(v * v for v in seg_part)) or 1e-9
    best, best_score = None, -1.0
    for lag in range(-window_frames, window_frames + 1):
        start = expect_frame + lag
        if start < 0 or start + use > len(track):
            continue
        win = track[start : start + use]
        dot = sum(a * b for a, b in zip(seg_part, win))
        win_energy = math.sqrt(sum(v * v for v in win)) or 1e-9
        score = dot / (seg_energy * win_energy)
        if score > best_score:
            best_score, best = score, lag
    return None if best is None else round(best * HOP, 3)


async def main() -> None:
    settings = get_settings()
    pipe = Pipeline(settings)
    req = TopicRequest(
        topic="BrewJoy Coffee",
        key_points=["Freshly roasted daily", "Delivered to your door",
                    "50% off the first bag", "Cancel anytime"],
        tone=Tone.ENERGETIC, duration_sec=20,
        aspect_ratio=AspectRatio.VERTICAL, caption_style=CaptionStyle.POP,
    )
    job_dir = os.path.join(settings.output_dir, "verify_sync")
    job = JobInfo(id="verify_sync", mode="topic")
    final = await pipe.run(job, req, job_dir)
    print(f"rendered {final}  ({len(os.listdir(job_dir))} files)")

    clips = sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"clip_\d+\.mp4", f))
    segs = sorted(f for f in os.listdir(job_dir) if re.fullmatch(r"scene_\d+\.m4a", f))
    n = min(len(clips), len(segs))
    assert n >= 5, f"expected 5+ scenes, got {n}"

    # Scene starts on the finished timeline, from the rendered clips.
    starts: list[float] = []
    acc = 0.0
    for c in clips[:n]:
        starts.append(acc)
        acc += await _probe_duration(os.path.join(job_dir, c))

    seg_paths = [os.path.join(job_dir, s) for s in segs[:n]]

    # Build the legacy track from the very same segments for a fair comparison.
    r = Renderer(1080, 1920, settings.video_fps)
    legacy = os.path.join(job_dir, "narration_legacy.m4a")
    await r.concat_audio(seg_paths, legacy)
    placed = os.path.join(job_dir, "narration.m4a")  # produced by the pipeline

    env_legacy = envelope(legacy)
    env_placed = envelope(placed)
    window = int(6.0 / HOP)  # search +-6s: legacy drift gets large

    rows = []
    for i in range(n):
        seg_env = envelope(seg_paths[i])
        frame = int(starts[i] / HOP)
        rows.append({
            "scene": i + 1,
            "caption_start": round(starts[i], 3),
            "legacy": find_lag(seg_env, env_legacy, frame, window),
            "placed": find_lag(seg_env, env_placed, frame, window),
        })

    print("\n| scene | caption start | legacy voice offset | placed voice offset |")
    print("|---|---|---|---|")
    for x in rows:
        f = lambda v: "not found" if v is None else f"{v:+.3f}s"  # noqa: E731
        print(f"| {x['scene']} | {x['caption_start']}s | {f(x['legacy'])} | {f(x['placed'])} |")

    vdur = await _probe_duration(os.path.join(job_dir, "video_silent.mp4"))
    adur = await _probe_duration(placed)
    ldur = await _probe_duration(legacy)
    print(f"\nvideo {vdur:.3f}s | placed narration {adur:.3f}s (diff {abs(vdur-adur):.3f}s)"
          f" | legacy narration {ldur:.3f}s (diff {abs(vdur-ldur):.3f}s)")

    val = lambda v: float("inf") if v is None else abs(v)  # noqa: E731
    worst_p = max(val(x["placed"]) for x in rows)
    worst_l = max(val(x["legacy"]) for x in rows)
    show = lambda v: "beyond the search window" if v == float("inf") else f"{v:.3f}s"  # noqa: E731
    print(f"worst drift — legacy {show(worst_l)}, placed {show(worst_p)} (limit {TOL}s)")
    if worst_p > TOL:
        raise SystemExit(f"FAIL: placed narration drifts up to {worst_p}s")
    print("PASS: every scene's voice lands within 0.1s of its captions")


if __name__ == "__main__":
    asyncio.run(main())
