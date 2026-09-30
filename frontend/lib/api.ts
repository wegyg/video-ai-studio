// Thin client for the backend API (proxied via next.config rewrites).

export type JobStatus =
  | "queued"
  | "scripting"
  | "voicing"
  | "visuals"
  | "rendering"
  | "done"
  | "error";

export interface JobInfo {
  id: string;
  status: JobStatus;
  progress: number;
  message: string;
  mode: "topic" | "image" | "video";
  providers: Record<string, string>;
  video_url: string | null;
  error: string | null;
}

export interface ProvidersInfo {
  active: Record<string, string>;
  upgrades: Record<string, boolean>;
}

export type Tone = "energetic" | "professional" | "friendly" | "luxury" | "playful";

export type AspectRatio = "9:16" | "1:1" | "16:9";
export type CaptionStyle = "static" | "pop" | "karaoke";

export interface TopicPayload {
  topic: string;
  key_points: string[];
  tone: Tone;
  duration_sec: number;
  language: string;
  voice: string;
  music: boolean;
  aspect_ratio: AspectRatio;
  caption_style: CaptionStyle;
}

export interface Scene {
  text: string;
  narration: string;
  visual_query: string;
  duration_sec: number;
}

export interface Script {
  title: string;
  hook: string;
  scenes: Scene[];
  cta: string;
}

export interface ScriptDraft {
  script: Script;
  tone: Tone;
  language: string;
  voice: string;
  music: boolean;
  aspect_ratio: AspectRatio;
  caption_style: CaptionStyle;
  mode: "topic" | "image" | "video";
  image_job_id: string | null;
  video_job_id: string | null;
}

export async function getProviders(): Promise<ProvidersInfo> {
  const r = await fetch("/api/providers", { cache: "no-store" });
  if (!r.ok) throw new Error("Failed to load providers");
  return r.json();
}

export async function generateFromTopic(payload: TopicPayload): Promise<JobInfo> {
  const r = await fetch("/api/generate/topic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`Topic generation failed: ${r.status}`);
  return r.json();
}

export async function generateFromVideos(form: FormData): Promise<JobInfo> {
  const r = await fetch("/api/generate/video", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Video generation failed: ${r.status}`);
  return r.json();
}

export async function generateFromImages(form: FormData): Promise<JobInfo> {
  const r = await fetch("/api/generate/image", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Image generation failed: ${r.status}`);
  return r.json();
}

export async function getJob(id: string): Promise<JobInfo> {
  const r = await fetch(`/api/jobs/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error("Job not found");
  return r.json();
}

// --- Two-step editable workflow -------------------------------------------
export async function scriptFromTopic(payload: TopicPayload): Promise<ScriptDraft> {
  const r = await fetch("/api/script/topic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`Script generation failed: ${r.status}`);
  return r.json();
}

export async function scriptFromImages(form: FormData): Promise<ScriptDraft> {
  const r = await fetch("/api/script/image", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Script generation failed: ${r.status}`);
  return r.json();
}

export async function scriptFromVideos(form: FormData): Promise<ScriptDraft> {
  const r = await fetch("/api/script/video", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Script generation failed: ${r.status}`);
  return r.json();
}

export async function renderScript(draft: ScriptDraft): Promise<JobInfo> {
  const r = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      script: draft.script,
      tone: draft.tone,
      language: draft.language,
      voice: draft.voice,
      music: draft.music,
      aspect_ratio: draft.aspect_ratio,
      caption_style: draft.caption_style,
      image_job_id: draft.image_job_id,
      video_job_id: draft.video_job_id,
    }),
  });
  if (!r.ok) throw new Error(`Render failed: ${r.status}`);
  return r.json();
}
