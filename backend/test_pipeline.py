"""Smoke test: run the pipeline in free mode and verify an MP4 is produced."""

import asyncio
import os

from app.config import get_settings
from app.models import JobInfo, JobStatus, TopicRequest, Tone
from app.pipeline import Pipeline


async def main() -> None:
    settings = get_settings()
    # Force free mode for the smoke test (silent TTS = no network needed).
    settings.tts_provider = "silent"
    pipe = Pipeline(settings)

    req = TopicRequest(
        topic="BrewJoy Coffee",
        key_points=[
            "Freshly roasted every morning",
            "Delivered to your door",
            "First bag 50% off",
        ],
        tone=Tone.ENERGETIC,
        duration_sec=18,
    )
    job = JobInfo(id="test", mode="topic")
    job_dir = os.path.join(settings.output_dir, "test")
    final = await pipe.run(job, req, job_dir)

    assert job.status == JobStatus.DONE, f"status={job.status} err={job.error}"
    assert os.path.exists(final), "final.mp4 missing"
    size = os.path.getsize(final)
    print(f"\n✅ Video produced: {final} ({size/1024:.1f} KB)")
    print(f"   Providers: {job.providers}")


if __name__ == "__main__":
    asyncio.run(main())
