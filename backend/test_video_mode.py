"""Test movie-CF mode: upload user footage -> script -> render over it."""

import os
import subprocess
import time

os.environ.setdefault("TTS_PROVIDER", "silent")
os.environ.setdefault("MUSIC_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _make_test_clip(path: str, color: str, secs: int = 4) -> None:
    # a moving test pattern so we can confirm real footage is used
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=640x480:rate=30:duration={secs}",
         "-pix_fmt", "yuv420p", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _ = color


def main() -> None:
    os.makedirs("output/vtest", exist_ok=True)
    c1 = "output/vtest/a.mp4"
    c2 = "output/vtest/b.mp4"
    _make_test_clip(c1, "red")
    _make_test_clip(c2, "blue")

    print("=== upload footage + script ===")
    with open(c1, "rb") as f1, open(c2, "rb") as f2:
        r = client.post(
            "/api/script/video",
            data={
                "topic": "Summer Sale",
                "key_points": "Up to 50% off\nLimited time\nShop now",
                "tone": "energetic",
                "duration_sec": 16,
            },
            files=[
                ("videos", ("a.mp4", f1, "video/mp4")),
                ("videos", ("b.mp4", f2, "video/mp4")),
            ],
        )
    assert r.status_code == 200, r.text
    draft = r.json()
    print(f"  scenes: {len(draft['script']['scenes'])}  video_job_id: {draft['video_job_id']}")
    assert draft["video_job_id"], "no video_job_id returned"

    print("=== render over user footage (16:9, karaoke) ===")
    rr = client.post(
        "/api/render",
        json={
            "script": draft["script"],
            "tone": draft["tone"],
            "language": draft["language"],
            "voice": draft["voice"],
            "music": False,
            "aspect_ratio": "16:9",
            "caption_style": "karaoke",
            "video_job_id": draft["video_job_id"],
        },
    )
    assert rr.status_code == 200, rr.text
    job_id = rr.json()["id"]

    for _ in range(90):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(1)
    print(f"  status: {j['status']}  providers: {j['providers']}")
    assert j["status"] == "done", j
    assert j["providers"].get("visuals") == "uservideo", j["providers"]

    vid = client.get(j["video_url"])
    dim = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", j["video_url"].lstrip("/")],
        capture_output=True, text=True,
    )
    print(f"  ✅ CF video from user footage: {len(vid.content)/1024:.1f} KB")


if __name__ == "__main__":
    main()
    print("\n🎉 Movie-CF (user footage + AI treatment) works.")
