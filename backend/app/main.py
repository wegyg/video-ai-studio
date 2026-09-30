"""FastAPI application: endpoints for topic->video and image->video generation."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.config import get_settings
from app.models import (
    AspectRatio,
    MotionIntensity,
    MotionSettings,
    MotionType,
    TransitionSettings,
    TransitionType,
    CaptionStyle,
    ImageRequest,
    JobInfo,
    JobStatus,
    Overlay,
    RenderRequest,
    Script,
    Tone,
    TopicRequest,
)
from app.pipeline import Pipeline

settings = get_settings()
app = FastAPI(title="Video AI Studio", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Set CORS_ORIGINS to your site (comma separated) in production; the
    # wildcard is the local-development default.
    allow_origins=settings.cors_origin_list or ["*"],
    # No cookies or Authorization headers are used anywhere in this API. Asking
    # for credentials alongside a "*" origin is invalid per the CORS spec and
    # browsers reject the response outright, so a deployment that had not set
    # CORS_ORIGINS yet would fail every cross-origin call.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store (swap for Redis/DB in production).
JOBS: dict[str, JobInfo] = {}
OUTPUT_ROOT = os.path.abspath(settings.output_dir)
os.makedirs(OUTPUT_ROOT, exist_ok=True)

pipeline = Pipeline(settings)


def _job_dir(job_id: str) -> str:
    return os.path.join(OUTPUT_ROOT, job_id)


LOGO_DIR = os.path.join(OUTPUT_ROOT, "logos")
os.makedirs(LOGO_DIR, exist_ok=True)


def _resolve_overlays(overlays: list[Overlay]) -> list[Overlay]:
    """Turn `logo_id` into a real path, and refuse anything else.

    `logo_path` is always rewritten from the id, so a crafted request cannot ask
    the renderer to read a file outside the logo directory. Ids are the hex names
    handed out by the upload endpoint, so anything with a separator or an odd
    character in it is dropped rather than looked up.
    """
    for ov in overlays:
        ov.logo_path = None
        raw = (ov.logo_id or "").strip()
        if not raw or not re.fullmatch(r"[0-9a-f]{8,40}", raw):
            continue
        candidate = os.path.join(LOGO_DIR, f"{raw}.png")
        if os.path.isfile(candidate) and os.path.abspath(candidate).startswith(LOGO_DIR):
            ov.logo_path = candidate
    return overlays


def _parse_overlays(raw: str | None) -> list[Overlay]:
    """Overlays arrive as a JSON array on the multipart upload endpoints."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"overlays must be a JSON array: {e}") from e
    if not isinstance(data, list):
        raise HTTPException(400, "overlays must be a JSON array")
    try:
        return _resolve_overlays([Overlay.model_validate(item) for item in data])
    except ValidationError as e:
        raise HTTPException(400, f"invalid overlay: {e}") from e


async def _run_job(job_id, req, image_paths=None, script=None, video_paths=None):
    job = JOBS[job_id]
    try:
        final = await pipeline.run(
            job, req, _job_dir(job_id),
            image_paths=image_paths, script=script, video_paths=video_paths,
        )
        job.video_url = f"/api/jobs/{job_id}/video"
        _ = final
    except Exception as e:  # keep the job store consistent on failure
        job.status = JobStatus.ERROR
        job.error = str(e)
        job.message = "Generation failed"


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "providers": pipeline.registry.summary(),
        # Reported from the real setting, per ratio. The old fixed pair claimed
        # 1080x1920 even when rendering 1:1 or 16:9.
        "resolution": {
            r.value: "x".join(map(str, r.dimensions(base=settings.video_base_height)))
            for r in AspectRatio
        },
        "fps": settings.video_fps,
    }


@app.get("/api/providers")
async def providers():
    """Which providers are active + whether each optional upgrade is available."""
    s = settings
    return {
        "active": pipeline.registry.summary(),
        "upgrades": {
            "openai_script_tts": bool(s.openai_api_key),
            "pexels_visuals": bool(s.pexels_api_key),
            "fal_video": bool(s.fal_api_key),
            "runway_video": bool(s.runway_api_key),
        },
    }


# --- Two-step (editable) workflow: script -> edit -> render ----------------
@app.post("/api/script/topic")
async def script_topic(req: TopicRequest):
    """Generate an editable script draft from a topic (no rendering)."""
    script = await pipeline.generate_script(req)
    return {
        "script": script,
        "tone": req.tone,
        "language": req.language,
        "voice": req.voice,
        "music": req.music,
        "aspect_ratio": req.aspect_ratio,
        "caption_style": req.caption_style,
        "transition": req.transition,
        "motion": req.motion,
        "mode": "topic",
        "image_job_id": None,
    }


@app.post("/api/script/image")
async def script_image(
    topic: str = Form(...),
    key_points: str = Form(""),
    tone: Tone = Form(Tone.ENERGETIC),
    duration_sec: int = Form(15),
    language: str = Form("en"),
    voice: str = Form("default"),
    music: bool = Form(True),
    aspect_ratio: AspectRatio = Form(AspectRatio.VERTICAL),
    caption_style: CaptionStyle = Form(CaptionStyle.POP),
    transition_type: TransitionType = Form(TransitionType.CROSSFADE),
    transition_duration_sec: float = Form(0.5),
    fade_in: bool = Form(True),
    fade_out: bool = Form(True),
    motion_type: MotionType = Form(MotionType.AUTO),
    motion_intensity: MotionIntensity = Form(MotionIntensity.MEDIUM),
    overlays: str | None = Form(None),
    images: list[UploadFile] = File(...),
):
    """Generate an editable script draft from product images. Uploaded images
    are stashed under a job id so the later /api/render call can reuse them."""
    if not images:
        raise HTTPException(400, "At least one image is required")

    image_job_id = uuid.uuid4().hex[:12]
    jdir = _job_dir(image_job_id)
    os.makedirs(jdir, exist_ok=True)
    for idx, up in enumerate(images):
        ext = os.path.splitext(up.filename or "")[1] or ".jpg"
        with open(os.path.join(jdir, f"upload_{idx}{ext}"), "wb") as f:
            shutil.copyfileobj(up.file, f)

    req = ImageRequest(
        topic=topic,
        key_points=[p.strip() for p in key_points.split("\n") if p.strip()],
        tone=tone,
        duration_sec=duration_sec,
        language=language,
        voice=voice,
        music=music,
        aspect_ratio=aspect_ratio,
        caption_style=caption_style,
        transition=TransitionSettings(
            type=transition_type, duration_sec=transition_duration_sec,
            fade_in=fade_in, fade_out=fade_out,
        ),
        motion=MotionSettings(type=motion_type, intensity=motion_intensity),
        overlays=_parse_overlays(overlays),
    )
    script = await pipeline.generate_script(req)
    return {
        "script": script,
        "tone": tone,
        "language": language,
        "voice": voice,
        "music": music,
        "aspect_ratio": aspect_ratio,
        "caption_style": caption_style,
        "transition": req.transition,
        "motion": req.motion,
        "mode": "image",
        "image_job_id": image_job_id,
    }


@app.post("/api/script/video")
async def script_video(
    topic: str = Form(...),
    key_points: str = Form(""),
    tone: Tone = Form(Tone.ENERGETIC),
    duration_sec: int = Form(20),
    language: str = Form("en"),
    voice: str = Form("default"),
    music: bool = Form(True),
    aspect_ratio: AspectRatio = Form(AspectRatio.VERTICAL),
    caption_style: CaptionStyle = Form(CaptionStyle.POP),
    transition_type: TransitionType = Form(TransitionType.CROSSFADE),
    transition_duration_sec: float = Form(0.5),
    fade_in: bool = Form(True),
    fade_out: bool = Form(True),
    motion_type: MotionType = Form(MotionType.AUTO),
    motion_intensity: MotionIntensity = Form(MotionIntensity.MEDIUM),
    overlays: str | None = Form(None),
    videos: list[UploadFile] = File(...),
):
    """Movie-CF mode: upload your OWN footage, get an editable script draft.
    Uploaded clips are stashed under a job id for the later /api/render call."""
    if not videos:
        raise HTTPException(400, "At least one video clip is required")

    video_job_id = uuid.uuid4().hex[:12]
    jdir = _job_dir(video_job_id)
    os.makedirs(jdir, exist_ok=True)
    for idx, up in enumerate(videos):
        ext = os.path.splitext(up.filename or "")[1] or ".mp4"
        with open(os.path.join(jdir, f"clip_{idx}{ext}"), "wb") as f:
            shutil.copyfileobj(up.file, f)

    req = TopicRequest(
        topic=topic,
        key_points=[p.strip() for p in key_points.split("\n") if p.strip()],
        tone=tone, duration_sec=duration_sec, language=language, voice=voice, music=music,
        aspect_ratio=aspect_ratio, caption_style=caption_style,
        transition=TransitionSettings(
            type=transition_type, duration_sec=transition_duration_sec,
            fade_in=fade_in, fade_out=fade_out,
        ),
        motion=MotionSettings(type=motion_type, intensity=motion_intensity),
        overlays=_parse_overlays(overlays),
    )
    script = await pipeline.generate_script(req)
    return {
        "script": script, "tone": tone, "language": language, "voice": voice,
        "music": music, "aspect_ratio": aspect_ratio, "caption_style": caption_style,
        "transition": req.transition,
        "motion": req.motion,
        "mode": "video", "image_job_id": None,
        "video_job_id": video_job_id,
    }


def _stashed_files(job_id: str | None, prefix: str) -> list[str] | None:
    if not job_id:
        return None
    d = _job_dir(job_id)
    if not os.path.isdir(d):
        return None
    return sorted(
        os.path.join(d, f) for f in os.listdir(d) if f.startswith(prefix)
    ) or None


@app.post("/api/assets/logo")
async def upload_logo(logo: UploadFile = File(...)):
    """Store a logo for use by a `logo` overlay and return its id.

    Re-encoded through PIL rather than written straight to disk: that rejects
    anything that is not really an image, and drops whatever else the uploaded
    file may have carried.
    """
    from PIL import Image

    logo_id = uuid.uuid4().hex[:16]
    dest = os.path.join(LOGO_DIR, f"{logo_id}.png")
    try:
        img = Image.open(logo.file)
        img.verify()          # structural check; consumes the stream
        logo.file.seek(0)
        img = Image.open(logo.file).convert("RGBA")
        img.thumbnail((2000, 2000), Image.LANCZOS)
        img.save(dest, "PNG")
    except Exception as e:
        raise HTTPException(400, f"Not a readable image: {e}") from e
    return {"logo_id": logo_id, "width": img.width, "height": img.height}


@app.post("/api/render", response_model=JobInfo)
async def render_script(req: RenderRequest, bg: BackgroundTasks):
    """Render a (possibly edited) script draft into the final video."""
    if not req.script.scenes:
        raise HTTPException(400, "Script must have at least one scene")

    mode = "video" if req.video_job_id else ("image" if req.image_job_id else "topic")
    gen_req = TopicRequest(
        topic=req.script.title or "Promo",
        tone=req.tone,
        duration_sec=max(5, int(sum(s.duration_sec for s in req.script.scenes)) or 15),
        language=req.language,
        voice=req.voice,
        music=req.music,
        aspect_ratio=req.aspect_ratio,
        caption_style=req.caption_style,
        transition=req.transition,
        motion=req.motion,
        overlays=_resolve_overlays(req.overlays),
    )

    image_paths = _stashed_files(req.image_job_id, "upload_")
    video_paths = _stashed_files(req.video_job_id, "clip_")

    job_id = uuid.uuid4().hex[:12]
    job = JobInfo(id=job_id, mode=mode, status=JobStatus.QUEUED)
    JOBS[job_id] = job
    bg.add_task(_run_job, job_id, gen_req, image_paths, req.script, video_paths)
    return job


# --- One-shot workflow (generate everything in one call) --------------------
@app.post("/api/generate/topic", response_model=JobInfo)
async def generate_topic(req: TopicRequest, bg: BackgroundTasks):
    req.overlays = _resolve_overlays(req.overlays)
    job_id = uuid.uuid4().hex[:12]
    job = JobInfo(id=job_id, mode="topic", status=JobStatus.QUEUED)
    JOBS[job_id] = job
    bg.add_task(_run_job, job_id, req)
    return job


@app.post("/api/generate/image", response_model=JobInfo)
async def generate_image(
    bg: BackgroundTasks,
    topic: str = Form(...),
    key_points: str = Form(""),
    tone: Tone = Form(Tone.ENERGETIC),
    duration_sec: int = Form(15),
    language: str = Form("en"),
    voice: str = Form("default"),
    music: bool = Form(True),
    aspect_ratio: AspectRatio = Form(AspectRatio.VERTICAL),
    caption_style: CaptionStyle = Form(CaptionStyle.POP),
    transition_type: TransitionType = Form(TransitionType.CROSSFADE),
    transition_duration_sec: float = Form(0.5),
    fade_in: bool = Form(True),
    fade_out: bool = Form(True),
    motion_type: MotionType = Form(MotionType.AUTO),
    motion_intensity: MotionIntensity = Form(MotionIntensity.MEDIUM),
    overlays: str | None = Form(None),
    images: list[UploadFile] = File(...),
):
    if not images:
        raise HTTPException(400, "At least one image is required")

    job_id = uuid.uuid4().hex[:12]
    jdir = _job_dir(job_id)
    os.makedirs(jdir, exist_ok=True)

    saved: list[str] = []
    for idx, up in enumerate(images):
        dest = os.path.join(jdir, f"upload_{idx}{os.path.splitext(up.filename or '')[1] or '.jpg'}")
        with open(dest, "wb") as f:
            shutil.copyfileobj(up.file, f)
        saved.append(dest)

    req = ImageRequest(
        topic=topic,
        key_points=[p.strip() for p in key_points.split("\n") if p.strip()],
        tone=tone,
        duration_sec=duration_sec,
        language=language,
        voice=voice,
        music=music,
        aspect_ratio=aspect_ratio,
        caption_style=caption_style,
        transition=TransitionSettings(
            type=transition_type, duration_sec=transition_duration_sec,
            fade_in=fade_in, fade_out=fade_out,
        ),
        motion=MotionSettings(type=motion_type, intensity=motion_intensity),
        overlays=_parse_overlays(overlays),
    )
    job = JobInfo(id=job_id, mode="image", status=JobStatus.QUEUED)
    JOBS[job_id] = job
    bg.add_task(_run_job, job_id, req, saved)
    return job


@app.post("/api/generate/video", response_model=JobInfo)
async def generate_video(
    bg: BackgroundTasks,
    topic: str = Form(...),
    key_points: str = Form(""),
    tone: Tone = Form(Tone.ENERGETIC),
    duration_sec: int = Form(20),
    language: str = Form("en"),
    voice: str = Form("default"),
    music: bool = Form(True),
    aspect_ratio: AspectRatio = Form(AspectRatio.VERTICAL),
    caption_style: CaptionStyle = Form(CaptionStyle.POP),
    transition_type: TransitionType = Form(TransitionType.CROSSFADE),
    transition_duration_sec: float = Form(0.5),
    fade_in: bool = Form(True),
    fade_out: bool = Form(True),
    motion_type: MotionType = Form(MotionType.AUTO),
    motion_intensity: MotionIntensity = Form(MotionIntensity.MEDIUM),
    overlays: str | None = Form(None),
    videos: list[UploadFile] = File(...),
):
    """Movie-CF mode in one shot: upload footage, get the finished promo."""
    if not videos:
        raise HTTPException(400, "At least one video clip is required")

    job_id = uuid.uuid4().hex[:12]
    jdir = _job_dir(job_id)
    os.makedirs(jdir, exist_ok=True)

    saved: list[str] = []
    for idx, up in enumerate(videos):
        dest = os.path.join(jdir, f"clip_{idx}{os.path.splitext(up.filename or '')[1] or '.mp4'}")
        with open(dest, "wb") as f:
            shutil.copyfileobj(up.file, f)
        saved.append(dest)

    req = TopicRequest(
        topic=topic,
        key_points=[p.strip() for p in key_points.split("\n") if p.strip()],
        tone=tone,
        duration_sec=duration_sec,
        language=language,
        voice=voice,
        music=music,
        aspect_ratio=aspect_ratio,
        caption_style=caption_style,
        transition=TransitionSettings(
            type=transition_type, duration_sec=transition_duration_sec,
            fade_in=fade_in, fade_out=fade_out,
        ),
        motion=MotionSettings(type=motion_type, intensity=motion_intensity),
        overlays=_parse_overlays(overlays),
    )
    job = JobInfo(id=job_id, mode="video", status=JobStatus.QUEUED)
    JOBS[job_id] = job
    bg.add_task(_run_job, job_id, req, None, None, saved)
    return job


@app.get("/api/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}/video")
async def get_video(job_id: str):
    path = os.path.join(_job_dir(job_id), "final.mp4")
    if not os.path.exists(path):
        raise HTTPException(404, "Video not ready")
    return FileResponse(path, media_type="video/mp4", filename=f"promo_{job_id}.mp4")
