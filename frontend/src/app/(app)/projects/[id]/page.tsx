"use client"

import { ArrowLeft, CheckCircle2, Circle, Download, FileText, Loader2, RotateCcw, XCircle } from "lucide-react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { ClipCard } from "@/components/clip-card"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Slider } from "@/components/ui/slider"
import { api, formatDuration, formatEta } from "@/lib/api"
import { t } from "@/lib/i18n"
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"

const STEPS = ["upload", "transcribe", "moments", "reframe", "render"]

type ExportState = { id: string; status: string; progress: number; message: string | null }

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [minScore, setMinScore] = useState(0)
  const [exp, setExp] = useState<ExportState | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const load = useCallback(async () => {
    try {
      setProject(await api<Project>(`/api/projects/${id}`))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  // live progress over SSE while the worker processes the video
  const running = project && (project.status === "queued" || project.status === "processing")
  useEffect(() => {
    if (!running) return
    const es = new EventSource(`/api/projects/${id}/events`)
    esRef.current = es
    es.addEventListener("progress", (ev) => {
      const snap = JSON.parse((ev as MessageEvent).data) as Project
      setProject((p) => (p ? { ...p, ...snap, clips: p.clips } : snap))
    })
    es.addEventListener("end", () => {
      es.close()
      void load()
    })
    return () => es.close()
  }, [running, id, load])

  // refresh clip render states while some clips are still rendering
  const anyRendering = project?.clips?.some((c) => c.render_status === "rendering" || c.render_status === "queued")
  useEffect(() => {
    if (!anyRendering || running) return
    const h = setInterval(load, 2500)
    return () => clearInterval(h)
  }, [anyRendering, running, load])

  // poll the ZIP export job
  useEffect(() => {
    if (!exp || exp.status === "ready" || exp.status === "failed") return
    const h = setInterval(async () => {
      try {
        const e = await api<ExportState>(`/api/exports/${exp.id}`)
        setExp(e)
        if (e.status === "ready") window.location.href = `/api/exports/${e.id}/download`
        if (e.status === "failed") toast.error(e.message ?? t.common.error)
      } catch {
        /* keep polling */
      }
    }, 1500)
    return () => clearInterval(h)
  }, [exp])

  const clips = useMemo(
    () => (project?.clips ?? []).filter((c) => c.virality_score >= minScore).sort((a, b) => b.virality_score - a.virality_score),
    [project, minScore],
  )

  async function retry() {
    try {
      setProject(await api<Project>(`/api/projects/${id}/retry`, { method: "POST" }))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function exportZip() {
    try {
      setExp(await api<ExportState>(`/api/projects/${id}/export`, { method: "POST" }))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (error) return <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>
  if (!project) return <Skeleton className="h-64 w-full rounded-xl" />

  const stepIdx = STEPS.indexOf(project.step)
  const usage = project.llm_usage
  const tokens = (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0)

  return (
    <div className="space-y-6">
      <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> {t.project.back}
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold tracking-tight" data-testid="project-title">
          {project.name}
        </h1>
        <StatusBadge status={project.status} />
      </div>
      <p className="-mt-4 text-sm text-muted-foreground">
        {project.duration ? `${formatDuration(project.duration)} · ` : ""}
        {project.width ? `${project.width}×${project.height} · ` : ""}
        {project.language ? `${project.language.toUpperCase()} · ` : ""}
        {tokens > 0 && t.project.usage(tokens.toLocaleString("cs-CZ"), usage.cost_usd != null ? ` · ≈ $${usage.cost_usd.toFixed(3)}` : "")}
        {usage.model ? ` (${usage.model})` : ""}
      </p>

      {running && (
        <Card data-testid="progress-card">
          <CardContent className="space-y-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-medium">{t.project.progressTitle}</h2>
              <span className="text-sm tabular-nums text-muted-foreground">
                {project.progress.toFixed(0)} %{project.eta_seconds ? ` · ${t.project.eta(formatEta(project.eta_seconds))}` : ""}
              </span>
            </div>
            <Progress value={project.progress} />
            <ol className="grid gap-2 sm:grid-cols-5">
              {STEPS.map((s, i) => {
                const done = i < stepIdx
                const active = i === stepIdx && project.status === "processing"
                return (
                  <li
                    key={s}
                    className={cn(
                      "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                      active && "border-primary bg-primary/10",
                      done && "text-muted-foreground",
                    )}
                  >
                    {done ? (
                      <CheckCircle2 className="size-4 text-emerald-400" />
                    ) : active ? (
                      <Loader2 className="size-4 animate-spin text-primary" />
                    ) : (
                      <Circle className="size-4 text-muted-foreground" />
                    )}
                    <span className="flex-1">{t.steps[s]}</span>
                    {active && <span className="tabular-nums text-xs">{project.step_progress.toFixed(0)} %</span>}
                  </li>
                )
              })}
            </ol>
            {project.message && <p className="text-sm text-muted-foreground">{project.message}</p>}
            <p className="text-xs text-muted-foreground">{t.project.canLeave}</p>
          </CardContent>
        </Card>
      )}

      {project.status === "failed" && (
        <Alert variant="destructive" data-testid="project-error">
          <XCircle />
          <AlertTitle>{t.project.failed}</AlertTitle>
          <AlertDescription>
            <p className="whitespace-pre-wrap">{project.error}</p>
            <Button size="sm" variant="outline" className="mt-3" onClick={retry}>
              <RotateCcw /> {t.project.retry}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {project.status === "done" && (
        <>
          {project.message && !project.message.startsWith("Hotovo") && (
            <Alert>
              <AlertDescription>{project.message}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <div className="mr-auto">
              <h2 className="text-lg font-semibold">{t.project.clipsTitle(project.clips?.length ?? 0)}</h2>
              <p className="text-xs text-muted-foreground">{t.project.sortedBy}</p>
            </div>
            <div className="flex w-48 items-center gap-2 text-sm">
              <span className="shrink-0 text-muted-foreground">{t.project.minScore}</span>
              <Slider value={[minScore]} min={0} max={95} step={5} onValueChange={([v]) => setMinScore(v)} />
              <span className="w-6 tabular-nums">{minScore}</span>
            </div>
            <Button variant="outline" asChild>
              <a href={`/api/projects/${id}/transcript.txt`}>
                <FileText /> {t.project.transcript}
              </a>
            </Button>
            <Button onClick={exportZip} disabled={!!exp && exp.status !== "ready" && exp.status !== "failed"} data-testid="export-zip">
              {exp && exp.status !== "ready" && exp.status !== "failed" ? <Loader2 className="animate-spin" /> : <Download />}
              {exp && exp.status !== "ready" && exp.status !== "failed" ? `${t.project.exporting} ${exp.progress.toFixed(0)} %` : t.project.exportZip}
            </Button>
          </div>
          {clips.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t.project.noClips}</p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="clip-grid">
              {clips.map((c, i) => (
                <ClipCard key={c.id} clip={c} rank={i + 1} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
