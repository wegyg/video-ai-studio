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
from app.providers.base import VisualAsset, VisualsProvider


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
    # Soft glowing light blobs for depth / a "designed" feel.
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    lighter = tuple(min(255, int(c * 1.35) + 30) for c in top)
    blob_r = int(w * 0.6)
    positions = [(int(w * 0.15), int(h * 0.18)), (int(w * 0.85), int(h * 0.42))]
    for bx, by in positions:
        gd.ellipse(
            [bx - blob_r, by - blob_r, bx + blob_r, by + blob_r],
            fill=(*lighter, 55),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(w // 4))
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")

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
    ) -> VisualAsset:
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
        return VisualAsset(path=out_path, kind="image")


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
    ) -> VisualAsset:
        if existing_images:  # honor uploaded product photos in image mode
            return await self._fallback.get_visual(
                query, out_path, width=width, height=height,
                existing_images=existing_images, index=index,
            )
        headers = {"Authorization": self._settings.pexels_api_key}
        # 1) Prefer a real MOVING stock clip (portrait).
        try:
            return await self._fetch_video(query, out_path, width, height, index, headers)
        except Exception:
            pass
        # 2) Fall back to a still stock photo.
        try:
            return await self._fetch_photo(query, out_path, width, height, index, headers)
        except Exception:
            pass
        # 3) Offline gradient keeps the pipeline alive.
        return await self._fallback.get_visual(
            query, out_path, width=width, height=height, index=index
        )

    async def _fetch_video(
        self, query: str, out_path: str, width: int, height: int, index: int, headers: dict
    ) -> VisualAsset:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={"query": query, "orientation": "portrait", "per_page": 8, "size": "medium"},
            )
            r.raise_for_status()
            videos = r.json().get("videos", [])
            if not videos:
                raise ValueError("no video results")
            pick = videos[index % len(videos)]
            # choose a portrait-ish file with the largest height <= 1920
            files = sorted(
                [f for f in pick.get("video_files", []) if f.get("height")],
                key=lambda f: f["height"],
                reverse=True,
            )
            portrait = [f for f in files if f["height"] >= f.get("width", 0)]
            chosen = (portrait or files)[0]
            vid_url = chosen["link"]
            raw = out_path + ".src.mp4"
            async with client.stream("GET", vid_url) as resp:
                resp.raise_for_status()
                with open(raw, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
        # normalize to exact 9:16, cap length, strip audio -> returned as video
        clip = out_path + ".clip.mp4"
        await _normalize_video(raw, clip, width, height, max_sec=6.0)
        try:
            os.remove(raw)
        except OSError:
            pass
        return VisualAsset(path=clip, kind="video")

    async def _fetch_photo(
        self, query: str, out_path: str, width: int, height: int, index: int, headers: dict
    ) -> VisualAsset:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.pexels.com/v1/search",
                headers=headers,
                params={"query": query, "orientation": "portrait", "per_page": 8},
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if not photos:
                raise ValueError("no photo results")
            pick = photos[index % len(photos)]
            img = await client.get(pick["src"]["large2x"])
            img.raise_for_status()
            tmp = out_path + ".dl"
            with open(tmp, "wb") as f:
                f.write(img.content)
        photo = Image.open(tmp).convert("RGB")
        photo = _cover_fit(photo, width, height)
        photo.save(out_path, "JPEG", quality=90)
        os.remove(tmp)
        return VisualAsset(path=out_path, kind="image")


# --- video helper ------------------------------------------------------------
async def _normalize_video(src: str, dst: str, w: int, h: int, max_sec: float) -> None:
    """Crop/scale a stock clip to exact WxH (9:16), trim length, drop audio."""
    import asyncio as _asyncio
    import subprocess as _sp

    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-t", f"{max_sec}", "-an",
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        dst,
    ]
    proc = await _asyncio.create_subprocess_exec(
        *cmd, stdout=_sp.DEVNULL, stderr=_sp.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"normalize_video failed: {err.decode()[-300:]}")


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
