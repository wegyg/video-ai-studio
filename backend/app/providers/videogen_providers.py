"""Premium image-to-video generation providers (paid tier).

These animate an uploaded product photo into a real cinematic clip.

FalVideoGenProvider    - fal.ai queue API. One key reaches many models
                         (Kling, Runway, Veo, ...). Endpoint chosen via config.
RunwayVideoGenProvider - Runway's native image-to-video REST API.

Both:
- upload/reference the source image,
- submit a generation job,
- poll until done,
- download + normalize the result to exact 9:16 (via _normalize_video).

They raise on any failure; the pipeline catches it and falls back to the free
Ken Burns animation, so a paid outage never breaks a render.
"""

from __future__ import annotations

import asyncio
import base64
import os

import httpx

from app.config import Settings
from app.providers.base import VideoGenProvider
from app.providers.visual_providers import _normalize_video


class FalVideoGenProvider(VideoGenProvider):
    """fal.ai unified queue API. Set FAL_API_KEY and (optionally) FAL_VIDEO_MODEL,
    e.g. 'fal-ai/kling-video/v2/master/image-to-video'."""

    name = "fal"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.key = settings.fal_api_key
        self.model = settings.fal_video_model
        self.base = "https://queue.fal.run"

    async def animate(
        self,
        image_path: str,
        out_path: str,
        *,
        prompt: str,
        duration_sec: float,
        width: int,
        height: int,
    ) -> str:
        headers = {"Authorization": f"Key {self.key}"}
        image_url = _data_uri(image_path)
        payload = {
            "prompt": prompt or "Subtle cinematic camera motion, product showcase",
            "image_url": image_url,
            "duration": "5",
            "aspect_ratio": "9:16",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            # 1) submit to the queue
            sub = await client.post(f"{self.base}/{self.model}", headers=headers, json=payload)
            sub.raise_for_status()
            data = sub.json()
            status_url = data.get("status_url") or data.get("response_url")
            resp_url = data.get("response_url")
            if not status_url:
                raise RuntimeError("fal: no status_url returned")

            # 2) poll until completed (cap ~5 min)
            for _ in range(100):
                await asyncio.sleep(3)
                st = await client.get(status_url, headers=headers)
                st.raise_for_status()
                s = st.json()
                state = s.get("status")
                if state == "COMPLETED":
                    break
                if state in ("FAILED", "ERROR"):
                    raise RuntimeError(f"fal generation failed: {s}")
            else:
                raise TimeoutError("fal generation timed out")

            # 3) fetch result and extract the video URL
            res = await client.get(resp_url or status_url, headers=headers)
            res.raise_for_status()
            result = res.json()
            video_url = _dig_video_url(result)
            if not video_url:
                raise RuntimeError("fal: no video URL in result")

            raw = out_path + ".src.mp4"
            async with client.stream("GET", video_url) as vr:
                vr.raise_for_status()
                with open(raw, "wb") as f:
                    async for chunk in vr.aiter_bytes():
                        f.write(chunk)

        await _normalize_video(raw, out_path, width, height, max_sec=duration_sec)
        _safe_remove(raw)
        return out_path


class RunwayVideoGenProvider(VideoGenProvider):
    """Runway native image-to-video REST API (Gen-4.x family)."""

    name = "runway"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.key = settings.runway_api_key
        self.model = settings.runway_video_model
        self.base = "https://api.dev.runwayml.com/v1"
        self.version = "2024-11-06"

    async def animate(
        self,
        image_path: str,
        out_path: str,
        *,
        prompt: str,
        duration_sec: float,
        width: int,
        height: int,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.key}",
            "X-Runway-Version": self.version,
        }
        payload = {
            "model": self.model,
            "promptImage": _data_uri(image_path),
            "promptText": prompt or "Subtle cinematic camera motion, product showcase",
            "ratio": "720:1280",  # portrait
            "duration": 5,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            sub = await client.post(
                f"{self.base}/image_to_video", headers=headers, json=payload
            )
            sub.raise_for_status()
            task_id = sub.json().get("id")
            if not task_id:
                raise RuntimeError("runway: no task id")

            video_url = None
            for _ in range(100):
                await asyncio.sleep(3)
                st = await client.get(f"{self.base}/tasks/{task_id}", headers=headers)
                st.raise_for_status()
                s = st.json()
                status = s.get("status")
                if status == "SUCCEEDED":
                    outs = s.get("output") or []
                    video_url = outs[0] if outs else None
                    break
                if status in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"runway task failed: {s}")
            if not video_url:
                raise TimeoutError("runway generation timed out")

            raw = out_path + ".src.mp4"
            async with client.stream("GET", video_url) as vr:
                vr.raise_for_status()
                with open(raw, "wb") as f:
                    async for chunk in vr.aiter_bytes():
                        f.write(chunk)

        await _normalize_video(raw, out_path, width, height, max_sec=duration_sec)
        _safe_remove(raw)
        return out_path


# --- helpers -----------------------------------------------------------------
def _data_uri(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b = base64.b64encode(f.read()).decode()
    ext = os.path.splitext(image_path)[1].lower().lstrip(".") or "jpeg"
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{b}"


def _dig_video_url(obj) -> str | None:
    """Find a video URL in a nested fal result payload."""
    if isinstance(obj, dict):
        if "video" in obj and isinstance(obj["video"], dict) and obj["video"].get("url"):
            return obj["video"]["url"]
        for v in obj.values():
            found = _dig_video_url(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _dig_video_url(v)
            if found:
                return found
    elif isinstance(obj, str) and obj.startswith("http") and obj.endswith(".mp4"):
        return obj
    return None


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
