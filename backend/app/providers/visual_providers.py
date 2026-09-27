"""Visual (background) providers for each scene.

GradientVisualProvider - offline, no key. Renders an attractive gradient card
                         with a subtle vignette. Always works. Also used to
                         "frame" uploaded product photos (image-to-video mode).
PexelsVisualProvider   - free stock photos/videos (needs PEXELS_API_KEY, free).
"""

from __future__ import annotations

import asyncio
import colorsys
import hashlib
import os

import httpx
from PIL import Image, ImageDraw, ImageFilter

from app.config import Settings
from app.providers.base import VisualsProvider


def _seed_color(query: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Deterministically derive a pleasant 2-color gradient from the query."""
    h = int(hashlib.md5(query.encode()).hexdigest(), 16)
    hue = (h % 360) / 360.0
    c1 = colorsys.hls_to_rgb(hue, 0.45, 0.65)
    c2 = colorsys.hls_to_rgb((hue + 0.08) % 1.0, 0.25, 0.7)
    to255 = lambda c: tuple(int(x * 255) for x in c)  # noqa: E731
    return to255(c1), to255(c2)


def _draw_gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    # subtle vignette for depth
    vignette = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-w * 0.2, -h * 0.15, w * 1.2, h * 1.15], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(w // 8))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(base, dark, vignette)


class GradientVisualProvider(VisualsProvider):
    name = "gradient"

    async def get_visual(
        self,
        query: str,
        out_path: str,
        *,
        width: int,
        height: int,
        existing_images: list[str] | None = None,
        index: int = 0,
    ) -> str:
        def _run() -> None:
            top, bottom = _seed_color(query)
            canvas = _draw_gradient(width, height, top, bottom)

            # image-to-video mode: composite an uploaded product photo, cover-fit.
            if existing_images:
                src = existing_images[index % len(existing_images)]
                try:
                    photo = Image.open(src).convert("RGB")
                    photo = _cover_fit(photo, width, height)
                    # blurred full-bleed backdrop + centered sharp photo card
                    backdrop = photo.filter(ImageFilter.GaussianBlur(40))
                    canvas = backdrop
                    card_w, card_h = int(width * 0.82), int(height * 0.62)
                    card = _contain_fit(photo, card_w, card_h)
                    cx = (width - card.width) // 2
                    cy = (height - card.height) // 2
                    canvas.paste(card, (cx, cy))
                except Exception:
                    pass  # fall back to the gradient we already drew

            canvas.save(out_path, "JPEG", quality=90)

        await asyncio.get_event_loop().run_in_executor(None, _run)
        return out_path


class PexelsVisualProvider(VisualsProvider):
    name = "pexels"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fallback = GradientVisualProvider()

    async def get_visual(
        self,
        query: str,
        out_path: str,
        *,
        width: int,
        height: int,
        existing_images: list[str] | None = None,
        index: int = 0,
    ) -> str:
        if existing_images:  # honor uploaded product photos in image mode
            return await self._fallback.get_visual(
                query, out_path, width=width, height=height,
                existing_images=existing_images, index=index,
            )
        try:
            headers = {"Authorization": self._settings.pexels_api_key}
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.pexels.com/v1/search",
                    headers=headers,
                    params={"query": query, "orientation": "portrait", "per_page": 5},
                )
                r.raise_for_status()
                photos = r.json().get("photos", [])
                if not photos:
                    raise ValueError("no results")
                pick = photos[index % len(photos)]
                img_url = pick["src"]["large2x"]
                img = await client.get(img_url)
                img.raise_for_status()
                tmp = out_path + ".dl"
                with open(tmp, "wb") as f:
                    f.write(img.content)
            # normalize to exact 9:16 canvas
            from PIL import Image as _Image

            photo = _Image.open(tmp).convert("RGB")
            photo = _cover_fit(photo, width, height)
            photo.save(out_path, "JPEG", quality=90)
            os.remove(tmp)
            return out_path
        except Exception:
            # graceful fallback keeps the pipeline alive
            return await self._fallback.get_visual(
                query, out_path, width=width, height=height, index=index
            )


# --- image helpers -----------------------------------------------------------
def _cover_fit(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover the WxH box, center-cropping the overflow."""
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _contain_fit(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to fit inside WxH preserving aspect (no crop)."""
    ratio = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), Image.LANCZOS)
