"""Per-scene transition override + cut fast path.

Two renders of the same 2-scene script:
  A) project default = cut, scene 1 overrides with fade_white
  B) project default = cut everywhere, edge fades off  (the original fast path)

Checks that the override actually happens (the boundary frame goes bright), that
the default stays a hard cut, and that neither render changes the timeline length.
"""

from __future__ import annotations

import asyncio
import os
import subprocess

from app.config import get_settings
from app.models import (
    JobInfo,
    Scene,
    Script,
    Tone,
    TopicRequest,
    TransitionSettings,
    TransitionType,
)
from app.pipeline import Pipeline
from app.render import _probe_duration


def brightness(video: str, t: float) -> float:
    """Mean luma (0-255) of the frame at t."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
         "-vf", "scale=64:64,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return round(sum(out) / max(len(out), 1), 1)


def make_script(override: TransitionType | None) -> Script:
    return Script(
        title="Override check",
        hook="One",
        scenes=[
            Scene(text="One", narration="One", visual_query="blue sky", duration_sec=2.0,
                  transition=override),
            Scene(text="Two", narration="Two", visual_query="red wall", duration_sec=2.0),
        ],
        cta="Two",
    )


async def render(tag: str, override: TransitionType | None, edge: bool) -> tuple[str, float, float]:
    """Render and return (path, length, boundary time). Scene durations are
    stretched to fit the narration by the pipeline, so the boundary is read back
    from the script instead of assumed."""
    settings = get_settings()
    settings.tts_provider = "silent"
    # Pin the background provider: with a PEXELS_API_KEY present the registry
    # would hand back real footage, and every measurement here assumes the
    # offline gradient. Results have to be reproducible with or without a key.
    settings.visuals_provider = "gradient"
    pipe = Pipeline(settings)
    script = make_script(override)
    req = TopicRequest(
        topic="Override check", tone=Tone.ENERGETIC, duration_sec=5,
        transition=TransitionSettings(
            type=TransitionType.CUT, duration_sec=0.6, fade_in=edge, fade_out=edge
        ),
    )
    job_dir = os.path.join(settings.output_dir, "verify_override", tag)
    final = await pipe.run(JobInfo(id=tag, mode="topic"), req, job_dir, script=script)
    boundary = script.scenes[0].duration_sec
    return final, await _probe_duration(final), boundary


def brightest(video: str, start: float, end: float) -> float:
    return max(brightness(video, t) for t in [start + i * 0.1 for i in range(int((end - start) / 0.1) + 1)])


async def main() -> None:
    a, dur_a, edge_a = await render("override_fade_white", TransitionType.FADE_WHITE, edge=False)
    b, dur_b, edge_b = await render("all_cut", None, edge=False)

    # the transition window runs [boundary, boundary + 0.6)
    peak_a = brightest(a, edge_a - 0.1, edge_a + 0.7)
    peak_b = brightest(b, edge_b - 0.1, edge_b + 0.7)
    base_a = brightness(a, max(0.1, edge_a - 0.8))
    expected = 2 * edge_a  # both scenes share the same duration

    print(f"\n| render | boundary | length (expected {expected:.2f}s) | frame before | brightest across boundary |")
    print("|---|---|---|---|---|")
    print(f"| scene override = fade_white | {edge_a:.2f}s | {dur_a:.3f}s | {base_a} | {peak_a} |")
    print(f"| project default = cut | {edge_b:.2f}s | {dur_b:.3f}s | {brightness(b, max(0.1, edge_b - 0.8))} | {peak_b} |")

    problems = []
    if peak_a < base_a + 40:
        problems.append(f"override did not brighten the boundary ({base_a} -> {peak_a})")
    if peak_b > base_a + 40:
        problems.append(f"the cut render flashed white ({peak_b}) — default should be a hard cut")
    for name, dur in (("override", dur_a), ("cut", dur_b)):
        if abs(dur - expected) > 0.1:
            problems.append(f"{name} render length {dur:.3f}s != {expected:.2f}s")
    if problems:
        raise SystemExit("FAIL: " + "; ".join(problems))
    print("\nPASS: per-scene override applies, default stays a hard cut, timeline length unchanged")


if __name__ == "__main__":
    asyncio.run(main())
