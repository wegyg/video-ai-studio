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
    caption_style: str = "pop"  # "static" | "pop" | "karaoke"


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

    def _reveal_steps(self, clip: SceneClip) -> list[tuple]:
        """Timeline of (reveal_arg) states across the scene for its style."""
        words = (_strip_emoji(clip.caption) or clip.caption).split()
        nw = len(words)
        if clip.caption_style == "pop" and nw > 1:
            return [("pop", k) for k in range(1, nw + 1)]
        if clip.caption_style == "karaoke" and nw > 1:
            return [("karaoke", k) for k in range(nw)]
        return [None]  # static

    async def _build_overlays(self, clip: SceneClip) -> list[str]:
        """Render one transparent overlay PNG per reveal step."""
        steps = self._reveal_steps(clip)
        paths: list[str] = []
        for idx, rev in enumerate(steps):
            p = f"{clip.image_path}.ov{idx}.png"
            await asyncio.get_event_loop().run_in_executor(
                None, self._make_caption_overlay, p, clip, rev
            )
            paths.append(p)
        return paths

    def _overlay_filter(self, n_overlays: int, d: float, base_label: str = "bg") -> str:
        """Chain N timed overlays across duration d. Overlay PNGs are ffmpeg
        inputs #1..#N (input #0 is the background), so alias each to ovK first.
        Reveal step i is shown in its time slice; the last step persists."""
        # alias overlay inputs [1:v]..[N:v] -> [ov0]..[ov(N-1)]
        aliases = ";".join(f"[{i + 1}:v]null[ov{i}]" for i in range(n_overlays))
        if n_overlays == 1:
            return f"{aliases};[{base_label}][ov0]overlay=0:0:format=auto,format=yuv420p[v]"
        slice_d = d / n_overlays
        parts = [aliases]
        prev = base_label
        for i in range(n_overlays):
            start = i * slice_d
            cond = f"gte(t,{start:.3f})" if i == n_overlays - 1 else \
                   f"between(t,{start:.3f},{(start + slice_d):.3f})"
            out = f"v{i}" if i < n_overlays - 1 else "vtmp"
            parts.append(f"[{prev}][ov{i}]overlay=0:0:enable='{cond}':format=auto[{out}]")
            prev = out
        parts.append("[vtmp]format=yuv420p[v]")
        return ";".join(parts)

    async def _render_still_scene(self, clip: SceneClip, out_path: str, d: float) -> str:
        frames = int(d * self.fps)
        overlays = await self._build_overlays(clip)
        # Ken Burns zoom on the still background.
        zoom = (
            f"scale={self.w*2}:-1,"
            f"zoompan=z='min(zoom+0.0009,1.08)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={self.w}x{self.h}:fps={self.fps},format=rgba[bg]"
        )
        inputs = ["-loop", "1", "-i", clip.image_path]
        for ov in overlays:
            inputs += ["-i", ov]
        fc = f"[0:v]{zoom};" + self._overlay_filter(len(overlays), d, "bg")
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", fc, "-map", "[v]",
            "-t", f"{d}", "-r", str(self.fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ]
        await _run(cmd)
        return out_path

    async def _render_video_scene(self, clip: SceneClip, out_path: str, d: float) -> str:
        overlays = await self._build_overlays(clip)
        inputs = ["-stream_loop", "-1", "-i", clip.image_path]
        for ov in overlays:
            inputs += ["-i", ov]
        bg = (
            f"[0:v]scale={self.w}:{self.h}:force_original_aspect_ratio=increase,"
            f"crop={self.w}:{self.h},setsar=1,format=rgba[bg];"
        )
        fc = bg + self._overlay_filter(len(overlays), d, "bg")
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", fc, "-map", "[v]",
            "-t", f"{d}", "-r", str(self.fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ]
        await _run(cmd)
        return out_path

    def _draw_caption_layer(self, clip: "SceneClip", reveal=None) -> Image.Image:
        """Render the caption onto a transparent RGBA layer.

        `reveal` controls animated styles:
        - None                -> show the whole caption (static).
        - ("pop", k)          -> show only the first k words (word pop-in).
        - ("karaoke", k)      -> show all words, highlight word index k.
        """
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # Dark gradient at the bottom for consistent legibility over any bg.
        grad_top = int(self.h * 0.55)
        for yy in range(grad_top, self.h):
            t = (yy - grad_top) / max(self.h - grad_top, 1)
            draw.line([(0, yy), (self.w, yy)], fill=(0, 0, 0, int(150 * t)))

        clean = _strip_emoji(clip.caption) or clip.caption
        words = clean.split()
        style = reveal[0] if reveal else "static"
        k = reveal[1] if reveal else len(words)

        # Which words are visible + which is "active" (highlighted).
        if style == "pop":
            shown_words = words[: max(1, k)]
            active_idx = -1
        elif style == "karaoke":
            shown_words = words
            active_idx = min(k, len(words) - 1)
        else:
            shown_words = words
            active_idx = -1

        text = _wrap(" ".join(shown_words)) if shown_words else ""
        full_text = _wrap(clean)  # measure against the FULL caption for stable layout

        base = self.w // 15 if clip.is_hook else self.w // 18
        font = self._load_font(size=max(52, base))
        spacing = 16

        # Stable panel sized to the full caption (so it doesn't jump per frame).
        fbbox = draw.multiline_textbbox((0, 0), full_text or " ", font=font, spacing=spacing, align="center")
        tw, th = fbbox[2] - fbbox[0], fbbox[3] - fbbox[1]
        x = (self.w - tw) // 2
        y = int(self.h * (0.66 if clip.is_hook else 0.70))

        pad = 40
        draw.rounded_rectangle(
            [x - pad, y - pad, x + tw + pad, y + th + pad], radius=32, fill=(10, 10, 15, 150)
        )
        draw.rounded_rectangle(
            [x - pad, y - pad, x - pad + 12, y + th + pad], radius=6, fill=(*clip.accent, 255)
        )

        panel_cx = x + tw // 2  # horizontal center of the stable panel
        if style == "karaoke":
            self._draw_karaoke(draw, full_text, font, x, y, tw, spacing, clip.accent, active_idx)
        elif style == "pop":
            # Fixed layout from the full caption so words never shift; newest
            # word gets accent color + tiny bounce.
            self._pop_full_words = words
            self._pop_accent = clip.accent
            self._draw_pop(layer, shown_words, font, panel_cx, y, spacing)
        elif text:
            # static: center the full caption within the panel
            self._draw_centered(draw, text, font, panel_cx, y, spacing)

        if clip.is_hook:
            uy = y + th + 14
            uw = min(int(tw * 0.5), 220)
            ux = (self.w - uw) // 2
            draw.rounded_rectangle([ux, uy, ux + uw, uy + 8], radius=4, fill=(*clip.accent, 255))

        return layer

    def _draw_karaoke(self, draw, wrapped_text, font, x, y, tw, spacing, accent, active_idx):
        """Draw wrapped text line-by-line, highlighting the active word index."""
        lines = wrapped_text.split("\n")
        wi = 0
        cy = y
        for line in lines:
            lwords = line.split()
            # measure line width to center it within the panel
            lbbox = draw.textbbox((0, 0), line, font=font)
            lw = lbbox[2] - lbbox[0]
            lh = lbbox[3] - lbbox[1]
            cx = x + (tw - lw) // 2
            space_w = draw.textbbox((0, 0), " ", font=font)[2]
            for w in lwords:
                color = accent if wi == active_idx else (255, 255, 255)
                draw.text((cx + 3, cy + 4), w, font=font, fill=(0, 0, 0, 200))
                draw.text((cx, cy), w, font=font, fill=(*color, 255) if len(color) == 3 else color)
                ww = draw.textbbox((0, 0), w, font=font)[2]
                cx += ww + space_w
                wi += 1
            cy += lh + spacing

    def _draw_centered(self, draw, text: str, font, cx: int, y: int, spacing: int) -> None:
        """Draw multiline text horizontally centered on cx (shadow + white)."""
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        tw = bbox[2] - bbox[0]
        left = cx - tw // 2
        draw.multiline_text((left + 3, y + 4), text, font=font, fill=(0, 0, 0, 200),
                            spacing=spacing, align="center")
        draw.multiline_text((left, y), text, font=font, fill=(255, 255, 255, 255),
                            spacing=spacing, align="center")

    def _draw_pop(self, layer: Image.Image, shown_words: list, font, cx: int, y: int,
                  spacing: int) -> None:
        """Stable word-reveal: word positions are computed from the FULL caption
        so nothing shifts as words appear. Already-shown words are white; the
        newest word gets an accent color + a small upward 'bounce' (position
        offset only — no scaling — so spacing never changes)."""
        if not shown_words:
            return
        draw = ImageDraw.Draw(layer)
        n_shown = len(shown_words)

        space_w = draw.textbbox((0, 0), " ", font=font)[2]
        asc = draw.textbbox((0, 0), "Ag", font=font)
        line_h = asc[3] - asc[1]

        # Fixed layout: wrap the FULL caption (all words) once.
        full_words = self._pop_full_words
        wrapped = _wrap(" ".join(full_words))
        lines = [ln.split() for ln in wrapped.split("\n") if ln.strip()]

        newest_idx = n_shown - 1
        flat = 0
        cy = y
        for lwords in lines:
            widths = [draw.textbbox((0, 0), w, font=font)[2] for w in lwords]
            lw = sum(widths) + space_w * (max(len(lwords) - 1, 0))
            cxpos = cx - lw // 2
            for w, ww in zip(lwords, widths):
                if flat < n_shown:  # only draw words revealed so far
                    is_newest = flat == newest_idx
                    color = self._pop_accent if is_newest else (255, 255, 255)
                    dy = -8 if is_newest else 0  # tiny upward bounce for the new word
                    draw.text((cxpos + 3, cy + 4 + dy), w, font=font, fill=(0, 0, 0, 200))
                    draw.text((cxpos, cy + dy), w, font=font, fill=(*color, 255))
                cxpos += ww + space_w
                flat += 1
            cy += line_h + spacing

    def _burn_caption(self, src: str, dst: str, clip: "SceneClip", reveal=None) -> None:
        img = Image.open(src).convert("RGBA")
        img = _cover_to(img, self.w, self.h)
        layer = self._draw_caption_layer(clip, reveal)
        out = Image.alpha_composite(img, layer).convert("RGB")
        out.save(dst, "JPEG", quality=92)

    def _make_caption_overlay(self, dst: str, clip: "SceneClip", reveal=None) -> None:
        self._draw_caption_layer(clip, reveal).save(dst, "PNG")

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

    async def build_narration(
        self,
        segments: list[tuple[float, str | None]],
        total: float,
        out_path: str,
    ) -> str:
        """Lay each scene's narration at its own start time on the timeline.

        `segments` is [(start_sec, audio_path)] — start_sec is where that scene's
        VIDEO begins. Concatenating the clips back-to-back (the old behaviour)
        drifts, because every scene's video is longer than its narration (scene
        duration = max(script, spoken + 0.6s)), so the voice creeps ahead of the
        captions by the accumulated padding. Placing each segment absolutely
        keeps voice, captions and visuals locked together.

        A 60ms fade on both ends of every segment removes the click you get from
        cutting into/out of a waveform mid-cycle. The result is padded with
        silence to exactly `total` so the audio and video lengths match.
        """
        valid = [(max(0.0, s), p) for s, p in segments if p and os.path.exists(p)]
        total = max(total, 0.1)
        if not valid:
            await _run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{total:.3f}", "-c:a", "aac", out_path,
            ])
            return out_path

        inputs: list[str] = []
        chains: list[str] = []
        labels: list[str] = []
        fade = 0.06
        for i, (start, path) in enumerate(valid):
            dur = await _probe_duration(path)
            inputs += ["-i", path]
            # normalise format first: segments can be mp3/m4a at different rates
            chain = (
                f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"afade=t=in:st=0:d={fade}"
            )
            if dur > 2 * fade:
                chain += f",afade=t=out:st={dur - fade:.3f}:d={fade}"
            if start > 0:
                ms = int(round(start * 1000))
                chain += f",adelay={ms}|{ms}"
            chain += f"[a{i}]"
            chains.append(chain)
            labels.append(f"[a{i}]")

        if len(labels) == 1:
            mixed = f"{labels[0]}apad[mix]"
        else:
            mixed = (
                "".join(labels)
                + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0:duration=longest,apad[mix]"
            )
        fc = ";".join(chains + [mixed])
        await _run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", fc, "-map", "[mix]",
            "-t", f"{total:.3f}", "-c:a", "aac", out_path,
        ])
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
