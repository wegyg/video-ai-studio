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
export type TransitionType =
  | "cut"
  | "crossfade"
  | "fade"
  | "fade_white"
  | "slide_left"
  | "slide_up"
  | "zoom_in";

export interface TransitionSettings {
  type: TransitionType;
  duration_sec: number;
  fade_in: boolean;
  fade_out: boolean;
}

export type MotionType =
  | "none"
  | "zoom_in"
  | "zoom_out"
  | "pan_left"
  | "pan_right"
  | "pan_up"
  | "pan_down"
  | "auto";

export type MotionIntensity = "weak" | "medium" | "strong";

export interface MotionSettings {
  type: MotionType;
  intensity: MotionIntensity;
}

export const MOTIONS: { value: MotionType; label: string }[] = [
  { value: "auto", label: "Auto (varies each scene)" },
  { value: "zoom_in", label: "Zoom in (Ken Burns)" },
  { value: "zoom_out", label: "Zoom out" },
  { value: "pan_left", label: "Pan left" },
  { value: "pan_right", label: "Pan right" },
  { value: "pan_up", label: "Pan up" },
  { value: "pan_down", label: "Pan down" },
  { value: "none", label: "Still (no movement)" },
];

export const MOTION_INTENSITIES: { value: MotionIntensity; label: string }[] = [
  { value: "weak", label: "Subtle" },
  { value: "medium", label: "Medium" },
  { value: "strong", label: "Strong" },
];

export const TRANSITIONS: { value: TransitionType; label: string }[] = [
  { value: "crossfade", label: "Crossfade (dissolve)" },
  { value: "fade", label: "Fade through black" },
  { value: "fade_white", label: "Fade through white" },
  { value: "slide_left", label: "Slide left" },
  { value: "slide_up", label: "Slide up" },
  { value: "zoom_in", label: "Zoom in" },
  { value: "cut", label: "Hard cut (no transition)" },
];

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
  transition: TransitionSettings;
  motion: MotionSettings;
}

export interface Scene {
  text: string;
  narration: string;
  visual_query: string;
  duration_sec: number;
  /** Transition INTO the next scene. null = use the project default. */
  transition?: TransitionType | null;
  /** Camera movement for this scene. null = use the project default. */
  motion?: MotionType | null;
  motion_intensity?: MotionIntensity | null;
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
  transition: TransitionSettings;
  motion: MotionSettings;
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
      transition: draft.transition,
      motion: draft.motion,
      image_job_id: draft.image_job_id,
      video_job_id: draft.video_job_id,
    }),
  });
  if (!r.ok) throw new Error(`Render failed: ${r.status}`);
  return r.json();
}
