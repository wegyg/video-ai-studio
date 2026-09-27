"use client";

import { useEffect, useState } from "react";
import { getProviders, ProvidersInfo } from "@/lib/api";

const LABELS: Record<string, string> = {
  free: "Free",
  gtts: "gTTS (free)",
  silent: "Silent",
  gradient: "Gradient (free)",
  pexels: "Pexels stock",
  openai: "OpenAI",
};

export default function ProviderBadge() {
  const [info, setInfo] = useState<ProvidersInfo | null>(null);

  useEffect(() => {
    getProviders().then(setInfo).catch(() => setInfo(null));
  }, []);

  if (!info) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {Object.entries(info.active).map(([stage, name]) => (
        <span
          key={stage}
          className="rounded-full border border-white/15 bg-white/5 px-3 py-1"
          title={`${stage} provider`}
        >
          <span className="text-white/50">{stage}:</span>{" "}
          <span className="font-medium">{LABELS[name] ?? name}</span>
        </span>
      ))}
    </div>
  );
}
