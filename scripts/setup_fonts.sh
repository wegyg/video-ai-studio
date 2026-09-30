#!/usr/bin/env bash
# Install a CJK font so Korean / Japanese / Chinese captions render as text.
#
# Without one, PIL has no glyphs for those characters and draws an empty "tofu"
# box per character — a Korean caption came out as a row of rectangles. The
# renderer falls back to a Latin font when no CJK font is present, so this script
# is not required to run, but any non-Latin caption needs it.
#
# Safe to re-run: it exits immediately once a CJK font is visible.
set -e

have_cjk() {
  fc-list 2>/dev/null | grep -qiE "CJK|nanum|NotoSansKR"
}

if have_cjk; then
  echo "[fonts] CJK font already installed"
  exit 0
fi

echo "[fonts] installing a CJK font"
if command -v dnf >/dev/null 2>&1; then
  dnf install -y google-noto-sans-cjk-ttc-fonts >/dev/null 2>&1 || true
elif command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq fonts-noto-cjk >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache font-noto-cjk >/dev/null 2>&1 || true
fi

command -v fc-cache >/dev/null 2>&1 && fc-cache -f >/dev/null 2>&1 || true

if have_cjk; then
  echo "[fonts] ready: $(fc-list | grep -iE 'CJK|nanum' | head -1 | cut -d: -f1)"
else
  # Not fatal: Latin captions are unaffected, and the renderer degrades to the
  # Latin font rather than failing.
  echo "[fonts] WARNING: no CJK font available — Korean/Japanese/Chinese captions"
  echo "[fonts]          will render as empty boxes. Latin text is unaffected."
fi
