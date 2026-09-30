"use client";

import { Scene, Script, TRANSITIONS, TransitionType } from "@/lib/api";

interface Props {
  script: Script;
  onChange: (script: Script) => void;
  /** Project-wide transition, shown as the "default" option on each boundary. */
  defaultTransition?: TransitionType;
}

export default function TimelineEditor({
  script,
  onChange,
  defaultTransition = "crossfade",
}: Props) {
  const scenes = script.scenes;

  function update(i: number, patch: Partial<Scene>) {
    const next = scenes.map((s, idx) => (idx === i ? { ...s, ...patch } : s));
    onChange({ ...script, scenes: next });
  }

  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= scenes.length) return;
    const next = [...scenes];
    [next[i], next[j]] = [next[j], next[i]];
    onChange({ ...script, scenes: next });
  }

  function remove(i: number) {
    if (scenes.length <= 1) return;
    onChange({ ...script, scenes: scenes.filter((_, idx) => idx !== i) });
  }

  function add() {
    const blank: Scene = {
      text: "New scene",
      narration: "New scene",
      visual_query: script.title || "background",
      duration_sec: 3,
    };
    onChange({ ...script, scenes: [...scenes, blank] });
  }

  const total = scenes.reduce((a, s) => a + (s.duration_sec || 0), 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-white/50">
          Timeline — {scenes.length} scenes · {total.toFixed(1)}s
        </h3>
        <button
          onClick={add}
          className="rounded-lg border border-white/15 px-3 py-1 text-xs hover:bg-white/10"
        >
          + Add scene
        </button>
      </div>

      <div className="space-y-3">
        {scenes.map((s, i) => (
          <div key={i}>
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="flex items-center gap-2 text-xs font-medium text-white/50">
                <span className="grid h-6 w-6 place-items-center rounded-full bg-brand/30 text-white">
                  {i + 1}
                </span>
                {i === 0 ? "Hook" : i === scenes.length - 1 ? "CTA" : `Scene ${i + 1}`}
              </span>
              <div className="flex items-center gap-1">
                <IconBtn label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                  ↑
                </IconBtn>
                <IconBtn
                  label="Move down"
                  disabled={i === scenes.length - 1}
                  onClick={() => move(i, 1)}
                >
                  ↓
                </IconBtn>
                <IconBtn
                  label="Delete"
                  disabled={scenes.length <= 1}
                  onClick={() => remove(i)}
                >
                  ✕
                </IconBtn>
              </div>
            </div>

            {/* On-screen caption */}
            <input
              value={s.text}
              onChange={(e) => update(i, { text: e.target.value })}
              placeholder="On-screen caption"
              className="mb-2 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm font-medium outline-none focus:border-brand"
            />

            {/* Narration (spoken) */}
            <input
              value={s.narration}
              onChange={(e) => update(i, { narration: e.target.value })}
              placeholder="Narration (spoken) — leave same as caption if unsure"
              className="mb-2 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white/70 outline-none focus:border-brand"
            />

            <div className="flex gap-2">
              {/* Visual search hint */}
              <input
                value={s.visual_query}
                onChange={(e) => update(i, { visual_query: e.target.value })}
                placeholder="Visual search (e.g. coffee pour)"
                className="flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white/60 outline-none focus:border-brand"
                title="What stock footage / background to search for"
              />
              {/* Duration */}
              <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-black/30 px-2">
                <input
                  type="number"
                  min={1}
                  max={15}
                  step={0.5}
                  value={s.duration_sec}
                  onChange={(e) =>
                    update(i, { duration_sec: Math.max(1, Number(e.target.value)) })
                  }
                  className="w-14 bg-transparent py-2 text-center text-xs outline-none"
                />
                <span className="pr-1 text-xs text-white/40">s</span>
              </div>
            </div>
          </div>

          {/* transition chip between this scene and the next */}
          {i < scenes.length - 1 && (
            <div className="flex items-center gap-2 py-1.5 pl-9">
              <span className="text-white/25">↓</span>
              <select
                aria-label={`Transition from scene ${i + 1} to scene ${i + 2}`}
                value={s.transition ?? ""}
                onChange={(e) =>
                  update(i, { transition: (e.target.value || null) as TransitionType | null })
                }
                className="rounded-full border border-white/10 bg-black/30 px-3 py-1 text-xs text-white/70 outline-none focus:border-brand"
                title="How this scene gives way to the next"
              >
                <option value="" className="bg-[#161226]">
                  ✨ Default ({TRANSITIONS.find((t) => t.value === defaultTransition)?.label ?? defaultTransition})
                </option>
                {TRANSITIONS.map((t) => (
                  <option key={t.value} value={t.value} className="bg-[#161226]">
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          </div>
        ))}
      </div>
      <p className="text-xs text-white/40">
        💡 Scene length auto-extends to fit the narration when rendering. Transitions overlap the
        scenes without shifting the voice or captions.
      </p>
    </div>
  );
}

function IconBtn({
  children,
  onClick,
  disabled,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-7 w-7 place-items-center rounded-md border border-white/10 text-xs text-white/70 hover:bg-white/10 disabled:opacity-25"
    >
      {children}
    </button>
  );
}
