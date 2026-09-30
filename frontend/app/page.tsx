"use client";

import { useEffect, useRef, useState } from "react";
import {
  AspectRatio,
  CaptionStyle,
  generateFromImages,
  generateFromTopic,
  getJob,
  JobInfo,
  renderScript,
  Script,
  ScriptDraft,
  scriptFromImages,
  scriptFromTopic,
  scriptFromVideos,
  generateFromVideos,
  Tone,
} from "@/lib/api";
import ProviderBadge from "@/components/ProviderBadge";
import JobProgress from "@/components/JobProgress";
import TimelineEditor from "@/components/TimelineEditor";

type Mode = "topic" | "image" | "video";

const TONES: Tone[] = ["energetic", "professional", "friendly", "luxury", "playful"];
const RATIOS: { value: AspectRatio; label: string }[] = [
  { value: "9:16", label: "9:16 Reels" },
  { value: "1:1", label: "1:1 Feed" },
  { value: "16:9", label: "16:9 YouTube" },
];
const CAPTION_STYLES: { value: CaptionStyle; label: string }[] = [
  { value: "pop", label: "Pop (word-by-word)" },
  { value: "karaoke", label: "Karaoke (highlight)" },
  { value: "static", label: "Static" },
];

export default function Home() {
  const [mode, setMode] = useState<Mode>("topic");

  // shared form state
  const [topic, setTopic] = useState("");
  const [keyPoints, setKeyPoints] = useState("");
  const [tone, setTone] = useState<Tone>("energetic");
  const [duration, setDuration] = useState(18);
  const [language, setLanguage] = useState("en");
  const [music, setMusic] = useState(true);
  const [ratio, setRatio] = useState<AspectRatio>("9:16");
  const [captionStyle, setCaptionStyle] = useState<CaptionStyle>("pop");
  const [files, setFiles] = useState<File[]>([]);
  const [videos, setVideos] = useState<File[]>([]);

  const [job, setJob] = useState<JobInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<ScriptDraft | null>(null); // editable script
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // poll job status until done/error
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getJob(job.id);
        setJob(updated);
      } catch {
        /* keep last known state */
      }
    }, 1200);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job?.id, job?.status]);

  function points(): string[] {
    return keyPoints
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function topicPayload() {
    return {
      topic,
      key_points: points(),
      tone,
      duration_sec: duration,
      language,
      voice: "default",
      music,
      aspect_ratio: ratio,
      caption_style: captionStyle,
    };
  }

  // Build a multipart form for image/video modes. `field` is "images"|"videos".
  function buildUploadForm(field: "images" | "videos", uploads: File[]): FormData | null {
    if (uploads.length === 0) {
      alert(field === "images" ? "Please upload at least one image." : "Please upload at least one video clip.");
      return null;
    }
    const fd = new FormData();
    fd.append("topic", topic);
    fd.append("key_points", points().join("\n"));
    fd.append("tone", tone);
    fd.append("duration_sec", String(duration));
    fd.append("language", language);
    fd.append("voice", "default");
    fd.append("music", String(music));
    fd.append("aspect_ratio", ratio);
    fd.append("caption_style", captionStyle);
    uploads.forEach((f) => fd.append(field, f));
    return fd;
  }

  // One-shot: generate the whole video immediately (no editing).
  // (Video mode always goes through the editable draft flow.)
  async function handleGenerate() {
    if (!topic.trim()) return;
    setBusy(true);
    setJob(null);
    setDraft(null);
    try {
      let created: JobInfo;
      if (mode === "topic") {
        created = await generateFromTopic(topicPayload());
      } else if (mode === "image") {
        const fd = buildUploadForm("images", files);
        if (!fd) {
          setBusy(false);
          return;
        }
        created = await generateFromImages(fd);
      } else {
        const fd = buildUploadForm("videos", videos);
        if (!fd) {
          setBusy(false);
          return;
        }
        created = await generateFromVideos(fd);
      }
      setJob(created);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Two-step: generate an editable script draft first.
  async function handleGenerateScript() {
    if (!topic.trim()) return;
    setBusy(true);
    setJob(null);
    setDraft(null);
    try {
      let d: ScriptDraft;
      if (mode === "topic") {
        d = await scriptFromTopic(topicPayload());
      } else if (mode === "image") {
        const fd = buildUploadForm("images", files);
        if (!fd) {
          setBusy(false);
          return;
        }
        d = await scriptFromImages(fd);
      } else {
        const fd = buildUploadForm("videos", videos);
        if (!fd) {
          setBusy(false);
          return;
        }
        d = await scriptFromVideos(fd);
      }
      // carry the UI ratio/caption choices into the draft for rendering
      d = { ...d, aspect_ratio: ratio, caption_style: captionStyle };
      setDraft(d);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Render the (possibly edited) draft.
  async function handleRender() {
    if (!draft) return;
    setBusy(true);
    setJob(null);
    try {
      const created = await renderScript(draft);
      setJob(created);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function updateScript(script: Script) {
    if (draft) setDraft({ ...draft, script });
  }

  const done = job?.status === "done" && job.video_url;
  const rendering = job !== null && job.status !== "done" && job.status !== "error";

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <header className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            🎬 Video AI Studio
          </h1>
          <p className="mt-1 text-white/60">
            Generate promo Reels &amp; Shorts from a topic or product photos — edit
            the AI script, then render.
          </p>
        </div>
        <ProviderBadge />
      </header>

      <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
        {/* ---- Left: form ---- */}
        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
          {/* mode toggle */}
          <div className="mb-6 inline-flex rounded-xl border border-white/10 bg-black/20 p-1">
            {(["topic", "image", "video"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
                  mode === m ? "bg-brand text-white" : "text-white/60 hover:text-white"
                }`}
              >
                {m === "topic" ? "✍️ Topic" : m === "image" ? "🖼️ Photos" : "🎥 My Video"}
              </button>
            ))}
          </div>

          <div className="space-y-5">
            <Field
              label={
                mode === "topic"
                  ? "Product / Topic"
                  : mode === "image"
                  ? "Product name"
                  : "What is this video about?"
              }
            >
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. BrewJoy Coffee"
                className="input"
              />
            </Field>

            {mode === "image" && (
              <Field label="Product photos">
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                  className="block w-full text-sm text-white/70 file:mr-3 file:rounded-lg file:border-0 file:bg-brand file:px-4 file:py-2 file:text-white"
                />
                {files.length > 0 && (
                  <p className="mt-2 text-xs text-white/50">
                    {files.length} image(s) selected
                  </p>
                )}
              </Field>
            )}

            {mode === "video" && (
              <Field label="Your video clips">
                <input
                  type="file"
                  accept="video/*"
                  multiple
                  onChange={(e) => setVideos(Array.from(e.target.files ?? []))}
                  className="block w-full text-sm text-white/70 file:mr-3 file:rounded-lg file:border-0 file:bg-brand file:px-4 file:py-2 file:text-white"
                />
                {videos.length > 0 && (
                  <p className="mt-2 text-xs text-white/50">
                    {videos.length} clip(s) selected — AI will add captions, voice &amp; music
                  </p>
                )}
                <p className="mt-1 text-xs text-white/40">
                  💡 Upload footage (incl. downloaded from Google Drive) — AI turns it into a CF-style promo.
                </p>
              </Field>
            )}

            <Field label="Key points (one per line, optional)">
              <textarea
                value={keyPoints}
                onChange={(e) => setKeyPoints(e.target.value)}
                rows={3}
                placeholder={"Freshly roasted daily\nFree delivery\n50% off first order"}
                className="input resize-none"
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Tone">
                <select
                  value={tone}
                  onChange={(e) => setTone(e.target.value as Tone)}
                  className="input capitalize"
                >
                  {TONES.map((t) => (
                    <option key={t} value={t} className="bg-[#161226]">
                      {t}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Language">
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="input"
                >
                  <option value="en" className="bg-[#161226]">English</option>
                  <option value="ko" className="bg-[#161226]">한국어</option>
                  <option value="es" className="bg-[#161226]">Español</option>
                  <option value="ja" className="bg-[#161226]">日本語</option>
                </select>
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Format">
                <select
                  value={ratio}
                  onChange={(e) => setRatio(e.target.value as AspectRatio)}
                  className="input"
                >
                  {RATIOS.map((r) => (
                    <option key={r.value} value={r.value} className="bg-[#161226]">
                      {r.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Captions">
                <select
                  value={captionStyle}
                  onChange={(e) => setCaptionStyle(e.target.value as CaptionStyle)}
                  className="input"
                >
                  {CAPTION_STYLES.map((c) => (
                    <option key={c.value} value={c.value} className="bg-[#161226]">
                      {c.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <Field label={`Duration: ${duration}s`}>
              <input
                type="range"
                min={8}
                max={45}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-full accent-brand"
              />
            </Field>

            <button
              type="button"
              onClick={() => setMusic((m) => !m)}
              className="flex w-full items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm"
            >
              <span className="font-medium text-white/80">🎵 Background music</span>
              <span
                className={`relative h-6 w-11 rounded-full transition ${
                  music ? "bg-brand" : "bg-white/20"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
                    music ? "left-[22px]" : "left-0.5"
                  }`}
                />
              </span>
            </button>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={handleGenerateScript}
                disabled={busy || !topic.trim() || rendering}
                className="rounded-xl bg-brand py-3 font-semibold transition hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-40"
                title="Generate an editable script you can tweak before rendering"
              >
                {busy && !job ? "Working…" : "📝 Review & Edit"}
              </button>
              <button
                onClick={handleGenerate}
                disabled={busy || !topic.trim() || rendering}
                className="rounded-xl border border-white/15 py-3 font-semibold transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
                title="Skip editing and render straight away"
              >
                ⚡ Quick Generate
              </button>
            </div>
          </div>
        </section>

        {/* ---- Right: timeline editor OR preview / progress ---- */}
        {draft && !done ? (
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
            <TimelineEditor script={draft.script} onChange={updateScript} />
            <div className="mt-5 space-y-3">
              {job && <JobProgress job={job} />}
              <button
                onClick={handleRender}
                disabled={busy || rendering}
                className="w-full rounded-xl bg-brand py-3 font-semibold transition hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-40"
              >
                {rendering ? "Rendering…" : "🎬 Render Video"}
              </button>
              <button
                onClick={() => {
                  setDraft(null);
                  setJob(null);
                }}
                className="w-full rounded-xl border border-white/10 py-2 text-sm text-white/60 transition hover:bg-white/5"
              >
                ← Discard draft
              </button>
            </div>
          </section>
        ) : (
        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-white/50">
            Preview
          </h2>

          <div className="mx-auto flex aspect-[9/16] max-w-[280px] items-center justify-center overflow-hidden rounded-2xl border border-white/10 bg-black/40">
            {done ? (
              <video
                key={job!.video_url!}
                src={job!.video_url!}
                controls
                autoPlay
                loop
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="px-6 text-center text-sm text-white/40">
                {job ? "Rendering your video…" : "Your 9:16 video will appear here"}
              </div>
            )}
          </div>

          {job && (
            <div className="mt-5 space-y-4">
              <JobProgress job={job} />
              {done && (
                <>
                  <a
                    href={job!.video_url!}
                    download
                    className="block w-full rounded-xl border border-brand py-2.5 text-center font-medium text-brand transition hover:bg-brand hover:text-white"
                  >
                    ⬇ Download MP4
                  </a>
                  <button
                    onClick={() => {
                      setJob(null);
                      setDraft(null);
                    }}
                    className="block w-full rounded-xl border border-white/10 py-2 text-sm text-white/60 transition hover:bg-white/5"
                  >
                    ✨ Make another
                  </button>
                </>
              )}
            </div>
          )}
        </section>
        )}
      </div>

      <style jsx global>{`
        .input {
          width: 100%;
          border-radius: 0.75rem;
          border: 1px solid rgba(255, 255, 255, 0.1);
          background: rgba(0, 0, 0, 0.25);
          padding: 0.65rem 0.85rem;
          font-size: 0.9rem;
          outline: none;
        }
        .input:focus {
          border-color: #7c5cff;
        }
      `}</style>
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-white/70">{label}</span>
      {children}
    </label>
  );
}
