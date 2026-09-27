"""FastAPI application: endpoints for topic->video and image->video generation."""

from __future__ import annotations

import os
import shutil
import uuid

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import get_settings
from app.models import ImageRequest, JobInfo, JobStatus, TopicRequest, Tone
from app.pipeline import Pipeline

settings = get_settings()
app = FastAPI(title="Video AI Studio", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
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


async def _run_job(job_id: str, req, image_paths=None):
    job = JOBS[job_id]
    try:
        final = await pipeline.run(job, req, _job_dir(job_id), image_paths=image_paths)
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
        "resolution": f"{settings.video_width}x{settings.video_height}@{settings.video_fps}",
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
            "runway_video": bool(s.runway_api_key),
            "kling_video": bool(s.kling_api_key),
        },
    }


@app.post("/api/generate/topic", response_model=JobInfo)
async def generate_topic(req: TopicRequest, bg: BackgroundTasks):
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
    )
    job = JobInfo(id=job_id, mode="image", status=JobStatus.QUEUED)
    JOBS[job_id] = job
    bg.add_task(_run_job, job_id, req, saved)
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
