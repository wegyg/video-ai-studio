"""Test the two-step (script -> edit -> render) workflow via the HTTP app."""

import asyncio
import os
import time

from fastapi.testclient import TestClient

os.environ.setdefault("TTS_PROVIDER", "silent")  # offline, fast

from app.main import app  # noqa: E402

client = TestClient(app)


def test_topic_two_step() -> None:
    print("\n=== SCRIPT (topic) ===")
    r = client.post(
        "/api/script/topic",
        json={
            "topic": "BrewJoy Coffee",
            "key_points": ["Fresh daily", "Free delivery", "50% off"],
            "tone": "energetic",
            "duration_sec": 16,
            "language": "en",
        },
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    scenes = draft["script"]["scenes"]
    print(f"  draft scenes: {len(scenes)}")
    for s in scenes:
        print(f"    - [{s['duration_sec']}s] {s['text']!r}  (visual: {s['visual_query']!r})")

    # --- simulate USER EDITS: change first caption, drop last scene, retime ---
    scenes[0]["text"] = "☕ BrewJoy — wake up happy"
    scenes[0]["narration"] = "BrewJoy. Wake up happy."
    edited = scenes[:-1]
    edited[1]["duration_sec"] = 5.0
    draft["script"]["scenes"] = edited
    print(f"  after edits: {len(edited)} scenes, scene[0] retitled, scene[1]=5s")

    print("=== RENDER (edited) ===")
    rr = client.post(
        "/api/render",
        json={
            "script": draft["script"],
            "tone": draft["tone"],
            "language": draft["language"],
            "voice": draft["voice"],
            "music": draft["music"],
            "image_job_id": draft["image_job_id"],
        },
    )
    assert rr.status_code == 200, rr.text
    job_id = rr.json()["id"]

    for _ in range(60):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(1)
    print(f"  status: {j['status']}  msg: {j['message']}")
    assert j["status"] == "done", j
    vid = client.get(j["video_url"])
    assert vid.status_code == 200 and vid.headers["content-type"] == "video/mp4"
    print(f"  ✅ rendered edited script: {len(vid.content)/1024:.1f} KB")


if __name__ == "__main__":
    test_topic_two_step()
    print("\n🎉 Two-step timeline workflow passed.")
