"""Script generation providers.

FreeScriptProvider  - template/heuristic based, no API key, always works.
OpenAIScriptProvider - uses an LLM for richer scripts when OPENAI_API_KEY is set.
"""

from __future__ import annotations

import json
import textwrap

from app.config import Settings
from app.models import ImageRequest, Scene, Script, TopicRequest, Tone
from app.providers.base import ScriptProvider

# --- Tone flavour used by the free template engine ---------------------------
_TONE_HOOKS: dict[Tone, list[str]] = {
    Tone.ENERGETIC: ["Stop scrolling! 🔥", "This changes everything.", "You NEED to see this."],
    Tone.PROFESSIONAL: ["Introducing {topic}.", "Meet {topic}.", "The smarter way to {topic}."],
    Tone.FRIENDLY: ["Hey! Let's talk about {topic} 👋", "So... you'll love this.", "Meet your new favorite."],
    Tone.LUXURY: ["Crafted for the few.", "Elevate everything.", "Pure. Refined. {topic}."],
    Tone.PLAYFUL: ["Okay this is kinda genius 😎", "Plot twist:", "Warning: highly addictive."],
}
_TONE_CTA: dict[Tone, str] = {
    Tone.ENERGETIC: "Tap the link now! 🚀",
    Tone.PROFESSIONAL: "Learn more today.",
    Tone.FRIENDLY: "Come check it out 💛",
    Tone.LUXURY: "Discover the collection.",
    Tone.PLAYFUL: "Go on, you know you want to 😉",
}


class FreeScriptProvider(ScriptProvider):
    name = "free"

    async def generate(self, req: TopicRequest | ImageRequest) -> Script:
        topic = req.topic.strip()
        tone = req.tone
        hook = _TONE_HOOKS[tone][0].format(topic=topic)
        cta = _TONE_CTA[tone]

        points = list(req.key_points) or self._auto_points(topic)
        # Distribute duration across a hook scene + point scenes + cta scene.
        n_scenes = min(len(points), 4) + 1  # +1 hook (cta folded into last)
        per = max(2.0, round(req.duration_sec / max(n_scenes, 1), 1))

        scenes: list[Scene] = [
            Scene(
                text=hook,
                narration=hook,
                visual_query=f"{topic} lifestyle background dynamic",
                duration_sec=per,
            )
        ]
        for p in points[:4]:
            scenes.append(
                Scene(
                    text=p,
                    narration=p,
                    visual_query=f"{topic} {p}",
                    duration_sec=per,
                )
            )
        scenes.append(
            Scene(
                text=cta,
                narration=cta,
                visual_query=f"{topic} logo clean background",
                duration_sec=per,
            )
        )
        return Script(title=topic, hook=hook, scenes=scenes, cta=cta)

    @staticmethod
    def _auto_points(topic: str) -> list[str]:
        return [
            f"Everything you wanted from {topic}.",
            "Fast, simple, and made for you.",
            "Thousands already made the switch.",
        ]


class OpenAIScriptProvider(ScriptProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def generate(self, req: TopicRequest | ImageRequest) -> Script:
        # Imported lazily so the app runs without the optional dependency.
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        prompt = textwrap.dedent(
            f"""
            You are a viral short-form (Reels/Shorts) scriptwriter for promo videos.
            Write a punchy vertical video script.

            Product/Topic: {req.topic}
            Key points: {", ".join(req.key_points) or "infer sensible ones"}
            Tone: {req.tone.value}
            Target length: ~{req.duration_sec} seconds
            Language: {req.language}

            Return STRICT JSON with this shape:
            {{
              "title": str,
              "hook": str,
              "scenes": [{{"text": str, "narration": str, "visual_query": str, "duration_sec": number}}],
              "cta": str
            }}
            - 3 to 6 scenes. Sum of duration_sec ~= target length.
            - "text" is the short on-screen caption; "narration" is spoken (can match).
            - "visual_query" is a concise English search term for stock/AI visuals.
            Output ONLY the JSON.
            """
        ).strip()

        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.8,
        )
        data = json.loads(resp.choices[0].message.content)
        return Script(
            title=data.get("title", req.topic),
            hook=data.get("hook", ""),
            scenes=[Scene(**s) for s in data["scenes"]],
            cta=data.get("cta", ""),
        )
