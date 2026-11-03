"use client"

import { Check, Copy, Download, Loader2, Pencil } from "lucide-react"
import Link from "next/link"
import { useRef, useState } from "react"

import { ScoreBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { formatDuration } from "@/lib/api"
import { t } from "@/lib/i18n"
import type { Clip } from "@/lib/types"

export function ScoreBars({ scores }: { scores: Clip["scores"] }) {
  return (
    <div className="grid grid-cols-4 gap-2">
      {(["hook", "flow", "value", "trend"] as const).map((k) => (
        <div key={k} className="space-y-1">
          <div className="flex justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
            <span>{t.clip.scores[k]}</span>
            <span className="tabular-nums">{Math.round(scores[k] ?? 0)}</span>
          </div>
          <div className="h-1 rounded-full bg-muted">
            <div className="h-1 rounded-full bg-primary" style={{ width: `${Math.min(100, scores[k] ?? 0)}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function ClipCard({ clip, rank }: { clip: Clip; rank: number }) {
  const [copied, setCopied] = useState(false)
  const [hover, setHover] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const w = clip.render_info.width ?? 1080
  const h = clip.render_info.height ?? 1920
  const ready = clip.render_status === "ready" && clip.has_video
  const v = encodeURIComponent(clip.updated_at ?? "")

  async function copy() {
    await navigator.clipboard.writeText(`${clip.description}\n\n${clip.hashtags.join(" ")}`).catch(() => null)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Card className="gap-0 overflow-hidden p-0" data-testid="clip-card">
      <div
        className="relative bg-black"
        style={{ aspectRatio: `${w} / ${h}`, maxHeight: 420 }}
        onMouseEnter={() => {
          setHover(true)
          void videoRef.current?.play().catch(() => null)
        }}
        onMouseLeave={() => {
          setHover(false)
          videoRef.current?.pause()
        }}
      >
        {ready ? (
          <video
            ref={videoRef}
            src={`/api/clips/${clip.id}/video?v=${v}`}
            poster={`/api/clips/${clip.id}/thumb?v=${v}`}
            className="mx-auto h-full max-h-[420px] object-contain"
            preload="none"
            muted={!hover}
            playsInline
            loop
            controls={hover}
          />
        ) : (
          <div className="flex size-full min-h-56 items-center justify-center gap-2 text-sm text-muted-foreground">
            {clip.render_status === "failed" ? (
              <span className="px-4 text-center text-destructive">{clip.render_error ?? t.clip.renderFailed}</span>
            ) : (
              <>
                <Loader2 className="size-4 animate-spin" /> {clip.render_status === "queued" ? t.clip.queued : t.clip.rendering}
              </>
            )}
          </div>
        )}
        <div className="absolute left-2 top-2 flex items-center gap-1.5">
          <ScoreBadge score={clip.virality_score} />
          <span className="rounded bg-black/70 px-1.5 py-0.5 text-xs">#{rank}</span>
        </div>
        <span className="absolute right-2 top-2 rounded bg-black/70 px-1.5 py-0.5 text-xs">
          {formatDuration(clip.render_info.duration ?? clip.duration)}
        </span>
      </div>
      <div className="space-y-3 p-3">
        <h3 className="line-clamp-2 font-semibold leading-snug" data-testid="clip-title">
          {clip.title}
        </h3>
        <ScoreBars scores={clip.scores} />
        {clip.reason && (
          <p className="line-clamp-3 text-xs text-muted-foreground" title={clip.reason}>
            <span className="font-medium text-foreground">{t.clip.why}: </span>
            {clip.reason}
          </p>
        )}
        <div className="rounded-lg bg-muted/60 p-2 text-xs">
          <p className="line-clamp-3">{clip.description}</p>
          <p className="mt-1 text-primary">{clip.hashtags.join(" ")}</p>
        </div>
        {clip.dirty && <p className="text-xs text-amber-400">{t.clip.notRendered}</p>}
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" asChild>
            <Link href={`/clips/${clip.id}`} data-testid="edit-clip">
              <Pencil /> {t.clip.edit}
            </Link>
          </Button>
          <Button size="sm" variant="outline" asChild disabled={!ready}>
            <a href={ready ? `/api/clips/${clip.id}/video?download=1` : undefined} aria-disabled={!ready}>
              <Download /> {t.clip.download}
            </a>
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`/api/clips/${clip.id}/srt`}>{t.clip.srt}</a>
          </Button>
          <Button size="sm" variant="ghost" onClick={copy} title={t.clip.copy}>
            {copied ? <Check /> : <Copy />}
          </Button>
        </div>
      </div>
    </Card>
  )
}
