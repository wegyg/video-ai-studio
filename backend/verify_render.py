"""Render verification harness.

Renders real MP4s offline (silent TTS, locally generated visuals) and reports a
table plus contact sheets so the output can be checked by eye.

Usage (from backend/, after ../scripts/setup_ffmpeg.sh):
    .venv/bin/python verify_render.py --ratios 9:16,1:1,16:9 --caption pop
    .venv/bin/python verify_render.py --ratios 9:16 --caption pop --word-sheet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess

from app.config import get_settings
from app.models import AspectRatio, CaptionStyle, JobInfo, Tone, TopicRequest
from app.pipeline import Pipeline

TOPIC = "BrewJoy Coffee"
POINTS = ["Freshly roasted daily", "Delivered to your door", "50% off the first bag"]


def probe(path: str, streams: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", streams, "-show_entries",
         "stream=width,height,duration,codec_type", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def media_info(path: str) -> dict:
    v = probe(path, "v:0")
    a = probe(path, "a:0")
    vs = (v.get("streams") or [{}])[0]
    as_ = (a.get("streams") or [{}])[0]
    vdur = float(vs.get("duration") or v.get("format", {}).get("duration") or 0)
    adur = float(as_.get("duration") or 0)
    return {
        "w": int(vs.get("width") or 0),
        "h": int(vs.get("height") or 0),
        "video_sec": round(vdur, 3),
        "audio_sec": round(adur, 3),
        "diff_sec": round(abs(vdur - adur), 3),
    }


def contact_sheet(video: str, out: str, times: list[float], cols: int, width: int = 260) -> str:
    """Tile the given timestamps into one image (labelled with the timestamp)."""
    tiles: list[str] = []
    for i, t in enumerate(times):
        p = f"{out}.f{i}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
             "-vf", f"scale={width}:-1,drawbox=y=0:h=26:c=black@0.55:t=fill",
             p],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        tiles.append(p)
    # stack with PIL so we can label each tile even without drawtext
    from PIL import Image, ImageDraw

    imgs = [Image.open(p) for p in tiles]
    tw, th = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (12, 10, 20))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(imgs):
        x, y = (i % cols) * tw, (i // cols) * th
        sheet.paste(im, (x, y))
        d.text((x + 8, y + 6), f"t={times[i]:.2f}s", fill=(255, 255, 255))
    sheet.save(out, "JPEG", quality=90)
    for p in tiles:
        os.remove(p)
    return out


async def render_one(ratio: AspectRatio, caption: CaptionStyle, out_dir: str, tag: str) -> str:
    settings = get_settings()
    settings.tts_provider = "silent"  # offline + deterministic
    pipe = Pipeline(settings)
    req = TopicRequest(
        topic=TOPIC, key_points=POINTS, tone=Tone.ENERGETIC, duration_sec=14,
        aspect_ratio=ratio, caption_style=caption,
    )
    job = JobInfo(id=tag, mode="topic")
    return await pipe.run(job, req, os.path.join(out_dir, tag))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratios", default="9:16,1:1,16:9")
    ap.add_argument("--caption", default="pop")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--word-sheet", action="store_true", help="extra sheet of the word-by-word reveal")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join(get_settings().output_dir, "verify")
    os.makedirs(out_dir, exist_ok=True)
    caption = CaptionStyle(args.caption)
    rows = []
    for r in args.ratios.split(","):
        ratio = AspectRatio(r.strip())
        tag = f"{r.replace(':', 'x')}_{caption.value}"
        video = await render_one(ratio, caption, out_dir, tag)
        info = media_info(video)
        info["ratio"] = r
        info["expected"] = "x".join(map(str, ratio.dimensions(base=1080)))
        info["ok"] = info["expected"] == f"{info['w']}x{info['h']}" and info["diff_sec"] <= 0.1
        sheet = contact_sheet(
            video, os.path.join(out_dir, f"sheet_{tag}.jpg"),
            [info["video_sec"] * f for f in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8)], cols=3,
        )
        info["sheet"] = os.path.relpath(sheet)
        if args.word_sheet:
            ws = contact_sheet(
                video, os.path.join(out_dir, f"words_{tag}.jpg"),
                [0.2, 0.7, 1.2, 1.7, 2.2, 2.7], cols=3,
            )
            info["word_sheet"] = os.path.relpath(ws)
        rows.append(info)
        print(f"  rendered {r}: {info}")

    print("\n| ratio | size | expected | video | audio | diff | ok |")
    print("|---|---|---|---|---|---|---|")
    for i in rows:
        print(f"| {i['ratio']} | {i['w']}x{i['h']} | {i['expected']} | {i['video_sec']}s "
              f"| {i['audio_sec']}s | {i['diff_sec']}s | {'PASS' if i['ok'] else 'FAIL'} |")
    print("\nsheets:", ", ".join(i["sheet"] for i in rows))
    if not all(i["ok"] for i in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
