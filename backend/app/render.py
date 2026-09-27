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
    image_path: str  # still image OR source video clip depending on `kind`
    caption: str
    duration: float
    audio_path: str | None = None
    accent: tuple[int, int, int] = (124, 92, 255)  # brand purple default
    is_hook: bool = False  # first scene -> bigger, punchier caption
    kind: str = "image"  # "image" | "video"


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


# --- Emoji handling ----------------------------------------------------------
# PIL can't reliably rasterize color-emoji glyphs at arbitrary sizes with a
# regular truetype font, so unrenderable emoji show up as "tofu" boxes. We map
# the most common promo emojis to plain-text/symbol equivalents and drop the
# rest, keeping captions clean in the free (PIL-rendered) path.
_EMOJI_MAP = {
    "🔥": "", "🚀": "", "✨": "", "😎": "", "😉": "", "👋": "",
    "💛": "", "⭐": "", "✅": "", "👉": "", "💯": "",
    "🎉": "", "❤️": "", "❤": "", "😍": "", "🤝": "",
}


def _strip_emoji(text: str) -> str:
    for e, repl in _EMOJI_MAP.items():
        text = text.replace(e, repl)
    # remove any remaining non-BMP / symbol chars that would tofu
    cleaned = []
    for ch in text:
        code = ord(ch)
        # keep basic latin/latin-1, common punctuation, CJK, hangul, kana
        if (
            code < 0x2500  # below the symbol/emoji blocks
            or 0x3000 <= code <= 0x9FFF  # CJK
            or 0xAC00 <= code <= 0xD7A3  # Hangul
            or 0x3040 <= code <= 0x30FF  # kana
        ):
            cleaned.append(ch)
    out = "".join(cleaned)
    # collapse whitespace left by removed emojis
    return " ".join(out.split()).strip()


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

        if clip.kind == "video":
            return await self._render_video_scene(clip, out_path, d)
        return await self._render_still_scene(clip, out_path, d)

    async def _render_still_scene(self, clip: SceneClip, out_path: str, d: float) -> str:
        frames = int(d * self.fps)
        # Burn the caption onto the still with PIL (full styling control).
        captioned = clip.image_path + ".cap.jpg"
        await asyncio.get_event_loop().run_in_executor(
            None, self._burn_caption, clip.image_path, captioned, clip
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

    async def _render_video_scene(self, clip: SceneClip, out_path: str, d: float) -> str:
        # Build a transparent caption overlay PNG, then composite it over the
        # looped/trimmed stock clip.
        overlay = clip.image_path + ".overlay.png"
        await asyncio.get_event_loop().run_in_executor(
            None, self._make_caption_overlay, overlay, clip
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", clip.image_path,  # loop the stock clip
            "-i", overlay,
            "-filter_complex",
            f"[0:v]scale={self.w}:{self.h}:force_original_aspect_ratio=increase,"
            f"crop={self.w}:{self.h},setsar=1[bg];"
            f"[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
            "-map", "[v]",
            "-t", f"{d}", "-r", str(self.fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ]
        await _run(cmd)
        return out_path

    def _draw_caption_layer(self, clip: "SceneClip") -> Image.Image:
        """Render the full caption treatment onto a transparent RGBA layer."""
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # Dark gradient at the bottom for consistent legibility over any bg.
        grad_top = int(self.h * 0.55)
        for yy in range(grad_top, self.h):
            t = (yy - grad_top) / max(self.h - grad_top, 1)
            draw.line([(0, yy), (self.w, yy)], fill=(0, 0, 0, int(150 * t)))

        text = _wrap(_strip_emoji(clip.caption) or clip.caption)
        base = self.w // 15 if clip.is_hook else self.w // 18
        font = self._load_font(size=max(52, base))

        spacing = 16
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (self.w - tw) // 2
        y = int(self.h * (0.66 if clip.is_hook else 0.70))

        pad = 40
        # rounded panel
        draw.rounded_rectangle(
            [x - pad, y - pad, x + tw + pad, y + th + pad],
            radius=32, fill=(10, 10, 15, 150),
        )
        # accent bar on the left edge of the panel (tone color)
        draw.rounded_rectangle(
            [x - pad, y - pad, x - pad + 12, y + th + pad],
            radius=6, fill=(*clip.accent, 255),
        )
        # soft shadow then main text
        draw.multiline_text(
            (x + 3, y + 4), text, font=font, fill=(0, 0, 0, 200),
            spacing=spacing, align="center",
        )
        draw.multiline_text(
            (x, y), text, font=font, fill=(255, 255, 255, 255),
            spacing=spacing, align="center",
        )
        # accent underline beneath the hook for extra punch
        if clip.is_hook:
            uy = y + th + 14
            uw = min(int(tw * 0.5), 220)
            ux = (self.w - uw) // 2
            draw.rounded_rectangle([ux, uy, ux + uw, uy + 8], radius=4, fill=(*clip.accent, 255))

        return layer

    def _burn_caption(self, src: str, dst: str, clip: "SceneClip") -> None:
        img = Image.open(src).convert("RGBA")
        img = _cover_to(img, self.w, self.h)
        layer = self._draw_caption_layer(clip)
        out = Image.alpha_composite(img, layer).convert("RGB")
        out.save(dst, "JPEG", quality=92)

    def _make_caption_overlay(self, dst: str, clip: "SceneClip") -> None:
        self._draw_caption_layer(clip).save(dst, "PNG")

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


def _cover_to(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover WxH, center-crop overflow (keeps RGBA)."""
    if img.width == w and img.height == h:
        return img
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_w, new_h = int(h * src_ratio), h
    else:
        new_w, new_h = w, int(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - w) // 2, (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


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
