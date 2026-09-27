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
  mode: "topic" | "image";
  providers: Record<string, string>;
  video_url: string | null;
  error: string | null;
}

export interface ProvidersInfo {
  active: Record<string, string>;
  upgrades: Record<string, boolean>;
}

export type Tone = "energetic" | "professional" | "friendly" | "luxury" | "playful";

export interface TopicPayload {
  topic: string;
  key_points: string[];
  tone: Tone;
  duration_sec: number;
  language: string;
  voice: string;
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
