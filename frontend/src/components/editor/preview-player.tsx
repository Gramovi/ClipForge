"use client"

import { Pause, Play, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { CaptionOverlay } from "@/components/caption-overlay"
import { Button } from "@/components/ui/button"
import { formatDuration } from "@/lib/api"
import type { BrandTemplate, CropPlan, HookDef, Style, Word } from "@/lib/types"

function interp(times: number[], vals: number[], t: number): number {
  if (!times.length) return 0
  if (t <= times[0]) return vals[0]
  if (t >= times[times.length - 1]) return vals[vals.length - 1]
  let lo = 0
  let hi = times.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= t) lo = mid
    else hi = mid
  }
  const f = (t - times[lo]) / (times[hi] - times[lo] || 1)
  return vals[lo] + (vals[hi] - vals[lo]) * f
}

type Props = {
  src: string
  previewOffset: number
  start: number
  end: number
  plan: CropPlan | null
  outW: number
  outH: number
  words: Word[] // relative to clip start
  style: Style
  keywords: string[]
  emojis: { word: string; emoji: string }[]
  emojiStems: Record<string, string>
  hook: { text: string; def: HookDef } | null
  showCaptions: boolean
  brand?: BrandTemplate | null
  seekTo?: { t: number; n: number } | null
  onTime?: (sourceTime: number) => void
}

/**
 * Live preview: draws the crop path (same plan as the final render) into a canvas and
 * overlays captions generated from the shared preset JSON.
 */
export function PreviewPlayer(p: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [displayW, setDisplayW] = useState(270)
  const [time, setTime] = useState(0) // relative to clip start
  const [playing, setPlaying] = useState(false)
  const propsRef = useRef(p)
  propsRef.current = p

  // keep canvas size in sync with the layout
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setDisplayW(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const draw = useCallback(() => {
    const v = videoRef.current
    const c = canvasRef.current
    const { plan, outW, outH, previewOffset, start, end } = propsRef.current
    if (!v || !c) return
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    const W = Math.round(c.clientWidth * dpr)
    const H = Math.round((W * outH) / outW)
    if (c.width !== W || c.height !== H) {
      c.width = W
      c.height = H
    }
    const ctx = c.getContext("2d")
    if (!ctx || !v.videoWidth) return
    const srcT = previewOffset + v.currentTime
    if (!v.paused && (srcT >= end - 0.02 || srcT < start - 0.5)) {
      v.currentTime = Math.max(0, start - previewOffset)
    }
    setTime(srcT - start)
    propsRef.current.onTime?.(srcT)
    ctx.fillStyle = "#000"
    ctx.fillRect(0, 0, W, H)
    const sw = plan?.src_w ?? v.videoWidth
    const k = v.videoWidth / sw
    const layout = plan?.layout ?? "blur"
    if (layout === "blur" || !plan) {
      const cover = Math.max(W / v.videoWidth, H / v.videoHeight)
      ctx.filter = `blur(${Math.round(W / 30)}px) brightness(0.8)`
      ctx.drawImage(v, (W - v.videoWidth * cover) / 2, (H - v.videoHeight * cover) / 2, v.videoWidth * cover, v.videoHeight * cover)
      ctx.filter = "none"
      const fit = Math.min(W / v.videoWidth, H / v.videoHeight)
      ctx.drawImage(v, (W - v.videoWidth * fit) / 2, (H - v.videoHeight * fit) / 2, v.videoWidth * fit, v.videoHeight * fit)
    } else if (layout === "split" && plan.xs2 && plan.ys2) {
      const hh = H / 2
      const x1 = interp(plan.times, plan.xs, srcT)
      const y1 = interp(plan.times, plan.ys, srcT)
      const x2 = interp(plan.times, plan.xs2, srcT)
      const y2 = interp(plan.times, plan.ys2, srcT)
      ctx.drawImage(v, x1 * k, y1 * k, plan.crop_w * k, plan.crop_h * k, 0, 0, W, hh)
      ctx.drawImage(v, x2 * k, y2 * k, plan.crop_w * k, plan.crop_h * k, 0, hh, W, H - hh)
    } else {
      const x = interp(plan.times, plan.xs, srcT)
      const y = interp(plan.times, plan.ys, srcT)
      ctx.drawImage(v, x * k, y * k, plan.crop_w * k, plan.crop_h * k, 0, 0, W, H)
    }
  }, [])

  useEffect(() => {
    let raf = 0
    const loop = () => {
      draw()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [draw])

  // seek when the clip range changes or a word is clicked
  useEffect(() => {
    const v = videoRef.current
    if (v && v.readyState >= 1) v.currentTime = Math.max(0, p.start - p.previewOffset)
  }, [p.start, p.previewOffset])
  useEffect(() => {
    const v = videoRef.current
    if (v && p.seekTo) v.currentTime = Math.max(0, p.seekTo.t - p.previewOffset)
  }, [p.seekTo, p.previewOffset])

  function toggle() {
    const v = videoRef.current
    if (!v) return
    if (v.paused) void v.play()
    else v.pause()
  }

  const logoPos: Record<string, React.CSSProperties> = {
    "top-left": { left: "4%", top: "4%" },
    "top-right": { right: "4%", top: "4%" },
    "bottom-left": { left: "4%", bottom: "4%" },
    "bottom-right": { right: "4%", bottom: "4%" },
    center: { left: "50%", top: "50%", transform: "translate(-50%,-50%)" },
  }

  return (
    <div className="space-y-2">
      <div
        ref={boxRef}
        className="relative mx-auto w-full overflow-hidden rounded-xl bg-black shadow-2xl"
        style={{ aspectRatio: `${p.outW} / ${p.outH}`, maxWidth: p.outW > p.outH ? 720 : p.outW === p.outH ? 480 : 340 }}
        onClick={toggle}
        data-testid="preview-player"
      >
        <canvas ref={canvasRef} className="absolute inset-0 size-full" />
        <CaptionOverlay
          words={p.words}
          style={p.style}
          outW={p.outW}
          outH={p.outH}
          displayW={displayW}
          time={time}
          keywords={p.keywords}
          emojis={p.emojis}
          emojiStems={p.emojiStems}
          hook={p.hook}
          showCaptions={p.showCaptions}
        />
        {p.brand?.logo_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={p.brand.logo_url}
            alt=""
            className="pointer-events-none absolute"
            style={{ width: `${p.brand.logo_scale * 100}%`, opacity: p.brand.logo_opacity, ...logoPos[p.brand.logo_position] }}
          />
        )}
        <video
          ref={videoRef}
          src={p.src}
          className="hidden"
          playsInline
          preload="auto"
          onLoadedMetadata={(e) => (e.currentTarget.currentTime = Math.max(0, p.start - p.previewOffset))}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      </div>
      <div className="mx-auto flex max-w-[340px] items-center gap-2 text-xs text-muted-foreground">
        <Button size="icon-sm" variant="secondary" onClick={toggle} aria-label={playing ? "Pauza" : "Přehrát"} data-testid="play-toggle">
          {playing ? <Pause /> : <Play />}
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="Na začátek"
          onClick={() => {
            if (videoRef.current) videoRef.current.currentTime = Math.max(0, p.start - p.previewOffset)
          }}
        >
          <RotateCcw />
        </Button>
        <span className="tabular-nums">
          {formatDuration(Math.max(0, time))} / {formatDuration(p.end - p.start)}
        </span>
      </div>
    </div>
  )
}
