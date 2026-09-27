"""Generate a video in-process and extract preview frames as a contact sheet."""

import asyncio
import os
import subprocess

from app.config import get_settings
from app.models import JobInfo, TopicRequest, Tone
from app.pipeline import Pipeline


async def main() -> None:
    settings = get_settings()
    settings.tts_provider = "silent"  # offline, deterministic
    pipe = Pipeline(settings)

    req = TopicRequest(
        topic="BrewJoy Coffee",
        key_points=["Freshly roasted daily", "Delivered to your door", "50% off first bag"],
        tone=Tone.ENERGETIC,
        duration_sec=16,
    )
    job = JobInfo(id="preview", mode="topic")
    job_dir = os.path.join(settings.output_dir, "preview")
    final = await pipe.run(job, req, job_dir)
    print("video:", final)

    # extract 4 frames spread across the clip into a 2x2 contact sheet
    sheet = os.path.join(job_dir, "contact_sheet.jpg")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", final,
            "-vf", "fps=1/3,scale=360:-1,tile=2x2",
            "-frames:v", "1", sheet,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("sheet:", sheet)


if __name__ == "__main__":
    asyncio.run(main())
