"use client";

import { useState } from "react";
import {
  Overlay,
  OverlayKind,
  OVERLAY_KINDS,
  POSITION_PRESETS,
  SHAPES,
  STICKERS,
  ShapeKind,
  StickerPreset,
  newOverlay,
  uploadLogo,
} from "@/lib/api";

interface Props {
  overlays: Overlay[];
  onChange: (overlays: Overlay[]) => void;
  /** Scene count, so an overlay can be pinned to one scene. */
  sceneCount?: number;
}

const KIND_ICON: Record<OverlayKind, string> = {
  text: "T",
  shape: "◻",
  sticker: "★",
  logo: "▣",
};

export default function OverlayPanel({ overlays, onChange, sceneCount = 0 }: Props) {
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  function update(i: number, patch: Partial<Overlay>) {
    onChange(overlays.map((o, idx) => (idx === i ? { ...o, ...patch } : o)));
  }

  function add(kind: OverlayKind) {
    onChange([...overlays, newOverlay(kind)]);
    setOpen(overlays.length);
  }

  function remove(i: number) {
    onChange(overlays.filter((_, idx) => idx !== i));
    setOpen(null);
  }

  async function pickLogo(i: number, file: File) {
    setBusy(i);
    setError("");
    try {
      const { logo_id } = await uploadLogo(file);
      update(i, { logo_id });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Logo upload failed");
    } finally {
      setBusy(null);
    }
  }

  function summary(o: Overlay): string {
    if (o.kind === "text") return o.text || "(empty text)";
    if (o.kind === "shape") return SHAPES.find((s) => s.value === o.shape)?.label ?? o.shape;
    if (o.kind === "sticker") return STICKERS.find((s) => s.value === o.sticker)?.label ?? o.sticker;
    return o.logo_id ? "Logo uploaded" : "No file chosen";
  }

  function timing(o: Overlay): string {
    if (o.scene_index !== null && o.scene_index !== undefined) return `scene ${o.scene_index + 1}`;
    const a = o.start_sec ?? null;
    const b = o.end_sec ?? null;
    if (a === null && b === null) return "whole video";
    return `${(a ?? 0).toFixed(1)}s – ${b === null ? "end" : `${b.toFixed(1)}s`}`;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-white/80">
          Graphics {overlays.length > 0 && `(${overlays.length})`}
        </span>
        <div className="flex gap-1">
          {OVERLAY_KINDS.map((k) => (
            <button
              key={k.value}
              type="button"
              onClick={() => add(k.value)}
              className="rounded-lg border border-white/15 px-2 py-1 text-xs text-white/70 transition hover:bg-white/10"
              title={`Add ${k.label.toLowerCase()}`}
            >
              + {k.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-xs text-red-300">{error}</p>}

      {overlays.length === 0 && (
        <p className="rounded-xl border border-dashed border-white/10 px-3 py-4 text-center text-xs text-white/35">
          No graphics yet. Add text, a shape, a sticker or your logo — each one can sit on a
          single scene or a time range.
        </p>
      )}

      <div className="space-y-2">
        {overlays.map((o, i) => (
          <div key={i} className="rounded-xl border border-white/10 bg-black/20">
            {/* row header */}
            <div className="flex items-center gap-2 px-3 py-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-brand/25 text-xs text-brand">
                {KIND_ICON[o.kind]}
              </span>
              <button
                type="button"
                onClick={() => setOpen(open === i ? null : i)}
                className="flex-1 text-left text-xs text-white/75"
              >
                <span className="font-medium">{summary(o)}</span>
                <span className="text-white/35"> · {timing(o)}</span>
              </button>
              <button
                type="button"
                onClick={() => remove(i)}
                aria-label={`Delete graphic ${i + 1}`}
                className="rounded-md px-2 py-1 text-xs text-white/40 transition hover:bg-red-500/20 hover:text-red-300"
              >
                ✕
              </button>
            </div>

            {open === i && (
              <div className="space-y-3 border-t border-white/10 px-3 py-3">
                {/* per-kind fields */}
                {o.kind === "text" && (
                  <div className="space-y-2">
                    <input
                      value={o.text}
                      onChange={(e) => update(i, { text: e.target.value })}
                      placeholder="Text to show"
                      className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs outline-none focus:border-brand"
                    />
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-1.5 text-xs text-white/60">
                        <input
                          type="checkbox"
                          checked={o.background_box}
                          onChange={(e) => update(i, { background_box: e.target.checked })}
                          className="accent-brand"
                        />
                        Background box
                      </label>
                      {o.background_box && (
                        <Swatch
                          label="Box"
                          value={o.box_color}
                          onChange={(v) => update(i, { box_color: v })}
                        />
                      )}
                    </div>
                  </div>
                )}

                {o.kind === "shape" && (
                  <div className="grid grid-cols-2 gap-2">
                    <select
                      value={o.shape}
                      onChange={(e) => update(i, { shape: e.target.value as ShapeKind })}
                      className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs outline-none focus:border-brand"
                    >
                      {SHAPES.map((s) => (
                        <option key={s.value} value={s.value} className="bg-[#161226]">
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <Num
                      label="Rotation"
                      value={o.rotation_deg}
                      min={0}
                      max={360}
                      step={15}
                      suffix="°"
                      onChange={(v) => update(i, { rotation_deg: v })}
                    />
                    <Num
                      label="Width"
                      value={o.width_pct}
                      min={2}
                      max={100}
                      step={1}
                      suffix="%"
                      onChange={(v) => update(i, { width_pct: v })}
                    />
                    {/* a circle takes its diameter from Width alone, so that it
                        stays round in every aspect ratio */}
                    {o.shape !== "circle" && (
                      <Num
                        label="Height"
                        value={o.height_pct}
                        min={1}
                        max={100}
                        step={1}
                        suffix="%"
                        onChange={(v) => update(i, { height_pct: v })}
                      />
                    )}
                  </div>
                )}

                {o.kind === "sticker" && (
                  <select
                    value={o.sticker}
                    onChange={(e) => update(i, { sticker: e.target.value as StickerPreset })}
                    className="w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs outline-none focus:border-brand"
                  >
                    {STICKERS.map((s) => (
                      <option key={s.value} value={s.value} className="bg-[#161226]">
                        {s.label}
                      </option>
                    ))}
                  </select>
                )}

                {o.kind === "logo" && (
                  <label className="flex cursor-pointer items-center justify-between rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-white/60">
                    <span>
                      {busy === i ? "Uploading…" : o.logo_id ? "Logo ready — replace" : "Choose a PNG"}
                    </span>
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void pickLogo(i, f);
                      }}
                    />
                    <span className="rounded-md bg-white/10 px-2 py-1">Browse</span>
                  </label>
                )}

                {/* position: 9 presets, plus exact percentages */}
                <div className="flex gap-3">
                  <div>
                    <p className="mb-1 text-[11px] uppercase tracking-wide text-white/40">
                      Position
                    </p>
                    <div className="grid w-[76px] grid-cols-3 gap-0.5">
                      {POSITION_PRESETS.map((p) => {
                        const active = Math.abs(o.x_pct - p.x) < 1 && Math.abs(o.y_pct - p.y) < 1;
                        return (
                          <button
                            key={p.label}
                            type="button"
                            aria-label={`Move to ${p.label}`}
                            onClick={() => update(i, { x_pct: p.x, y_pct: p.y })}
                            className={`h-6 rounded text-[10px] transition ${
                              active ? "bg-brand text-white" : "bg-white/10 text-white/50 hover:bg-white/20"
                            }`}
                          >
                            {p.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="grid flex-1 grid-cols-2 gap-2">
                    <Num label="X" value={o.x_pct} min={0} max={100} step={1} suffix="%"
                      onChange={(v) => update(i, { x_pct: v })} />
                    <Num label="Y" value={o.y_pct} min={0} max={100} step={1} suffix="%"
                      onChange={(v) => update(i, { y_pct: v })} />
                    <Num label="Size" value={o.size_pct} min={1} max={100} step={1} suffix="%"
                      onChange={(v) => update(i, { size_pct: v })} />
                    <Num label="Opacity" value={o.opacity} min={0.1} max={1} step={0.05}
                      onChange={(v) => update(i, { opacity: v })} />
                  </div>
                </div>

                {/* colour + timing */}
                <div className="flex flex-wrap items-end gap-3">
                  {o.kind !== "logo" && (
                    <Swatch label="Colour" value={o.color} onChange={(v) => update(i, { color: v })} />
                  )}
                  <label className="text-[11px] uppercase tracking-wide text-white/40">
                    Shows on
                    <select
                      value={o.scene_index === null || o.scene_index === undefined ? "range" : String(o.scene_index)}
                      onChange={(e) =>
                        update(
                          i,
                          e.target.value === "range"
                            ? { scene_index: null }
                            : { scene_index: Number(e.target.value), start_sec: null, end_sec: null },
                        )
                      }
                      className="mt-1 block rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-white/70 outline-none focus:border-brand"
                    >
                      <option value="range" className="bg-[#161226]">
                        A time range
                      </option>
                      {Array.from({ length: sceneCount }).map((_, s) => (
                        <option key={s} value={s} className="bg-[#161226]">
                          Scene {s + 1}
                        </option>
                      ))}
                    </select>
                  </label>
                  {(o.scene_index === null || o.scene_index === undefined) && (
                    <>
                      <Num label="From" value={o.start_sec ?? 0} min={0} max={600} step={0.5}
                        suffix="s" onChange={(v) => update(i, { start_sec: v })} />
                      <Num label="To" value={o.end_sec ?? 0} min={0} max={600} step={0.5}
                        suffix="s" placeholder="end"
                        onChange={(v) => update(i, { end_sec: v > 0 ? v : null })} />
                    </>
                  )}
                  <Num label="Fade" value={o.fade_sec} min={0} max={2} step={0.1} suffix="s"
                    onChange={(v) => update(i, { fade_sec: v })} />
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Num({
  label,
  value,
  min,
  max,
  step,
  suffix,
  placeholder,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  placeholder?: string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="text-[11px] uppercase tracking-wide text-white/40">
      {label}
      {suffix ? ` (${suffix})` : ""}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        onChange={(e) => {
          const n = Number(e.target.value);
          onChange(Math.min(max, Math.max(min, Number.isFinite(n) ? n : min)));
        }}
        className="mt-1 block w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-white/80 outline-none focus:border-brand"
      />
    </label>
  );
}

function Swatch({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="text-[11px] uppercase tracking-wide text-white/40">
      {label}
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        className="mt-1 block h-8 w-14 cursor-pointer rounded-lg border border-white/10 bg-black/30"
      />
    </label>
  );
}
