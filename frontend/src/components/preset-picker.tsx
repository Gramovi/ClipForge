"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { CaptionOverlay } from "@/components/caption-overlay"
import { resolveStyle } from "@/lib/captions"
import type { PresetDef, PresetsResponse, Word } from "@/lib/types"
import { cn } from "@/lib/utils"

const SAMPLE = "Tohle je tajemství úspěchu. Peníze přijdou, když děláš věci pořádně!"

function sampleWords(): Word[] {
  let t = 0.2
  return SAMPLE.split(" ").map((w, i) => {
    const s = t
    t += 0.32 + w.length * 0.025
    if (/[.!?]$/.test(w)) t += 0.25
    return { w, s, e: t - 0.06, i }
  })
}

/** Small looping 9:16 preview of a preset (rendered from the shared preset JSON). */
export function PresetPreview({ data, preset, width = 132 }: { data: PresetsResponse; preset: PresetDef; width?: number }) {
  const words = useMemo(sampleWords, [])
  const style = useMemo(() => resolveStyle(data, preset.id), [data, preset.id])
  const [time, setTime] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const loop = words[words.length - 1].e + 0.8
  useEffect(() => {
    let raf = 0
    let visible = true
    const obs = new IntersectionObserver(([e]) => (visible = e.isIntersecting))
    if (ref.current) obs.observe(ref.current)
    const t0 = performance.now()
    const tick = () => {
      if (visible) setTime(((performance.now() - t0) / 1000) % loop)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      obs.disconnect()
    }
  }, [loop])
  const height = (width * 16) / 9
  return (
    <div
      ref={ref}
      className="relative overflow-hidden rounded-lg bg-[radial-gradient(circle_at_30%_20%,#3b4b6b,#141821_70%)]"
      style={{ width, height }}
    >
      <div className="absolute left-1/2 top-[22%] h-[30%] w-[46%] -translate-x-1/2 rounded-full bg-[#c89f86]/70 blur-[1px]" />
      <div className="absolute left-1/2 top-[48%] h-[40%] w-[70%] -translate-x-1/2 rounded-t-[45%] bg-[#2d3a52]" />
      <CaptionOverlay words={words} style={style} outW={1080} outH={1920} displayW={width} time={time} keywords={["úspěchu", "peníze"]} emojiStems={(data as PresetsResponse & { emoji_stems?: Record<string, string> }).emoji_stems} />
    </div>
  )
}

export function PresetPicker({
  data,
  value,
  onChange,
  compact = false,
}: {
  data: PresetsResponse
  value: string
  onChange: (id: string) => void
  compact?: boolean
}) {
  const all = [...data.presets, ...data.user_presets]
  return (
    <div className={cn("grid gap-3", compact ? "grid-cols-3 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-4 lg:grid-cols-7")}>
      {all.map((p) => (
        <button
          key={p.id}
          type="button"
          data-testid={`preset-${p.id}`}
          onClick={() => onChange(p.id)}
          className={cn(
            "group flex flex-col items-center gap-2 rounded-xl border p-2 text-left transition-colors",
            value === p.id ? "border-primary bg-primary/10" : "border-border hover:border-primary/50",
          )}
          title={p.description}
        >
          <PresetPreview data={data} preset={p} width={compact ? 96 : 120} />
          <span className="w-full truncate text-center text-xs font-medium">{p.name}</span>
        </button>
      ))}
    </div>
  )
}
