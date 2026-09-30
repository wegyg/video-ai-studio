# 🎬 Video AI Studio

Generate promotional **Reels / Shorts** (9:16 vertical video) from either a
**topic/brief** or your **product photos** — with an AI pipeline that runs
**fully free out of the box** and upgrades to premium providers the moment you
add API keys.

> Think "CapCut-style promo generator", but the intelligence is in *orchestrating*
> the best available AI for each stage (script → voice → visuals → render).

---

## ✨ Features

- **Two generation modes**
  - ✍️ **From Topic** — enter a product/brief, get a scripted promo short.
  - 🖼️ **From Photos** — upload product images, get an animated ad reel.
- **Free tier & Premium tier** — same app, keys unlock quality:
  | Stage | 🆓 Free (default) | 💎 Premium (auto-detected via API key) |
  |-------|----------------|-------------------------------------|
  | Script | Template engine | OpenAI LLM |
  | Voice | gTTS (free) → silent fallback | OpenAI TTS |
  | Visuals | Gradient cards / photo compositing | Pexels stock video (free key) |
  | **Video** | **Ken Burns zoom** | **fal.ai / Runway image-to-video** (animate product photos) |
  | Music | Procedural bed | Procedural bed (or your own tracks) |

  Every stage is a pluggable provider (adapter pattern). With **zero keys** the
  app produces a complete video; each key you add upgrades one stage — and if a
  premium call fails, it **falls back to the free path** so a render never breaks.
- **Auto-fallback**: with zero keys the app still produces a complete video.
- **9:16 / 1:1 / 16:9 rendering** via FFmpeg — Ken Burns zoom + burned-in animated captions
- **Scene transitions** — crossfade, fade through black/white, slide, zoom (xfade), with start/end
  fades and a per-scene override. Transitions overlap padded footage, so the timeline length and the
  voice/caption sync never shift
  + narration + optional background music.
- **Next.js UI** with live job progress and in-browser video preview + download.

---

## 🏗️ Architecture

```
frontend/ (Next.js + TS + Tailwind)
   └─ proxies /api/* ──▶ backend/ (FastAPI)
                              ├─ providers/   ← adapter interfaces + free/paid impls
                              │    ├─ script_providers.py
                              │    ├─ tts_providers.py
                              │    ├─ visual_providers.py
                              │    └─ registry.py   ← "auto" resolution + fallback
                              ├─ pipeline.py  ← orchestrates the stages
                              └─ render.py    ← FFmpeg + PIL caption compositing
```

Adding a new AI provider = implement one interface in `providers/` and register
it in `registry.py`. Nothing else changes.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+ (or [uv](https://docs.astral.sh/uv/)), Node.js 18+
- FFmpeg — installed for you by `scripts/setup_ffmpeg.sh` (no system packages needed)

### 0) One-time environment setup
```bash
bash scripts/setup_ffmpeg.sh   # static FFmpeg with the filters we need, on PATH
bash scripts/setup_python.sh   # backend/.venv + dependencies
```
Both scripts are idempotent — run them as often as you like. `run_server.sh` and
`run_e2e.sh` call them on start, so the usual flow needs no manual step.

### 1) Backend
```bash
cd backend
cp .env.example .env                  # optional: add API keys
bash run_server.sh                    # serves on http://127.0.0.1:8000
```

### 2) Frontend
```bash
cd frontend
npm install
npm run dev                           # http://localhost:3000
```

Open http://localhost:3000, pick a mode, and generate. 🎉

---

## 🔌 Free tier → Premium tier

The **free tier needs no keys at all**. Premium is **opt-in via `.env`** — no code changes:

```env
OPENAI_API_KEY=sk-...     # smarter scripts + natural TTS voices
PEXELS_API_KEY=...        # real stock footage (FREE key at pexels.com/api)

# Premium image-to-video (animate product photos into real AI clips):
FAL_API_KEY=...           # fal.ai — one key reaches Kling / Runway / Veo / etc.
FAL_VIDEO_MODEL=fal-ai/kling-video/v2/master/image-to-video
# or Runway's native API:
RUNWAY_API_KEY=...
RUNWAY_VIDEO_MODEL=gen4_turbo
```

Provider selection per stage (`auto` | `free`/`off` | `<name>`):
```env
SCRIPT_PROVIDER=auto
TTS_PROVIDER=auto
VISUALS_PROVIDER=auto
VIDEOGEN_PROVIDER=auto     # auto -> fal/runway if key present, else Ken Burns
```
`auto` = use the best provider your keys allow, else fall back to free.
The UI shows a **🆓 Free tier / 💎 Premium tier active** badge based on what's configured.

---

## 🧪 Tests

```bash
cd backend
.venv/bin/python test_pipeline.py     # offline pipeline smoke test
bash run_e2e.sh                       # full HTTP test (topic + image modes)
```

---

## ✂️ Editing workflow

Two ways to create a video:

- **⚡ Quick Generate** — one call, full video (`POST /api/generate/topic` | `/image`).
- **📝 Review & Edit** — generate an editable script first, tweak it, then render:
  1. `POST /api/script/topic` (or `/api/script/image` with photos) → returns a
     `ScriptDraft` (scenes with caption, narration, visual query, duration).
  2. Edit scenes in the timeline UI (reorder, retime, rewrite, add/remove).
  3. `POST /api/render` with the edited script → renders the final MP4.

  Image-mode uploads are stashed under an `image_job_id` so the render step
  reuses the same product photos.

## 🗺️ Roadmap ideas

- [ ] Wire up Runway/Kling image-to-video generation (stubs exist)
- [x] Music library + procedural background music
- [x] Editable timeline in the UI before final render
- [ ] Multiple aspect ratios (1:1, 16:9)
- [ ] Persist jobs in Redis/DB + a render queue for scale

---

## 📄 License

MIT — build something great.
