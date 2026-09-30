"""Per-scene camera-motion override, and that "none" is still a dead-still frame.

One render of a 3-scene script whose project default is `none`:

  scene 0  overrides with pan_left, strong
  scene 1  overrides with pan_left, weak
  scene 2  no override -> inherits the project default (none)

Each scene is measured on its own clip, so the expectations are unambiguous:
scenes 0 and 1 must move, scene 2 must not move at all, and the strong scene
must move measurably more than the weak one — which is what proves the
per-scene INTENSITY override is honoured too, not just the direction.

Rendered on the verification grid from verify_motion, because movement across a
smooth gradient is too small to measure reliably.
"""

from __future__ import annotations

import asyncio
import os

from app.config import get_settings
from app.models import (
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
from app.render import _probe_duration
from verify_motion import PatternVisualProvider, jitter


def make_script() -> Script:
    return Script(
        title="Motion override check",
        hook="One",
        scenes=[
            Scene(text="One", narration="One", visual_query="grid", duration_sec=3.0,
                  motion=MotionType.PAN_LEFT, motion_intensity=MotionIntensity.STRONG),
            Scene(text="Two", narration="Two", visual_query="grid", duration_sec=3.0,
                  motion=MotionType.PAN_LEFT, motion_intensity=MotionIntensity.WEAK),
            Scene(text="Three", narration="Three", visual_query="grid", duration_sec=3.0),
        ],
        cta="Three",
    )


async def main() -> None:
    settings = get_settings()
    settings.tts_provider = "silent"
    pipe = Pipeline(settings)
    pipe.registry.visuals = lambda: PatternVisualProvider()  # type: ignore[method-assign]

    job_dir = os.path.join(settings.output_dir, "verify_motion_override")
    req = TopicRequest(
        topic="Motion override check", tone=Tone.ENERGETIC, duration_sec=9,
        # transitions off so each clip holds only its own scene's movement
        transition=TransitionSettings(type=TransitionType.CUT, fade_in=False, fade_out=False),
        motion=MotionSettings(type=MotionType.NONE, intensity=MotionIntensity.MEDIUM),
    )
    await pipe.run(JobInfo(id="motion_override", mode="topic"), req, job_dir,
                   script=make_script())

    rows = []
    for i, label in enumerate(["scene 0: pan_left strong", "scene 1: pan_left weak",
                               "scene 2: inherits default (none)"]):
        clip = os.path.join(job_dir, f"clip_{i}.mp4")
        d = await _probe_duration(clip)
        start = 1.0 if d > 2.2 else max(0.1, d * 0.2)
        rows.append((label, jitter(clip, start, settings.video_fps)))

    print("\n| scene | movement (mean per-frame change) | smoothness (min/mean) |")
    print("|---|---|---|")
    for label, j in rows:
        print(f"| {label} | {j['mean_diff']} | {j['min_over_mean']} |")

    strong, weak, still = (r[1]["mean_diff"] for r in rows)
    problems = []
    # A subtle pan is the case most likely to quantise into stall-then-jump, so
    # hold every moving scene to the smoothness bar, not just the obvious ones.
    for label, j in rows[:2]:
        if not j["ok"]:
            problems.append(
                f"{label} judders (min/mean {j['min_over_mean']}, needs >= 0.25)")
    if still > 0.01:
        problems.append(f"default 'none' scene moved ({still}) — override leaked across scenes")
    if strong <= 0.5:
        problems.append(f"pan_left override did not move (mean diff {strong})")
    if weak <= 0.5:
        problems.append(f"weak pan_left did not move (mean diff {weak})")
    if strong <= weak * 1.25:
        problems.append(f"intensity ignored: strong {strong} vs weak {weak}")
    if problems:
        raise SystemExit("FAIL: " + "; ".join(problems))
    print(f"\nPASS: per-scene motion + intensity override applies (strong {strong} > weak {weak}), "
          f"and a 'none' scene stays perfectly still ({still})")


if __name__ == "__main__":
    asyncio.run(main())
