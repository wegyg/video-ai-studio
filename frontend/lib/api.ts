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

export type OverlayKind = "text" | "shape" | "logo" | "sticker";
export type ShapeKind = "label_box" | "arrow" | "circle" | "highlight_bar";
export type StickerPreset =
  | "new"
  | "sale"
  | "hot"
  | "best"
  | "free"
  | "sold_out"
  | "check"
  | "star"
  | "arrow_down"
  | "percent";

/** A graphic laid over the video. Position/size are percentages of the frame, so
 *  the same overlay lands in the same visual spot in every aspect ratio. */
export interface Overlay {
  kind: OverlayKind;
  x_pct: number;
  y_pct: number;
  scene_index?: number | null;
  start_sec?: number | null;
  end_sec?: number | null;
  fade_sec: number;
  color: string;
  opacity: number;
  text: string;
  size_pct: number;
  background_box: boolean;
  box_color: string;
  shape: ShapeKind;
  width_pct: number;
  height_pct: number;
  thickness_pct: number;
  logo_id?: string | null;
  sticker: StickerPreset;
  rotation_deg: number;
}

export const OVERLAY_KINDS: { value: OverlayKind; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "shape", label: "Shape" },
  { value: "sticker", label: "Sticker" },
  { value: "logo", label: "Logo / image" },
];

export const SHAPES: { value: ShapeKind; label: string }[] = [
  { value: "label_box", label: "Label box" },
  { value: "arrow", label: "Arrow" },
  { value: "circle", label: "Circle highlight" },
  { value: "highlight_bar", label: "Highlight bar" },
];

export const STICKERS: { value: StickerPreset; label: string }[] = [
  { value: "new", label: "NEW" },
  { value: "sale", label: "SALE" },
  { value: "hot", label: "HOT" },
  { value: "best", label: "BEST" },
  { value: "free", label: "FREE" },
  { value: "sold_out", label: "SOLD OUT" },
  { value: "check", label: "Check" },
  { value: "star", label: "Star" },
  { value: "arrow_down", label: "Down arrow" },
  { value: "percent", label: "Percent" },
];

/** The 9 position presets, as centre coordinates in percent. */
export const POSITION_PRESETS: { label: string; x: number; y: number }[] = [
  { label: "↖", x: 22, y: 14 },
  { label: "↑", x: 50, y: 14 },
  { label: "↗", x: 78, y: 14 },
  { label: "←", x: 22, y: 50 },
  { label: "•", x: 50, y: 50 },
  { label: "→", x: 78, y: 50 },
  { label: "↙", x: 22, y: 86 },
  { label: "↓", x: 50, y: 86 },
  { label: "↘", x: 78, y: 86 },
];

export function newOverlay(kind: OverlayKind): Overlay {
  return {
    kind,
    x_pct: 50,
    y_pct: kind === "text" ? 16 : 50,
    scene_index: null,
    start_sec: null,
    end_sec: null,
    fade_sec: 0.3,
    color: kind === "text" ? "#FFFFFF" : "#FF3B5C",
    opacity: 1,
    text: kind === "text" ? "Your text" : "",
    size_pct: kind === "text" ? 7 : 20,
    background_box: false,
    box_color: "#000000",
    shape: "label_box",
    width_pct: 45,
    height_pct: 14,
    thickness_pct: 0.8,
    logo_id: null,
    sticker: "new",
    rotation_deg: 0,
  };
}

export async function uploadLogo(file: File): Promise<{ logo_id: string }> {
  const fd = new FormData();
  fd.append("logo", file);
  const r = await fetch("/api/assets/logo", { method: "POST", body: fd });
  if (!r.ok) throw new Error(`Logo upload failed: ${r.status}`);
  return r.json();
}

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
  overlays: Overlay[];
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
  overlays: Overlay[];
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
      overlays: draft.overlays ?? [],
      image_job_id: draft.image_job_id,
      video_job_id: draft.video_job_id,
    }),
  });
  if (!r.ok) throw new Error(`Render failed: ${r.status}`);
  return r.json();
}
