"""Background music for the promo video.

Two sources, resolved in order:
1. A local royalty-free track chosen from `assets/music/<tone>.mp3` (or any file
   under assets/music/). Drop your own licensed loops there to use them.
2. A procedurally-synthesized bed generated on the fly with FFmpeg — zero files,
   zero licensing concerns, always available. Each tone maps to a small chord
   built from sine oscillators plus a soft kick pulse for rhythm.

The generator is intentionally simple/ambient: it sits UNDER the narration
(mixed + ducked in render.mux) rather than competing with it.
"""

from __future__ import annotations

import asyncio
import glob
import os
import subprocess

from app.models import Tone

# Musical note frequencies (Hz) for building simple tone-appropriate chords.
_NOTE = {
    "C3": 130.81, "E3": 164.81, "G3": 196.00, "A3": 220.00,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23,
    "G4": 392.00, "A4": 440.00, "B4": 493.88,
}

# Tone -> (chord notes, tempo BPM, overall gain). Chosen to match the vibe.
_TONE_MUSIC: dict[Tone, tuple[list[str], int, float]] = {
    Tone.ENERGETIC: (["C4", "E4", "G4"], 128, 0.16),      # bright major, fast
    Tone.PROFESSIONAL: (["C3", "G3", "C4"], 100, 0.12),   # clean, steady
    Tone.FRIENDLY: (["C4", "E4", "A4"], 112, 0.14),       # warm major 6th
    Tone.LUXURY: (["A3", "C4", "E4"], 84, 0.11),          # smooth minor, slow
    Tone.PLAYFUL: (["D4", "F4", "A4"], 120, 0.15),        # bouncy
}


def _music_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "assets", "music")


def find_local_track(tone: Tone) -> str | None:
    """Return a local licensed track for this tone if one exists."""
    d = _music_dir()
    if not os.path.isdir(d):
        return None
    # exact tone match first
    for ext in ("mp3", "wav", "m4a", "ogg"):
        p = os.path.join(d, f"{tone.value}.{ext}")
        if os.path.exists(p):
            return p
    # otherwise any file in the folder (round-robin-ish: first found)
    for ext in ("mp3", "wav", "m4a", "ogg"):
        hits = sorted(glob.glob(os.path.join(d, f"*.{ext}")))
        if hits:
            return hits[0]
    return None


async def synthesize_bed(tone: Tone, duration: float, out_path: str) -> str:
    """Generate an ambient music bed with FFmpeg (no external files needed)."""
    notes, bpm, gain = _TONE_MUSIC.get(tone, _TONE_MUSIC[Tone.ENERGETIC])
    dur = max(duration + 0.5, 2.0)

    # Build layered sine oscillators for the chord.
    inputs: list[str] = []
    labels: list[str] = []
    for i, note in enumerate(notes):
        freq = _NOTE.get(note, 261.63)
        inputs += ["-f", "lavfi", "-t", f"{dur}", "-i", f"sine=frequency={freq}:sample_rate=44100"]
        labels.append(f"[{i}:a]")

    # A soft "kick" pulse for gentle rhythm, gated by tempo.
    beat_period = 60.0 / bpm
    kick_idx = len(notes)
    inputs += [
        "-f", "lavfi", "-t", f"{dur}",
        "-i",
        f"sine=frequency=60:sample_rate=44100",
    ]

    # Mix chord notes, apply a slow tremolo for movement, soften highs,
    # add the kick with a tremolo gate to imply a beat, then set final gain.
    chord_mix = "".join(labels) + f"amix=inputs={len(notes)}:normalize=1[chord];"
    chord_fx = (
        "[chord]tremolo=f=5:d=0.25,"
        "lowpass=f=2500,"
        "aformat=channel_layouts=stereo[chordfx];"
    )
    kick_hz = 1.0 / beat_period
    kick_fx = (
        f"[{kick_idx}:a]tremolo=f={kick_hz:.3f}:d=0.9,"
        "lowpass=f=120,volume=0.5[kick];"
    )
    final_mix = (
        f"[chordfx][kick]amix=inputs=2:normalize=0,"
        f"volume={gain},"
        f"afade=t=in:st=0:d=0.6,afade=t=out:st={dur-0.8:.2f}:d=0.8[out]"
    )
    filter_complex = chord_mix + chord_fx + kick_fx + final_mix

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"music synth failed: {err.decode()[-400:]}")
    return out_path


async def get_music(tone: Tone, duration: float, out_path: str, enabled: bool = True) -> str | None:
    """Resolve background music: local track > procedural bed. None if disabled."""
    if not enabled:
        return None
    local = find_local_track(tone)
    if local:
        return local
    try:
        return await synthesize_bed(tone, duration, out_path)
    except Exception:
        return None  # never let music break the render
