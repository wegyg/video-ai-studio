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
- **Pluggable provider architecture** (adapter pattern) for every stage:
  | Stage | Free (default) | Upgrade (auto-detected via API key) |
  |-------|----------------|-------------------------------------|
  | Script | Template engine | OpenAI LLM |
  | Voice | gTTS (free) → silent fallback | OpenAI TTS |
  | Visuals | Gradient cards / photo compositing | Pexels stock (free key) |
  | Video model | — | Runway / Kling (stubs ready) |
- **Auto-fallback**: with zero keys the app still produces a complete video.
- **9:16 rendering** via FFmpeg — Ken Burns zoom + burned-in animated captions
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
- Python 3.11+, Node.js 18+
- **FFmpeg** on your PATH (`ffmpeg -version` should work)

### 1) Backend
```bash
cd backend
uv venv --python 3.11 .venv           # or: python3.11 -m venv .venv
uv pip install --python .venv/bin/python \
  fastapi "uvicorn[standard]" pydantic pydantic-settings \
  python-multipart httpx pillow gTTS
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

## 🔌 Enabling premium providers

Everything is **opt-in via `.env`** — no code changes needed:

```env
OPENAI_API_KEY=sk-...     # richer scripts + natural TTS voices
PEXELS_API_KEY=...        # real stock footage (free key at pexels.com/api)
RUNWAY_API_KEY=...        # (stub) full AI video generation
KLING_API_KEY=...         # (stub) full AI video generation
```

Provider selection per stage (`auto` | `free` | `<name>`):
```env
SCRIPT_PROVIDER=auto
TTS_PROVIDER=auto
VISUALS_PROVIDER=auto
```
`auto` = use the best provider your keys allow, else fall back to free.

---

## 🧪 Tests

```bash
cd backend
.venv/bin/python test_pipeline.py     # offline pipeline smoke test
bash run_e2e.sh                       # full HTTP test (topic + image modes)
```

---

## 🗺️ Roadmap ideas

- [ ] Wire up Runway/Kling image-to-video generation (stubs exist)
- [ ] Music library + beat-synced cuts
- [ ] Editable timeline in the UI before final render
- [ ] Multiple aspect ratios (1:1, 16:9)
- [ ] Persist jobs in Redis/DB + a render queue for scale

---

## 📄 License

MIT — build something great.
