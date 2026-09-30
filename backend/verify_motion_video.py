"""Camera motion on VIDEO backgrounds (uploaded footage / Pexels clips).

Stills and footage take different branches inside `_motion_chain` — a still is
moved with `zoompan`, footage with a `crop` window that slides across an enlarged
frame, because `zoompan` would restart on every input frame. So passing the stills
matrix says nothing about footage; this covers the other branch.

Checks, per motion:
  black edge   no exposed border while the crop window travels
  intensity    footage is capped to the lightest strength even when the project
               asks for strong, since the footage is already moving
  length       the scene still occupies exactly its own duration

Runs offline: the source clip is synthesised with ffmpeg rather than fetched, and
is deliberately high-contrast and edge-to-edge so a black band cannot hide.
"""

from __future__ import annotations

import asyncio
import os
import subprocess

from app.config import get_settings
from app.models import (
    AspectRatio,
    JobInfo,
    MotionIntensity,
    MotionSettings,
    MotionType,
    Scene,
    Script,
    Tone,
    TopicRequest,
    TransitionSettings,
    TransitionType,
)
from app.pipeline import Pipeline
from app.providers.visual_providers import UserVideoProvider
from app.render import VIDEO_MAX_INTENSITY, Renderer, SceneClip
from app.render import _probe_duration
from verify_motion import black_edges


def make_source_clip(path: str) -> str:
    """A moving, high-contrast clip: colour bars under a drifting grid."""
    if not os.path.isfile(path):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=1920x1920:rate=30:duration=6",
             "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", path],
            check=True,
        )
    return path


def make_script(motion: MotionType) -> Script:
    return Script(
        title="Video motion check",
        hook="One",
        scenes=[
            Scene(text="One", narration="One", visual_query="footage", duration_sec=3.0,
                  motion=motion),
            Scene(text="Two", narration="Two", visual_query="footage", duration_sec=3.0,
                  motion=motion),
        ],
        cta="Two",
    )


def intensity_is_capped() -> tuple[bool, str]:
    """Footage must ignore a strong request and fall back to the light setting."""
    r = Renderer(width=1080, height=1920, fps=30)
    strong_video = r._motion_chain(
        SceneClip(image_path="x", caption="c", duration=3.0, kind="video",
                  motion="pan_left", motion_intensity="strong"), total=3.0, frames=90)
    weak_video = r._motion_chain(
        SceneClip(image_path="x", caption="c", duration=3.0, kind="video",
                  motion="pan_left", motion_intensity="weak"), total=3.0, frames=90)
    strong_still = r._motion_chain(
        SceneClip(image_path="x", caption="c", duration=3.0, kind="image",
                  motion="pan_left", motion_intensity="strong"), total=3.0, frames=90)
    weak_still = r._motion_chain(
        SceneClip(image_path="x", caption="c", duration=3.0, kind="image",
                  motion="pan_left", motion_intensity="weak"), total=3.0, frames=90)
    capped = strong_video == weak_video
    # Sanity: the cap has to be a real restriction. If intensity were ignored
    # everywhere, `capped` would be trivially true — so require that strength
    # still changes the chain on the stills branch, which is not capped.
    honoured = strong_still != weak_still
    return capped and honoured, (
        f"video strong == video {VIDEO_MAX_INTENSITY}: {capped}; "
        f"strength still changes a still: {honoured}"
    )


async def main() -> None:
    settings = get_settings()
    settings.tts_provider = "silent"
    src = make_source_clip(os.path.join(settings.output_dir, "motion_src.mp4"))

    ratio = AspectRatio.VERTICAL
    w, h = ratio.dimensions(base=1080)
    rows = []
    for motion in (MotionType.PAN_LEFT, MotionType.PAN_DOWN, MotionType.ZOOM_IN):
        pipe = Pipeline(settings)
        pipe.registry.visuals = lambda: UserVideoProvider([src])  # type: ignore[method-assign]
        job_dir = os.path.join(settings.output_dir, "verify_motion_video", motion.value)
        req = TopicRequest(
            topic="Video motion check", tone=Tone.ENERGETIC, duration_sec=6,
            aspect_ratio=ratio,
            transition=TransitionSettings(type=TransitionType.CUT, fade_in=False, fade_out=False),
            # ask for the heaviest movement: footage must quietly cap it
            motion=MotionSettings(type=motion, intensity=MotionIntensity.STRONG),
        )
        final = await pipe.run(JobInfo(id=f"vm_{motion.value}", mode="topic"), req, job_dir,
                               script=make_script(motion))
        dur = await _probe_duration(final)
        kinds = [f for f in os.listdir(job_dir) if f.endswith(".uclip.mp4")]
        edges = black_edges(final, w, h, [dur * f for f in (0.1, 0.3, 0.49, 0.7, 0.9, 0.99)])
        for name in sorted(f for f in os.listdir(job_dir) if f.startswith("clip_")):
            cd = await _probe_duration(os.path.join(job_dir, name))
            e = black_edges(os.path.join(job_dir, name), w, h, [max(0.0, cd - 0.04)])
            if e["worst_black_frac"] > edges["worst_black_frac"]:
                edges = e
        rows.append((motion.value, len(kinds), dur, edges))

    capped, detail = intensity_is_capped()

    print("\n| motion | footage clips used | length (expected 6.0s) | black edge |")
    print("|---|---|---|---|")
    for name, n, dur, e in rows:
        black = "none" if e["ok"] else f"{e['worst_black_frac']} {e['where']}"
        print(f"| {name} | {n} | {dur:.3f}s | {black} |")
    print(f"\nintensity cap on footage: {detail}")

    problems = []
    for name, n, dur, e in rows:
        if n == 0:
            problems.append(f"{name}: fell back to a still, footage branch never ran")
        if not e["ok"]:
            problems.append(f"{name}: black edge {e['worst_black_frac']} at {e['where']}")
        if abs(dur - 6.0) > 0.15:
            problems.append(f"{name}: length {dur:.3f}s != 6.0s")
    if not capped:
        problems.append(f"footage intensity not capped ({detail})")
    if problems:
        raise SystemExit("FAIL: " + "; ".join(problems))
    print(f"\nPASS: {len(rows)} footage renders — motion applied, no black edges, "
          f"strength capped to '{VIDEO_MAX_INTENSITY}', lengths exact")


if __name__ == "__main__":
    asyncio.run(main())
