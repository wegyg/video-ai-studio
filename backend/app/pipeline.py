"""Generation pipeline orchestrator.

Runs the full flow for a job:
  script -> per-scene (visual + narration TTS) -> render scenes -> concat -> mux
Progress is reported back through a JobInfo object as it advances.
"""

from __future__ import annotations

import os

from app.config import Settings
from app.models import ImageRequest, JobInfo, JobStatus, Script, TopicRequest
from app.providers.registry import ProviderRegistry
from app.render import Renderer, SceneClip


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.registry = ProviderRegistry(settings)
        self.renderer = Renderer(settings.video_width, settings.video_height, settings.video_fps)

    async def run(
        self,
        job: JobInfo,
        req: TopicRequest | ImageRequest,
        job_dir: str,
        image_paths: list[str] | None = None,
    ) -> str:
        os.makedirs(job_dir, exist_ok=True)
        script_p = self.registry.script()
        tts_p = self.registry.tts()
        visuals_p = self.registry.visuals()
        job.providers = self.registry.summary()

        # 1) Script -------------------------------------------------------
        job.status = JobStatus.SCRIPTING
        job.progress = 10
        job.message = f"Writing script ({script_p.name})"
        script: Script = await script_p.generate(req)

        n = len(script.scenes)
        scene_clips: list[SceneClip] = []

        # 2) Per-scene visuals + narration -------------------------------
        for i, scene in enumerate(script.scenes):
            job.status = JobStatus.VISUALS
            job.progress = 15 + int((i / max(n, 1)) * 45)
            job.message = f"Scene {i + 1}/{n}: visuals ({visuals_p.name}) + voice ({tts_p.name})"

            img_path = os.path.join(job_dir, f"scene_{i}.jpg")
            await visuals_p.get_visual(
                scene.visual_query, img_path,
                width=self.s.video_width, height=self.s.video_height,
                existing_images=image_paths, index=i,
            )

            audio_path = os.path.join(job_dir, f"scene_{i}.m4a")
            await tts_p.synthesize(
                scene.narration, audio_path, language=req.language, voice=req.voice
            )
            # Sync scene duration to actual narration length (+padding).
            from app.render import _probe_duration

            spoken = await _probe_duration(audio_path)
            scene.duration_sec = max(scene.duration_sec, round(spoken + 0.6, 2))

            scene_clips.append(
                SceneClip(
                    image_path=img_path,
                    caption=scene.text,
                    duration=scene.duration_sec,
                    audio_path=audio_path,
                )
            )

        # 3) Render each scene -------------------------------------------
        job.status = JobStatus.RENDERING
        rendered: list[str] = []
        for i, clip in enumerate(scene_clips):
            job.progress = 60 + int((i / max(n, 1)) * 25)
            job.message = f"Rendering scene {i + 1}/{n}"
            out = os.path.join(job_dir, f"clip_{i}.mp4")
            await self.renderer.render_scene(clip, out)
            rendered.append(out)

        # 4) Concat + mux -------------------------------------------------
        job.progress = 88
        job.message = "Stitching video"
        silent_video = os.path.join(job_dir, "video_silent.mp4")
        await self.renderer.concat_video(rendered, silent_video)

        merged_audio = os.path.join(job_dir, "narration.m4a")
        await self.renderer.concat_audio(
            [c.audio_path or "" for c in scene_clips], merged_audio
        )

        job.progress = 95
        job.message = "Adding audio"
        final = os.path.join(job_dir, "final.mp4")
        music = _default_music_path()
        await self.renderer.mux(silent_video, merged_audio, final, music_path=music)

        job.status = JobStatus.DONE
        job.progress = 100
        job.message = "Done"
        return final


def _default_music_path() -> str | None:
    # Optional: drop a royalty-free loop at backend/assets/music.mp3 to enable.
    p = os.path.join(os.path.dirname(__file__), "..", "assets", "music.mp3")
    return p if os.path.exists(p) else None
