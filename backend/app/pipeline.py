"""Generation pipeline orchestrator.

Runs the full flow for a job:
  script -> per-scene (visual + narration TTS) -> render scenes -> concat -> mux
Progress is reported back through a JobInfo object as it advances.
"""

from __future__ import annotations

import os

from app.config import Settings
from app.models import (
    AUTO_MOTION_CYCLE,
    TRANSITION_MAX_SEC,
    TRANSITION_MIN_SEC,
    AspectRatio,
    CaptionStyle,
    MotionSettings,
    MotionType,
    ImageRequest,
    Overlay,
    JobInfo,
    JobStatus,
    Script,
    Tone,
    TopicRequest,
    TransitionSettings,
)
from app.graphics import render_overlay_png
from app.providers.registry import ProviderRegistry
from app.render import GraphicCue, Renderer, SceneClip

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

    def _attach_graphics(self, overlays: list[Overlay], scene_clips: list[SceneClip],
                         job_dir: str, renderer: Renderer) -> None:
        """Draw each overlay once, then cue it on every scene its window covers.

        Scenes are rendered as separate clips, so an overlay spanning a boundary
        has to be cued on each scene it touches, with times rebased to that
        scene. Only the scene the overlay actually arrives in fades it in, and
        only the one it leaves in fades it out — otherwise it would blink at
        every boundary it crosses.
        """
        if not overlays:
            return
        durations = [c.duration for c in scene_clips]
        starts, acc = [], 0.0
        for d in durations:
            starts.append(acc)
            acc += d
        total = acc

        for oi, ov in enumerate(overlays):
            png = os.path.join(job_dir, f"graphic_{oi}.png")
            try:
                # pick a font that can draw this overlay's own text, so a Korean
                # label does not come out as empty boxes
                drawn = render_overlay_png(ov, renderer.w, renderer.h, png,
                                           renderer.font_for(ov.text))
            except Exception:
                drawn = None
            if not drawn:
                continue  # nothing to show (e.g. empty text, missing logo file)
            g_start, g_end = ov.window(starts, durations, total)
            for i, (s_start, s_dur) in enumerate(zip(starts, durations)):
                s_end = s_start + s_dur
                lo, hi = max(g_start, s_start), min(g_end, s_end)
                if hi - lo <= 0.01:
                    continue  # this scene is outside the overlay's window
                scene_clips[i].graphics.append(
                    GraphicCue(
                        png_path=drawn,
                        start=round(lo - s_start, 3),
                        end=round(hi - s_start, 3),
                        fade=min(ov.fade_sec, max(0.0, (hi - lo) / 2)),
                        fade_in=abs(lo - g_start) < 0.01,
                        fade_out=abs(hi - g_end) < 0.01,
                    )
                )

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
        # Camera movement: scene override > project default. AUTO walks a cycle so
        # neighbouring scenes never move the same way.
        mset: MotionSettings = getattr(req, "motion", None) or MotionSettings()

        def motion_for(index: int) -> MotionType:
            chosen = script.scenes[index].motion or mset.type
            if chosen is MotionType.AUTO:
                return AUTO_MOTION_CYCLE[index % len(AUTO_MOTION_CYCLE)]
            return chosen

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
                    motion=motion_for(i).value,
                    motion_intensity=(scene.motion_intensity or mset.intensity).value,
                )
            )

        # 2b) Graphic overlays -------------------------------------------
        # Each scene occupies exactly its own duration on the finished timeline
        # (transitions eat padding, not content), so a scene's start is just the
        # durations before it. That lets an overlay's timeline window be split
        # across scenes here, before anything is rendered.
        self._attach_graphics(getattr(req, "overlays", None) or [], scene_clips,
                              job_dir, renderer)

        # 3) Transition plan ---------------------------------------------
        # One entry per scene boundary. A scene may override the project default.
        # Each transition is clamped so it can never swallow a whole scene, and
        # quantised to whole frames so offsets stay exact.
        tset: TransitionSettings = getattr(req, "transition", None) or TransitionSettings()
        fps = self.s.video_fps
        plan: list[tuple[str | None, float]] = []
        for i in range(n - 1):
            kind = script.scenes[i].transition or tset.type
            name = kind.xfade_name
            dur = 0.0
            if name:
                dur = min(max(tset.duration_sec, TRANSITION_MIN_SEC), TRANSITION_MAX_SEC)
                dur = min(dur, 0.4 * min(scene_clips[i].duration, scene_clips[i + 1].duration))
                dur = round(dur * fps) / fps
                if dur < 0.1:  # scene too short to transition into
                    name, dur = None, 0.0
            plan.append((name, dur))
        # Extra footage each scene needs so the transition has something to eat.
        pads = [plan[i][1] if i < len(plan) else 0.0 for i in range(n)]
        edge_fade = round(tset.duration_sec * fps) / fps

        # 4) Render each scene -------------------------------------------
        job.status = JobStatus.RENDERING
        rendered: list[str] = []
        for i, clip in enumerate(scene_clips):
            job.progress = 60 + int((i / max(n, 1)) * 25)
            job.message = f"Rendering scene {i + 1}/{n}"
            out = os.path.join(job_dir, f"clip_{i}.mp4")
            await renderer.render_scene(clip, out, tail_pad=pads[i])
            rendered.append(out)

        # 5) Concat + mux -------------------------------------------------
        job.progress = 88
        job.message = "Stitching video"
        silent_video = os.path.join(job_dir, "video_silent.mp4")
        if any(name for name, _ in plan) or tset.fade_in or tset.fade_out:
            await renderer.concat_with_transitions(
                rendered, plan, silent_video,
                fade_in=edge_fade if tset.fade_in else 0.0,
                fade_out=edge_fade if tset.fade_out else 0.0,
            )
        else:
            # all cuts and no edge fades -> the original stream-copy fast path
            await renderer.concat_video(rendered, silent_video)

        # Narration is placed at each scene's real start time (measured from the
        # rendered clips, so frame quantisation can't drift) instead of being
        # concatenated back-to-back, which used to pull the voice ahead of the
        # captions by the per-scene padding.
        from app.render import _probe_duration as _probe_clip

        starts: list[float] = []
        acc = 0.0
        for path, pad in zip(rendered, pads):
            starts.append(acc)
            acc += await _probe_clip(path) - pad  # the pad is eaten by the transition

        merged_audio = os.path.join(job_dir, "narration.m4a")
        video_len = await _probe_clip(silent_video)
        await renderer.build_narration(
            list(zip(starts, [c.audio_path for c in scene_clips])),
            video_len or acc,
            merged_audio,
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
        await renderer.mux(
            silent_video, merged_audio, final, music_path=music,
            fade_in=edge_fade if tset.fade_in else 0.0,
            fade_out=edge_fade if tset.fade_out else 0.0,
        )

        job.status = JobStatus.DONE
        job.progress = 100
        job.message = "Done"
        return final
