"""End-to-end HTTP test against the running server: topic + image modes."""

import io
import time

import httpx
from PIL import Image

BASE = "http://127.0.0.1:8000"


def poll(job_id: str) -> dict:
    for _ in range(60):
        r = httpx.get(f"{BASE}/api/jobs/{job_id}", timeout=10).json()
        print(f"  {r['status']:>10}  {r['progress']:>3}%  {r['message']}")
        if r["status"] in ("done", "error"):
            return r
        time.sleep(2)
    raise TimeoutError("job did not finish")


def test_topic() -> None:
    print("\n=== TOPIC MODE ===")
    r = httpx.post(
        f"{BASE}/api/generate/topic",
        json={
            "topic": "BrewJoy Coffee",
            "key_points": ["Freshly roasted daily", "Free delivery", "50% off first order"],
            "tone": "energetic",
            "duration_sec": 16,
            "language": "en",
        },
        timeout=10,
    ).json()
    res = poll(r["id"])
    assert res["status"] == "done", res
    vid = httpx.get(f"{BASE}{res['video_url']}", timeout=30)
    assert vid.status_code == 200 and vid.headers["content-type"] == "video/mp4"
    print(f"  ✅ topic video: {len(vid.content)/1024:.1f} KB  providers={res['providers']}")


def test_image() -> None:
    print("\n=== IMAGE MODE ===")
    # build two fake product photos in-memory
    files = []
    for i, color in enumerate([(230, 90, 60), (60, 120, 230)]):
        buf = io.BytesIO()
        Image.new("RGB", (800, 800), color).save(buf, "JPEG")
        buf.seek(0)
        files.append(("images", (f"prod{i}.jpg", buf, "image/jpeg")))
    r = httpx.post(
        f"{BASE}/api/generate/image",
        data={
            "topic": "Aura Sneakers",
            "key_points": "Ultra light\nAll-day comfort\nLimited drop",
            "tone": "luxury",
            "duration_sec": 14,
            "language": "en",
            "voice": "default",
        },
        files=files,
        timeout=15,
    ).json()
    res = poll(r["id"])
    assert res["status"] == "done", res
    vid = httpx.get(f"{BASE}{res['video_url']}", timeout=30)
    assert vid.status_code == 200
    print(f"  ✅ image video: {len(vid.content)/1024:.1f} KB  providers={res['providers']}")


if __name__ == "__main__":
    print("health:", httpx.get(f"{BASE}/api/health", timeout=10).json())
    test_topic()
    test_image()
    print("\n🎉 All end-to-end HTTP tests passed.")
