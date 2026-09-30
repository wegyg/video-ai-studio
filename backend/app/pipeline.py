"""Generation pipeline orchestrator.

Runs the full flow for a job:
  script -> per-scene (visual + narration TTS) -> render scenes -> concat -> mux
Progress is reported back through a JobInfo object as it advances.
"""

from __future__ import annotations

import os

from app.config import Settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    ImageRequest,
    JobInfo,
    JobStatus,
    Script,
    Tone,
    TopicRequest,
)
from app.providers.registry import ProviderRegistry
from app.render import Renderer, SceneClip

# Tone -> accent color (used for caption accent bar / underline).
TONE_ACCENT: dict[Tone, tuple[int, int, int]] = {
    Tone.ENERGETIC: (255, 82, 82),      # vivid red
    Tone.PROFESSIONAL: (56, 132, 255),  # confident blue
    Tone.FRIENDLY: (255, 184, 46),      # warm amber
    Tone.LUXURY: (201, 162, 39),        # gold
    Tone.PLAYFUL: (124, 92, 255),       # purple
}


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.registry = ProviderRegistry(settings)

    async def generate_script(self, req: TopicRequest | ImageRequest) -> Script:
        """Stage 1 only: produce an editable script draft (no rendering)."""
        script_p = self.registry.script()
        return await script_p.generate(req)

    async def run(
        self,
        job: JobInfo,
        req: TopicRequest | ImageRequest,
        job_dir: str,
        image_paths: list[str] | None = None,
        script: Script | None = None,
        video_paths: list[str] | None = None,
    ) -> str:
        """Full flow. If `script` is provided (e.g. an edited draft), skip
        generation and render it directly. If `video_paths` are provided, the
        user's own footage is used as scene backgrounds (movie-CF mode)."""
        os.makedirs(job_dir, exist_ok=True)
        script_p = self.registry.script()
        tts_p = self.registry.tts()
        # User footage overrides the visual provider entirely.
        if video_paths:
            from app.providers.visual_providers import UserVideoProvider

            visuals_p = UserVideoProvider(video_paths)
            videogen_p = None  # don't AI-generate over the user's own footage
        else:
            visuals_p = self.registry.visuals()
            videogen_p = self.registry.videogen()  # premium image->video, or None
        job.providers = {**self.registry.summary(), "visuals": visuals_p.name}
        if video_paths:
            job.providers["videogen"] = "user-footage"

        # Per-request output dimensions + caption style.
        ratio = getattr(req, "aspect_ratio", None) or AspectRatio.VERTICAL
        w, h = ratio.dimensions(base=1080)
        caption_style = getattr(req, "caption_style", None) or CaptionStyle.POP
        renderer = Renderer(w, h, self.s.video_fps)

        # 1) Script (generate, or use the caller-supplied edited draft) ---
        job.status = JobStatus.SCRIPTING
        job.progress = 10
        if script is None:
            job.message = f"Writing script ({script_p.name})"
            script = await script_p.generate(req)
        else:
            job.message = "Using edited script"

        n = len(script.scenes)
        scene_clips: list[SceneClip] = []

        # 2) Per-scene visuals + narration -------------------------------
        for i, scene in enumerate(script.scenes):
            job.status = JobStatus.VISUALS
            job.progress = 15 + int((i / max(n, 1)) * 45)
            job.message = f"Scene {i + 1}/{n}: visuals ({visuals_p.name}) + voice ({tts_p.name})"

            img_path = os.path.join(job_dir, f"scene_{i}.jpg")
            asset = await visuals_p.get_visual(
                scene.visual_query, img_path,
                width=w, height=h,
                existing_images=image_paths, index=i,
            )

            # Premium: animate the (product) still into a real AI clip.
            # Only when a videogen provider is configured AND we have a still
            # image to animate. Any failure falls back to the still/Ken Burns.
            if videogen_p is not None and asset.kind == "image":
                job.message = f"Scene {i + 1}/{n}: AI video ({videogen_p.name})"
                gen_out = os.path.join(job_dir, f"scene_{i}_ai.mp4")
                try:
                    await videogen_p.animate(
                        asset.path, gen_out,
                        prompt=scene.visual_query,
                        duration_sec=min(max(scene.duration_sec, 3.0), 6.0),
                        width=w, height=h,
                    )
                    asset.path, asset.kind = gen_out, "video"
                except Exception:
                    pass  # keep the still; render falls back to Ken Burns

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
                    image_path=asset.path,
                    caption=scene.text,
                    duration=scene.duration_sec,
                    audio_path=audio_path,
                    accent=TONE_ACCENT.get(req.tone, (124, 92, 255)),
                    is_hook=(i == 0),
                    kind=asset.kind,
                    caption_style=caption_style.value,
                )
            )

        # 3) Render each scene -------------------------------------------
        job.status = JobStatus.RENDERING
        rendered: list[str] = []
        for i, clip in enumerate(scene_clips):
            job.progress = 60 + int((i / max(n, 1)) * 25)
            job.message = f"Rendering scene {i + 1}/{n}"
            out = os.path.join(job_dir, f"clip_{i}.mp4")
            await renderer.render_scene(clip, out)
            rendered.append(out)

        # 4) Concat + mux -------------------------------------------------
        job.progress = 88
        job.message = "Stitching video"
        silent_video = os.path.join(job_dir, "video_silent.mp4")
        await renderer.concat_video(rendered, silent_video)

        # Narration is placed at each scene's real start time (measured from the
        # rendered clips, so frame quantisation can't drift) instead of being
        # concatenated back-to-back, which used to pull the voice ahead of the
        # captions by the per-scene padding.
        from app.render import _probe_duration as _probe_clip

        starts: list[float] = []
        acc = 0.0
        for path in rendered:
            starts.append(acc)
            acc += await _probe_clip(path)

        merged_audio = os.path.join(job_dir, "narration.m4a")
        await renderer.build_narration(
            list(zip(starts, [c.audio_path for c in scene_clips])), acc, merged_audio
        )

        job.progress = 95
        job.message = "Adding music & audio"
        final = os.path.join(job_dir, "final.mp4")

        from app.music import get_music
        from app.render import _probe_duration as _probe

        total = await _probe(silent_video)
        music_out = os.path.join(job_dir, "music.m4a")
        music_on = getattr(req, "music", True) and self.s.music_enabled
        music = await get_music(req.tone, total, music_out, enabled=music_on)
        await renderer.mux(silent_video, merged_audio, final, music_path=music)

        job.status = JobStatus.DONE
        job.progress = 100
        job.message = "Done"
        return final
