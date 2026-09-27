"""FFmpeg rendering: turn (visuals + audio + captions) into a 9:16 MP4.

Strategy (kept robust across ffmpeg builds):
1. For each scene: build a per-scene clip from its still image with a slow
   Ken-Burns zoom and a burned-in caption (drawtext).
2. Concatenate all scene clips (video only).
3. Mux the single narration track (already concatenated) over the video,
   trimming/padding to match, and mix in optional background music.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont


@dataclass
class SceneClip:
    image_path: str
    caption: str
    duration: float
    audio_path: str | None = None


def _escape_drawtext(text: str) -> str:
    # Escape characters that are special inside ffmpeg drawtext.
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")  # curly apostrophe avoids quoting headaches
        .replace("%", "\\%")
    )


def _wrap(text: str, width: int = 22) -> str:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines[:4])


async def _run(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}...\n{err.decode()[-800:]}")


async def _probe_duration(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return 0.0


class Renderer:
    def __init__(self, width: int, height: int, fps: int, font: str | None = None) -> None:
        self.w = width
        self.h = height
        self.fps = fps
        self.font = font or _find_font()

    async def render_scene(self, clip: SceneClip, out_path: str) -> str:
        d = max(clip.duration, 1.0)
        frames = int(d * self.fps)

        # Burn the caption onto the still with PIL (portable: no ffmpeg
        # drawtext/freetype dependency, and gives us full styling control).
        captioned = clip.image_path + ".cap.jpg"
        await asyncio.get_event_loop().run_in_executor(
            None, self._burn_caption, clip.image_path, captioned, clip.caption
        )

        # Ken Burns: gentle zoom from 1.0 -> 1.08 across the scene.
        zoom = (
            f"scale={self.w*2}:-1,"
            f"zoompan=z='min(zoom+0.0009,1.08)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={self.w}x{self.h}:fps={self.fps}"
        )
        vf = f"{zoom},format=yuv420p"
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", captioned,
            "-t", f"{d}", "-vf", vf, "-r", str(self.fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ]
        await _run(cmd)
        return out_path

    def _burn_caption(self, src: str, dst: str, caption: str) -> None:
        img = Image.open(src).convert("RGB")
        draw = ImageDraw.Draw(img)
        text = _wrap(caption)
        font = self._load_font(size=max(48, self.w // 17))
        # measure multi-line text
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=14, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (self.w - tw) // 2
        y = int(self.h * 0.70)
        # semi-transparent rounded panel behind the text
        pad = 34
        panel = Image.new("RGBA", img.size, (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(panel)
        pdraw.rounded_rectangle(
            [x - pad, y - pad, x + tw + pad, y + th + pad],
            radius=28, fill=(0, 0, 0, 130),
        )
        img = Image.alpha_composite(img.convert("RGBA"), panel).convert("RGB")
        draw = ImageDraw.Draw(img)
        # soft shadow then main text
        draw.multiline_text(
            (x + 3, y + 3), text, font=font, fill=(0, 0, 0),
            spacing=14, align="center",
        )
        draw.multiline_text(
            (x, y), text, font=font, fill=(255, 255, 255),
            spacing=14, align="center",
        )
        img.save(dst, "JPEG", quality=90)

    def _load_font(self, size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
        if self.font and os.path.exists(self.font):
            try:
                return ImageFont.truetype(self.font, size)
            except Exception:
                pass
        return ImageFont.load_default()

    async def concat_video(self, clips: list[str], out_path: str) -> str:
        list_file = out_path + ".txt"
        with open(list_file, "w") as f:
            for c in clips:
                f.write(f"file '{os.path.abspath(c)}'\n")
        await _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", out_path,
        ])
        os.remove(list_file)
        return out_path

    async def concat_audio(self, audio_paths: list[str], out_path: str) -> str:
        valid = [a for a in audio_paths if a and os.path.exists(a)]
        if not valid:
            # produce a short silent track
            await _run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "1", "-c:a", "aac", out_path,
            ])
            return out_path
        list_file = out_path + ".txt"
        with open(list_file, "w") as f:
            for a in valid:
                f.write(f"file '{os.path.abspath(a)}'\n")
        await _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:a", "aac", out_path,
        ])
        os.remove(list_file)
        return out_path

    async def mux(
        self, video_path: str, audio_path: str, out_path: str, music_path: str | None = None
    ) -> str:
        vdur = await _probe_duration(video_path)
        if music_path and os.path.exists(music_path):
            # mix narration (a) with looped, ducked music (b)
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-stream_loop", "-1", "-i", music_path,
                "-filter_complex",
                "[2:a]volume=0.18[m];[1:a][m]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac",
                "-t", f"{vdur}", "-shortest", out_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac",
                "-t", f"{vdur}", out_path,
            ]
        await _run(cmd)
        return out_path


def _find_font() -> str:
    candidates = [
        "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/gnu-free/FreeSansBold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""  # ffmpeg will use its built-in default
