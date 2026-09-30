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
import re
import subprocess
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont


# The background is prepared at UPSCALE x the output size before any pan/zoom.
# Crop/zoom offsets land on whole pixels of that larger image, so after the
# downscale to the output size the movement lands on sub-pixels — that is what
# keeps a slow pan from stepping (jittering) one pixel at a time.
#
# The factor sets how fine that sub-pixel grid is: 1/UPSCALE of an output pixel.
# It has to stay clear of the slowest movement we offer, a subtle pan, which
# crosses roughly 0.4 output pixels per frame. At 2x the grid (0.5px) is coarser
# than that step, so such a pan froze for a frame and then jumped ~2px. 4x puts
# the grid at 0.25px and the movement lands on a new position every frame.
# Measured on the verification grid: smoothness (min/mean frame delta) on a
# subtle pan went 0.19 -> 0.68, for about 30% more time on a 3-scene render.
UPSCALE = 4

# Motion strength: (zoom factor, pan travel as a fraction of the upscaled frame).
MOTION_STRENGTH = {
    "weak": (1.05, 0.06),
    "medium": (1.10, 0.12),
    "strong": (1.18, 0.20),
}
# A still is enlarged once per scene, but footage pays that cost on every single
# frame, so video uses a smaller canvas. It still gives a pan far more margin than
# it can travel, and footage is already full of movement, so the coarser sub-pixel
# grid has nothing to show against it.
VIDEO_UPSCALE = 2

# Footage is already moving, so cap camera movement on video backgrounds.
VIDEO_MAX_INTENSITY = "weak"


@dataclass
class GraphicCue:
    """A pre-drawn graphic PNG and when it shows, in THIS scene's own time.

    An overlay can span several scenes, and each scene is a separate render, so
    the cue also records whether this is the scene where the graphic arrives or
    leaves. Without that, a graphic crossing a scene boundary would fade in again
    on every clip it touches instead of only at its start.
    """

    png_path: str
    start: float
    end: float
    fade: float = 0.0
    fade_in: bool = True
    fade_out: bool = True


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
    motion: str = "zoom_in"  # see models.MotionType (already resolved: never "auto")
    motion_intensity: str = "medium"
    graphics: list[GraphicCue] = field(default_factory=list)


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

    def _motion_chain(self, clip: SceneClip, total: float, frames: int) -> str:
        """Filter chain that turns input #0 into a moving [bg] at the output size.

        The background is first covered to UPSCALE x the output size, so a pan or
        zoom always has real pixels to move into — there is no way to expose a
        black edge, whatever the aspect ratio. Stills use zoompan; video uses a
        moving crop (zoompan would restart per input frame).
        """
        up = VIDEO_UPSCALE if clip.kind == "video" else UPSCALE
        bw, bh = self.w * up, self.h * up
        cover = (
            f"scale={bw}:{bh}:force_original_aspect_ratio=increase,"
            f"crop={bw}:{bh},setsar=1"
        )
        motion = clip.motion if clip.motion in {
            "none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down",
        } else "zoom_in"
        strength = clip.motion_intensity if clip.motion_intensity in MOTION_STRENGTH else "medium"
        if clip.kind == "video" and strength != "weak":
            strength = VIDEO_MAX_INTENSITY
        zmax, travel = MOTION_STRENGTH[strength]

        if motion == "none":
            return f"[0:v]scale={self.w}:{self.h}:force_original_aspect_ratio=increase," \
                   f"crop={self.w}:{self.h},setsar=1,format=rgba[bg]"

        if clip.kind == "video":
            # A crop window of the upscaled frame, moved with time, then downscaled.
            ramp = f"min(1\,t/{max(total, 0.1):.3f})"
            if motion in ("zoom_in", "zoom_out"):
                # crop size cannot change per frame, so emulate zoom with a slow
                # push across the extra margin instead of resizing the window
                cw, ch = f"iw/{zmax:.4f}", f"ih/{zmax:.4f}"
                grow = ramp if motion == "zoom_in" else f"(1-{ramp})"
                x = f"(iw-{cw})*0.5*(1-{grow}*0.6)"
                y = f"(ih-{ch})*0.5*(1-{grow}*0.6)"
            else:
                z = 1.0 + travel
                cw, ch = f"iw/{z:.4f}", f"ih/{z:.4f}"
                if motion == "pan_left":
                    x, y = f"(iw-{cw})*(1-{ramp})", f"(ih-{ch})/2"
                elif motion == "pan_right":
                    x, y = f"(iw-{cw})*{ramp}", f"(ih-{ch})/2"
                elif motion == "pan_up":
                    x, y = f"(iw-{cw})/2", f"(ih-{ch})*(1-{ramp})"
                else:  # pan_down
                    x, y = f"(iw-{cw})/2", f"(ih-{ch})*{ramp}"
            return (
                f"[0:v]{cover},crop={cw}:{ch}:x='{x}':y='{y}',"
                f"scale={self.w}:{self.h},setsar=1,format=rgba[bg]"
            )

        # Stills: zoompan over the upscaled image. `on` is the output frame index.
        last = max(frames - 1, 1)
        ramp = f"on/{last}"
        if motion == "zoom_in":
            z, x, y = f"1+{zmax - 1:.4f}*{ramp}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        elif motion == "zoom_out":
            z, x, y = f"{zmax:.4f}-{zmax - 1:.4f}*{ramp}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        else:
            z = f"{1.0 + travel:.4f}"  # hold a constant zoom so the pan has margin
            span_x, span_y = "(iw-iw/zoom)", "(ih-ih/zoom)"
            if motion == "pan_left":
                x, y = f"{span_x}*(1-{ramp})", f"{span_y}/2"
            elif motion == "pan_right":
                x, y = f"{span_x}*{ramp}", f"{span_y}/2"
            elif motion == "pan_up":
                x, y = f"{span_x}/2", f"{span_y}*(1-{ramp})"
            else:  # pan_down
                x, y = f"{span_x}/2", f"{span_y}*{ramp}"
        return (
            f"[0:v]{cover},zoompan=z='{z}':d={frames}:x='{x}':y='{y}':"
            f"s={self.w}x{self.h}:fps={self.fps},format=rgba[bg]"
        )

    async def render_scene(self, clip: SceneClip, out_path: str, tail_pad: float = 0.0) -> str:
        """Render one scene.

        `tail_pad` renders EXTRA footage past the scene's own duration. A
        transition to the next scene consumes exactly that much, so the scene
        still occupies `duration` on the finished timeline and nothing else
        (narration, captions, music) has to move. Captions keep their own timing
        over `duration` and stay on screen through the pad.
        """
        d = max(clip.duration, 1.0)
        pad = max(0.0, tail_pad)

        if clip.kind == "video":
            return await self._render_video_scene(clip, out_path, d, pad)
        return await self._render_still_scene(clip, out_path, d, pad)

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

    def _overlay_filter(self, n_overlays: int, d: float, base_label: str = "bg",
                        out_label: str = "v", final: bool = True) -> str:
        """Chain N timed overlays across duration d. Overlay PNGs are ffmpeg
        inputs #1..#N (input #0 is the background), so alias each to ovK first.
        Reveal step i is shown in its time slice; the last step persists.

        `final` converts to the output pixel format. Graphics overlays turn it off
        so they can still composite in RGBA before that conversion happens.
        """
        tail = ",format=yuv420p" if final else ""
        # alias overlay inputs [1:v]..[N:v] -> [ov0]..[ov(N-1)]
        aliases = ";".join(f"[{i + 1}:v]null[ov{i}]" for i in range(n_overlays))
        if n_overlays == 1:
            return (f"{aliases};[{base_label}][ov0]overlay=0:0:format=auto"
                    f"{tail}[{out_label}]")
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
        parts.append(f"[vtmp]null{tail}[{out_label}]" if not final
                     else f"[vtmp]format=yuv420p[{out_label}]")
        return ";".join(parts)

    def _graphics_filter(self, cues: list[GraphicCue], first_input: int,
                         base_label: str, out_label: str = "v") -> str:
        """Lay pre-drawn graphics over `base_label`, each in its own time window.

        Graphic PNGs come in as looped inputs #first_input.., so they are real
        streams and `fade` can ramp their alpha over time; a single-frame input
        would have no timeline to fade along. `enable` decides when the graphic is
        composited at all, and the fades soften its arrival and exit.
        """
        parts: list[str] = []
        for k, cue in enumerate(cues):
            idx = first_input + k
            chain = ["format=rgba"]
            if cue.fade > 0 and cue.fade_in:
                chain.append(f"fade=t=in:st={cue.start:.3f}:d={cue.fade:.3f}:alpha=1")
            if cue.fade > 0 and cue.fade_out:
                chain.append(
                    f"fade=t=out:st={max(cue.start, cue.end - cue.fade):.3f}"
                    f":d={cue.fade:.3f}:alpha=1"
                )
            parts.append(f"[{idx}:v]{','.join(chain)}[g{k}]")
        prev = base_label
        for k, cue in enumerate(cues):
            out = f"gv{k}"
            parts.append(
                f"[{prev}][g{k}]overlay=0:0:"
                f"enable='between(t,{cue.start:.3f},{cue.end:.3f})':format=auto[{out}]"
            )
            prev = out
        parts.append(f"[{prev}]format=yuv420p[{out_label}]")
        return ";".join(parts)

    def _scene_filter(self, clip: SceneClip, total: float, frames: int, d: float) -> str:
        """Motion -> captions -> graphics, ending on [v]."""
        n_caps = len(self._reveal_steps(clip))
        motion = self._motion_chain(clip, total, frames)
        if not clip.graphics:
            return motion + ";" + self._overlay_filter(n_caps, d, "bg")
        # captions stop short of the pixel-format conversion so the graphics can
        # still be composited on top of them
        caps = self._overlay_filter(n_caps, d, "bg", out_label="vcap", final=False)
        first = 1 + n_caps  # input 0 is the background, then one per caption step
        return ";".join([motion, caps, self._graphics_filter(clip.graphics, first, "vcap")])

    async def _render_still_scene(self, clip: SceneClip, out_path: str, d: float, pad: float = 0.0) -> str:
        total = d + pad
        frames = int(total * self.fps)
        overlays = await self._build_overlays(clip)
        inputs = ["-loop", "1", "-i", clip.image_path]
        for ov in overlays:
            inputs += ["-i", ov]
        for cue in clip.graphics:
            # looped so the graphic is a stream with a timeline to fade along
            inputs += ["-loop", "1", "-i", cue.png_path]
        fc = self._scene_filter(clip, total, frames, d)
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", fc, "-map", "[v]",
            "-t", f"{total}", "-r", str(self.fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ]
        await _run(cmd)
        return out_path

    async def _render_video_scene(self, clip: SceneClip, out_path: str, d: float, pad: float = 0.0) -> str:
        overlays = await self._build_overlays(clip)
        inputs = ["-stream_loop", "-1", "-i", clip.image_path]
        for ov in overlays:
            inputs += ["-i", ov]
        for cue in clip.graphics:
            inputs += ["-loop", "1", "-i", cue.png_path]
        fc = self._scene_filter(clip, d + pad, int((d + pad) * self.fps), d)
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", fc, "-map", "[v]",
            "-t", f"{d + pad}", "-r", str(self.fps),
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
        font = self._load_font(size=max(52, base), text=clean)
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

    def font_for(self, text: str = "") -> str:
        """Font path able to draw `text`.

        The configured font wins unless the text needs CJK glyphs it does not
        carry, in which case a CJK face is used for that line only.
        """
        if text and _CJK_RE.search(text):
            cjk = _find_font(text)
            if cjk:
                return cjk
        return self.font

    def _load_font(self, size: int, text: str = "") -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
        path = self.font_for(text)
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
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

    async def concat_with_transitions(
        self,
        clips: list[str],
        transitions: list[tuple[str | None, float]],
        out_path: str,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> str:
        """Stitch clips with xfade transitions in a single filter graph.

        `transitions[i]` is the (xfade name, duration) between clip i and i+1;
        a name of None is a hard cut. Every clip was rendered with a tail pad
        equal to its outgoing transition, so xfade eats the pad and the finished
        length stays sum(scene durations) — see render_scene().

        offset for boundary i = (length of the chain so far) - duration, i.e. the
        moment the next scene is supposed to start.
        """
        assert len(transitions) >= len(clips) - 1, "need one transition per boundary"
        lengths = [await _probe_duration(c) for c in clips]

        inputs: list[str] = []
        for c in clips:
            inputs += ["-i", c]
        parts = [f"[{i}:v]settb=AVTB,fps={self.fps},format=yuv420p[c{i}]" for i in range(len(clips))]

        cur = "c0"
        acc = lengths[0]
        for i in range(1, len(clips)):
            name, dur = transitions[i - 1]
            out = f"x{i}"
            if not name or dur <= 0:
                parts.append(f"[{cur}][c{i}]concat=n=2:v=1:a=0[{out}]")
                acc += lengths[i]
            else:
                offset = max(0.0, acc - dur)
                parts.append(
                    f"[{cur}][c{i}]xfade=transition={name}:duration={dur:.3f}:offset={offset:.3f}[{out}]"
                )
                acc += lengths[i] - dur
            cur = out

        tail = []
        if fade_in > 0:
            tail.append(f"fade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0:
            tail.append(f"fade=t=out:st={max(0.0, acc - fade_out):.3f}:d={fade_out:.3f}")
        parts.append(f"[{cur}]{','.join(tail) if tail else 'null'}[v]")

        await _run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(parts), "-map", "[v]",
            "-r", str(self.fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ])
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
        self,
        video_path: str,
        audio_path: str,
        out_path: str,
        music_path: str | None = None,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> str:
        vdur = await _probe_duration(video_path)
        afades = ""
        if fade_in > 0:
            afades += f",afade=t=in:st=0:d={fade_in:.3f}"
        if fade_out > 0:
            afades += f",afade=t=out:st={max(0.0, vdur - fade_out):.3f}:d={fade_out:.3f}"
        if music_path and os.path.exists(music_path):
            # mix narration (a) with looped, ducked music (b)
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-stream_loop", "-1", "-i", music_path,
                "-filter_complex",
                f"[2:a]volume=0.18[m];[1:a][m]amix=inputs=2:duration=first{afades}[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac",
                "-t", f"{vdur}", "-shortest", out_path,
            ]
        elif afades:
            cmd = [
                "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                "-filter_complex", f"[1:a]anull{afades}[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac",
                "-t", f"{vdur}", out_path,
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


_LATIN_FONTS = [
    "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/gnu-free/FreeSansBold.ttf",
]

# Korean, Japanese and Chinese need a font that actually carries those glyphs.
# The Latin fonts above do not: PIL draws a "tofu" box per character instead, so
# a Korean caption came out as a row of empty rectangles.
_CJK_FONTS = [
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]

# Hangul, kana, and CJK ideographs — enough to decide which font a line needs.
_CJK_RE = re.compile(
    r"[\u1100-\u11FF\u3040-\u30FF\u3130-\u318F\u3400-\u4DBF\u4E00-\u9FFF"
    r"\uA960-\uA97F\uAC00-\uD7AF\uF900-\uFAFF]"
)


def _find_font(text: str = "") -> str:
    """Best available font, preferring one that can draw `text`.

    Latin faces stay the default so existing output is unchanged; a CJK face is
    only reached for when the text actually contains CJK characters, and falls
    back to Latin if no CJK font is installed.
    """
    groups = [_CJK_FONTS, _LATIN_FONTS] if text and _CJK_RE.search(text) else [_LATIN_FONTS]
    for group in groups:
        for c in group:
            if os.path.exists(c):
                return c
    return ""  # ffmpeg will use its built-in default
