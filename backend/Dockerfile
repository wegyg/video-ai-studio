# Backend image: FastAPI + ffmpeg + the fonts the renderer needs.
#
# Build context is ./backend (see render.yaml).
FROM python:3.11-slim

# ffmpeg does the rendering. Both font packages matter and neither is optional:
#   fonts-dejavu-core  Latin captions. Without a real TTF, PIL falls back to a
#                      tiny bitmap font and captions come out unreadable.
#   fonts-noto-cjk     Korean/Japanese/Chinese glyphs. Without them PIL draws an
#                      empty "tofu" box per character. Debian ships only the
#                      Regular face here, which is why the renderer looks fonts up
#                      by pattern instead of by exact filename.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so edits to app code do not re-run the install layer.
# gTTS is an optional extra in pyproject.toml but the free voice path needs it,
# so it is installed here explicitly.
RUN pip install --no-cache-dir \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.30.0" \
        "pydantic>=2.9.0" \
        "pydantic-settings>=2.5.0" \
        "python-multipart>=0.0.12" \
        "httpx>=0.27.0" \
        "pillow>=10.4.0" \
        "gTTS>=2.5.0"

COPY app ./app

ENV PYTHONUNBUFFERED=1

# Free hosts give no persistent disk, so write where a container can always
# write. Renders are lost on restart either way; see docs/deploy.md.
ENV OUTPUT_DIR=/tmp/output

# Output height. This is what decides whether a render survives on a small
# instance, so the default is set for the smallest common one (512 MB).
# Measured peak (app + ffmpeg) for a 5-scene 9:16 video in this image:
#   1080 -> over 700 MB     540 -> 566 MB
#    480 -> 474 MB          432 -> 435 MB
# 432 leaves ~77 MB of headroom on 512 MB. Raise it to 720 or 1080 on an
# instance with 2 GB or more — quality improves a lot.
ENV VIDEO_BASE_HEIGHT=432

EXPOSE 8000

# Render (and most PaaS) inject PORT and expect the app to bind it.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
