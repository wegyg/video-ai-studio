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
  kenburns: "Ken Burns (free)",
  fal: "fal.ai AI video",
  runway: "Runway AI video",
};

// Which provider names count as the premium tier (purple badge).
const PREMIUM = new Set(["openai", "fal", "runway"]);

export default function ProviderBadge() {
  const [info, setInfo] = useState<ProvidersInfo | null>(null);

  useEffect(() => {
    getProviders().then(setInfo).catch(() => setInfo(null));
  }, []);

  if (!info) return null;

  const anyPremium = Object.values(info.active).some((n) => PREMIUM.has(n));

  return (
    <div className="flex flex-col items-start gap-2 sm:items-end">
      <span
        className={`rounded-full px-3 py-1 text-xs font-semibold ${
          anyPremium
            ? "bg-brand/20 text-brand"
            : "bg-emerald-500/15 text-emerald-400"
        }`}
      >
        {anyPremium ? "💎 Premium tier active" : "🆓 Free tier"}
      </span>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {Object.entries(info.active).map(([stage, name]) => (
          <span
            key={stage}
            className={`rounded-full border px-3 py-1 ${
              PREMIUM.has(name)
                ? "border-brand/40 bg-brand/10"
                : "border-white/15 bg-white/5"
            }`}
            title={`${stage} provider`}
          >
            <span className="text-white/50">{stage}:</span>{" "}
            <span className="font-medium">{LABELS[name] ?? name}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
