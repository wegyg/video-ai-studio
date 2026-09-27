"use client";

import { JobInfo } from "@/lib/api";

const STAGES = [
  { key: "scripting", label: "Script" },
  { key: "visuals", label: "Visuals" },
  { key: "voicing", label: "Voice" },
  { key: "rendering", label: "Render" },
  { key: "done", label: "Done" },
];

export default function JobProgress({ job }: { job: JobInfo }) {
  const isError = job.status === "error";
  return (
    <div className="space-y-3">
      <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            isError ? "bg-red-500" : "bg-brand"
          }`}
          style={{ width: `${job.progress}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className={isError ? "text-red-400" : "text-white/70"}>
          {isError ? job.error : job.message || "Working…"}
        </span>
        <span className="text-white/40">{job.progress}%</span>
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-white/50">
        {STAGES.map((s) => (
          <span
            key={s.key}
            className={`rounded px-2 py-0.5 ${
              job.status === s.key ? "bg-brand text-white" : "bg-white/5"
            }`}
          >
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
