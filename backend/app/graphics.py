"""Graphic overlays, drawn with PIL onto transparent full-frame PNGs.

Everything here is generated in code — no fetched or licensed artwork — and every
size and position is a percentage of the frame, so one overlay lands in the same
visual spot whether the video is 9:16, 1:1 or 16:9.

Each overlay is drawn on its own small tile, rotated if asked, then pasted
centred on its anchor. That keeps rotation and opacity in one place for all four
kinds instead of special-casing each shape.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from app.models import Overlay, OverlayKind, ShapeKind, StickerPreset

# Badge stickers are just a word in a rounded box; these are the words.
_STICKER_WORDS: dict[StickerPreset, str] = {
    StickerPreset.NEW: "NEW",
    StickerPreset.SALE: "SALE",
    StickerPreset.HOT: "HOT",
    StickerPreset.BEST: "BEST",
    StickerPreset.FREE: "FREE",
    StickerPreset.SOLD_OUT: "SOLD OUT",
}


def hex_rgb(value: str, fallback: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    v = (value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return fallback
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return fallback


def _readable_on(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """Black or white, whichever stays legible on `bg`."""
    luma = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (17, 17, 17) if luma > 150 else (255, 255, 255)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(8, int(size))
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _measure(text: str, font) -> tuple[int, int, int, int]:
    """Size of `text` plus the offset from the draw origin to its top-left ink.

    `textbbox` reports where the glyphs actually land, which is not the origin you
    pass to `draw.text` — ascenders and descenders push it around. Drawing at
    (x - ox, y - oy) puts the visible ink exactly at (x, y), which is what keeps
    text centred in a badge instead of hanging out of the bottom of it.
    """
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=font)
    return x1 - x0, y1 - y0, x0, y0


# --- the four kinds -------------------------------------------------------


def _draw_text_tile(ov: Overlay, w: int, h: int, font_path: str) -> Image.Image:
    """A line of text, optionally sitting on a filled box."""
    size = max(10, int(h * ov.size_pct / 100.0))
    font = _font(font_path, size)
    tw, th, ox, oy = _measure(ov.text or " ", font)
    pad_x, pad_y = int(size * 0.5), int(size * 0.32)
    tile = Image.new("RGBA", (tw + pad_x * 2, th + pad_y * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    colour = hex_rgb(ov.color)
    tx, ty = pad_x - ox, pad_y - oy
    if ov.background_box:
        d.rounded_rectangle(
            [0, 0, tile.width - 1, tile.height - 1],
            radius=max(4, int(size * 0.28)), fill=(*hex_rgb(ov.box_color, (0, 0, 0)), 235),
        )
    else:
        # no box, so lift the text off the picture with a shadow
        d.text((tx + 2, ty + 3), ov.text, font=font, fill=(0, 0, 0, 170))
    d.text((tx, ty), ov.text, font=font, fill=(*colour, 255))
    return tile


def _draw_shape_tile(ov: Overlay, w: int, h: int, font_path: str) -> Image.Image:
    """Label box, arrow, circle or highlight bar."""
    tw = max(4, int(w * ov.width_pct / 100.0))
    th = max(4, int(h * ov.height_pct / 100.0))
    stroke = max(2, int(w * ov.thickness_pct / 100.0))
    colour = hex_rgb(ov.color)
    if ov.shape is ShapeKind.CIRCLE:
        th = tw  # keep it round; see the CIRCLE branch below
    pad = stroke * 2  # room for the stroke and for rotation not to clip
    tile = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    box = [pad, pad, pad + tw - 1, pad + th - 1]

    if ov.shape is ShapeKind.LABEL_BOX:
        d.rounded_rectangle(box, radius=max(6, int(min(tw, th) * 0.18)),
                            outline=(*colour, 255), width=stroke)
    elif ov.shape is ShapeKind.CIRCLE:
        # One diameter for both axes. Width and height are percentages of
        # different sides of the frame, so honouring both would squash a circle
        # highlight into a flat ellipse in 16:9 and stretch it in 9:16 — the same
        # setting would not look like the same graphic. `height_pct` is ignored
        # here; a deliberately oval frame is what LABEL_BOX is for.
        d.ellipse([pad, pad, pad + tw - 1, pad + tw - 1], outline=(*colour, 255),
                  width=stroke)
    elif ov.shape is ShapeKind.HIGHLIGHT_BAR:
        d.rounded_rectangle(box, radius=max(3, int(th * 0.45)), fill=(*colour, 255))
    else:  # ARROW, drawn pointing right; rotation_deg aims it elsewhere
        mid = pad + th // 2
        head_w = max(stroke * 3, int(tw * 0.32))
        shaft_end = pad + tw - head_w
        half = max(stroke, int(th * 0.16))
        d.rectangle([pad, mid - half, shaft_end, mid + half], fill=(*colour, 255))
        d.polygon(
            [(pad + tw - 1, mid), (shaft_end, pad), (shaft_end, pad + th - 1)],
            fill=(*colour, 255),
        )
    return tile


def _draw_logo_tile(ov: Overlay, w: int, h: int) -> Image.Image | None:
    """An uploaded PNG, scaled to width_pct of the frame, aspect preserved."""
    if not ov.logo_path or not os.path.isfile(ov.logo_path):
        return None
    try:
        logo = Image.open(ov.logo_path).convert("RGBA")
    except Exception:
        return None
    target_w = max(8, int(w * ov.size_pct / 100.0))
    scale = target_w / max(logo.width, 1)
    target_h = max(8, int(logo.height * scale))
    return logo.resize((target_w, target_h), Image.LANCZOS)


def _draw_sticker_tile(ov: Overlay, w: int, h: int, font_path: str) -> Image.Image:
    """One of ten built-in badges. Size is a percentage of the frame width."""
    side = max(24, int(w * ov.size_pct / 100.0))
    colour = hex_rgb(ov.color, (255, 59, 92))
    ink = _readable_on(colour)
    preset = ov.sticker

    if preset in _STICKER_WORDS:
        word = _STICKER_WORDS[preset]
        font = _font(font_path, int(side * (0.3 if len(word) > 4 else 0.42)))
        tw, th, ox, oy = _measure(word, font)
        pad = int(side * 0.16)
        tile = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        d.rounded_rectangle([0, 0, tile.width - 1, tile.height - 1],
                            radius=int(tile.height * 0.28), fill=(*colour, 255))
        d.text((pad - ox, pad - oy), word, font=font, fill=(*ink, 255))
        return tile

    tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    m = int(side * 0.06)  # margin so strokes stay inside the tile

    if preset is StickerPreset.CHECK:
        d.ellipse([m, m, side - m, side - m], fill=(*colour, 255))
        lw = max(3, int(side * 0.1))
        d.line([(side * 0.28, side * 0.52), (side * 0.45, side * 0.68),
                (side * 0.73, side * 0.34)], fill=(*ink, 255), width=lw, joint="curve")
    elif preset is StickerPreset.STAR:
        import math
        cx = cy = side / 2
        outer, inner = side * 0.46, side * 0.2
        pts = []
        for i in range(10):
            r = outer if i % 2 == 0 else inner
            a = -math.pi / 2 + i * math.pi / 5
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=(*colour, 255))
    elif preset is StickerPreset.ARROW_DOWN:
        shaft = max(4, int(side * 0.16))
        cx = side / 2
        d.rectangle([cx - shaft / 2, m, cx + shaft / 2, side * 0.62], fill=(*colour, 255))
        d.polygon([(cx, side - m), (side * 0.22, side * 0.55), (side * 0.78, side * 0.55)],
                  fill=(*colour, 255))
    else:  # PERCENT
        d.ellipse([m, m, side - m, side - m], fill=(*colour, 255))
        font = _font(font_path, int(side * 0.52))
        tw, th, ox, oy = _measure("%", font)
        d.text(((side - tw) / 2 - ox, (side - th) / 2 - oy), "%", font=font,
               fill=(*ink, 255))
    return tile


# --- composition ----------------------------------------------------------


def render_overlay_png(ov: Overlay, width: int, height: int, out_path: str,
                       font_path: str = "") -> str | None:
    """Draw one overlay onto a transparent frame-sized PNG.

    Returns None when there is nothing to draw (for example a logo overlay whose
    file is missing), so the caller can skip it rather than composite a blank
    layer for the whole scene.
    """
    if ov.kind is OverlayKind.TEXT:
        if not (ov.text or "").strip():
            return None
        tile = _draw_text_tile(ov, width, height, font_path)
    elif ov.kind is OverlayKind.SHAPE:
        tile = _draw_shape_tile(ov, width, height, font_path)
    elif ov.kind is OverlayKind.LOGO:
        tile = _draw_logo_tile(ov, width, height)
    else:
        tile = _draw_sticker_tile(ov, width, height, font_path)
    if tile is None:
        return None

    if ov.rotation_deg:
        tile = tile.rotate(ov.rotation_deg, resample=Image.BICUBIC, expand=True)

    if ov.opacity < 1.0:
        alpha = tile.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, ov.opacity))))
        tile.putalpha(alpha)

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # x_pct/y_pct is the centre of the graphic, so the 9-grid presets land the
    # same way in every aspect ratio.
    cx = int(width * ov.x_pct / 100.0)
    cy = int(height * ov.y_pct / 100.0)
    layer.alpha_composite(tile, (cx - tile.width // 2, cy - tile.height // 2))
    layer.save(out_path, "PNG")
    return out_path
