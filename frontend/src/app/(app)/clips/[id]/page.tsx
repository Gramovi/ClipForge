"use client"

import { ArrowLeft, Download, FileText, Loader2, Save, Wand2 } from "lucide-react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { ScoreBars } from "@/components/clip-card"
import { PreviewPlayer } from "@/components/editor/preview-player"
import { StylePanel } from "@/components/editor/style-panel"
import { ScoreBadge } from "@/components/status-badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { api, formatDuration } from "@/lib/api"
import { resolveStyle } from "@/lib/captions"
import { useCaptionFonts, useFetch, usePresets } from "@/lib/hooks"
import { t } from "@/lib/i18n"
import type { BrandTemplate, ClipDetail, ClipEdit, CropPlan, Style, Word } from "@/lib/types"
import { cn } from "@/lib/utils"

const ASPECT_SIZE: Record<string, [number, number]> = { "9:16": [1080, 1920], "1:1": [1080, 1080], "16:9": [1920, 1080] }

export default function ClipEditorPage() {
  const { id } = useParams<{ id: string }>()
  const { data: presets, reload: reloadPresets } = usePresets()
  const { data: brands } = useFetch<BrandTemplate[]>("/api/brand-templates")
  useCaptionFonts(presets?.fonts)

  const [clip, setClip] = useState<ClipDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [edit, setEdit] = useState<ClipEdit | null>(null)
  const [range, setRange] = useState<[number, number]>([0, 0])
  const [meta, setMeta] = useState({ title: "", description: "", hashtags: "" })
  const [dirty, setDirty] = useState(false)
  const [plan, setPlan] = useState<CropPlan | null>(null)
  const [clickMode, setClickMode] = useState<"seek" | "start" | "end">("seek")
  const [seekTo, setSeekTo] = useState<{ t: number; n: number } | null>(null)
  const [curTime, setCurTime] = useState(0)
  const [editingWord, setEditingWord] = useState<Word | null>(null)
  const [wordText, setWordText] = useState("")
  const [saving, setSaving] = useState(false)
  const [view, setView] = useState<"live" | "rendered">("live")
  const lastTimeUpdate = useRef(0)

  const load = useCallback(async () => {
    try {
      const c = await api<ClipDetail>(`/api/clips/${id}`)
      setClip(c)
      return c
    } catch (e) {
      setError((e as Error).message)
      return null
    }
  }, [id])

  useEffect(() => {
    void load().then((c) => {
      if (!c) return
      setEdit(c.effective_edit)
      setRange([c.start, c.end])
      setMeta({ title: c.title, description: c.description, hashtags: c.hashtags.join(" ") })
    })
  }, [load])

  // crop plan for the current aspect/layout (computed by the backend, same as the render)
  const aspect = edit?.aspect ?? "9:16"
  const layout = edit?.layout ?? "auto"
  useEffect(() => {
    if (!clip?.has_preview) return
    api<CropPlan>(`/api/clips/${id}/plan?aspect=${encodeURIComponent(aspect)}&layout=${layout}`)
      .then(setPlan)
      .catch(() => setPlan(null))
  }, [id, aspect, layout, clip?.has_preview])

  // poll while rendering
  const rendering = clip?.render_status === "queued" || clip?.render_status === "rendering"
  useEffect(() => {
    if (!rendering) return
    const h = setInterval(async () => {
      const c = await load()
      if (c && c.render_status === "ready") {
        toast.success(t.editor.renderDone)
        setView("rendered")
      }
      if (c && c.render_status === "failed") toast.error(c.render_error ?? t.clip.renderFailed)
    }, 1500)
    return () => clearInterval(h)
  }, [rendering, load])

  const brand = useMemo(() => brands?.find((b) => b.id === edit?.brand_template_id) ?? null, [brands, edit?.brand_template_id])

  const style: Style | null = useMemo(() => {
    if (!presets || !edit) return null
    const s = resolveStyle(presets, edit.preset_id, edit.style)
    if (brand) {
      s.text_color = brand.primary_color || s.text_color
      s.highlight_color = brand.accent_color || s.highlight_color
      if (brand.font_id) s.font = brand.font_id
    }
    return s
  }, [presets, edit, brand])

  const clipWords = useMemo(() => {
    if (!clip || !edit) return []
    const [s, e] = range
    return clip.words
      .filter((w) => w.e > s && w.s < e)
      .map((w) => ({ ...w, t: edit.word_edits[String(w.i)] ?? undefined, s: Math.max(0, w.s - s), e: Math.min(e, w.e) - s }))
  }, [clip, edit, range])

  function patchEdit(p: Partial<ClipEdit>) {
    setEdit((e) => (e ? { ...e, ...p } : e))
    setDirty(true)
  }
  function patchStyle(p: Partial<Style>) {
    setEdit((e) => (e ? { ...e, style: { ...e.style, ...p } } : e))
    setDirty(true)
  }

  async function save(): Promise<boolean> {
    if (!edit || !clip) return false
    setSaving(true)
    try {
      await api(`/api/clips/${id}`, {
        method: "PATCH",
        json: {
          start: range[0],
          end: range[1],
          title: meta.title,
          description: meta.description,
          hashtags: meta.hashtags.split(/\s+/).filter(Boolean),
          edit: { ...edit, brand_template_id: edit.brand_template_id || null },
        },
      })
      setDirty(false)
      await load()
      toast.success(t.editor.saved)
      return true
    } catch (e) {
      toast.error((e as Error).message)
      return false
    } finally {
      setSaving(false)
    }
  }

  async function saveAndRender() {
    if (dirty && !(await save())) return
    try {
      await api(`/api/clips/${id}/render`, { method: "POST" })
      await load()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  function onWordClick(w: Word) {
    if (clickMode === "start") {
      setRange(([, e]) => [Math.min(w.s, e - 1), e])
      setDirty(true)
    } else if (clickMode === "end") {
      setRange(([s]) => [s, Math.max(w.e + 0.15, s + 1)])
      setDirty(true)
    }
    setSeekTo({ t: w.s, n: Date.now() })
  }

  if (error) return <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>
  if (!clip || !edit || !presets || !style) return <Skeleton className="h-[70vh] w-full rounded-xl" />

  const [outW, outH] = ASPECT_SIZE[aspect] ?? ASPECT_SIZE["9:16"]
  const pStart = clip.preview_offset
  const pEnd = clip.preview_offset + (clip.preview_duration ?? clip.end - clip.start + 60)
  const v = encodeURIComponent(clip.updated_at ?? "")
  const upscale = clip.render_info.upscale

  return (
    <div className="space-y-4 pb-24">
      <Link href={`/projects/${clip.project.id}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> {t.editor.back}
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <ScoreBadge score={clip.virality_score} />
        <h1 className="min-w-0 flex-1 truncate text-xl font-semibold">{meta.title}</h1>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(280px,420px)_1fr]">
        {/* left: player */}
        <div className="space-y-3 lg:sticky lg:top-20 lg:self-start">
          {clip.has_video && (
            <div className="flex justify-center">
              <Tabs value={view} onValueChange={(x) => setView(x as "live" | "rendered")}>
                <TabsList>
                  <TabsTrigger value="live">{t.editor.previewNote}</TabsTrigger>
                  <TabsTrigger value="rendered" data-testid="tab-rendered">MP4</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          )}
          {view === "rendered" && clip.has_video ? (
            <video
              key={v}
              src={`/api/clips/${id}/video?v=${v}`}
              controls
              playsInline
              className="mx-auto max-h-[70vh] rounded-xl bg-black"
              data-testid="rendered-video"
            />
          ) : clip.has_preview ? (
            <PreviewPlayer
              src={`/api/clips/${id}/preview`}
              previewOffset={pStart}
              start={range[0]}
              end={range[1]}
              plan={plan}
              outW={outW}
              outH={outH}
              words={clipWords}
              style={style}
              keywords={clip.keywords}
              emojis={clip.emojis}
              emojiStems={(presets as unknown as { emoji_stems: Record<string, string> }).emoji_stems ?? {}}
              hook={edit.hook_enabled ? { text: edit.hook_text, def: presets.hook } : null}
              showCaptions={edit.captions_enabled}
              brand={brand}
              seekTo={seekTo}
              onTime={(st) => {
                const now = performance.now()
                if (now - lastTimeUpdate.current > 120) {
                  lastTimeUpdate.current = now
                  setCurTime(st)
                }
              }}
            />
          ) : (
            <Skeleton className="mx-auto aspect-[9/16] w-full max-w-[340px]" />
          )}
          {rendering && (
            <div className="space-y-1">
              <p className="flex items-center gap-2 text-sm">
                <Loader2 className="size-4 animate-spin" /> {clip.render_status === "queued" ? t.clip.queued : t.clip.rendering}
              </p>
              <Progress value={clip.render_progress} />
            </div>
          )}
          {clip.render_status === "failed" && clip.render_error && (
            <Alert variant="destructive">
              <AlertDescription>{clip.render_error}</AlertDescription>
            </Alert>
          )}
          {upscale && upscale > 1.05 && <p className="text-xs text-amber-400">{t.clip.upscale(upscale.toFixed(2))}</p>}
          <div className="flex flex-wrap justify-center gap-2">
            <Button variant="outline" size="sm" asChild disabled={!clip.has_video}>
              <a href={`/api/clips/${id}/video?download=1`} data-testid="download-mp4">
                <Download /> {t.clip.download}
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/clips/${id}/srt`}>
                <FileText /> {t.clip.srt}
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/clips/${id}/txt`}>
                <FileText /> {t.clip.txt}
              </a>
            </Button>
          </div>
        </div>

        {/* right: controls */}
        <div className="min-w-0 space-y-4">
          <Card>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-medium">{t.editor.trim}</h2>
                <span className="text-sm tabular-nums text-muted-foreground">
                  {formatDuration(range[0])} – {formatDuration(range[1])} ({(range[1] - range[0]).toFixed(1)} s)
                </span>
              </div>
              <Slider
                value={range}
                min={pStart}
                max={pEnd}
                step={0.1}
                minStepsBetweenThumbs={10}
                onValueChange={(r) => {
                  setRange([r[0], r[1]])
                  setDirty(true)
                }}
                data-testid="trim-slider"
              />
              <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">{t.editor.start} (s)</Label>
                  <Input
                    type="number"
                    step={0.1}
                    value={range[0].toFixed(2)}
                    onChange={(e) => {
                      setRange([Math.max(pStart, Number(e.target.value)), range[1]])
                      setDirty(true)
                    }}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">{t.editor.end} (s)</Label>
                  <Input
                    type="number"
                    step={0.1}
                    value={range[1].toFixed(2)}
                    onChange={(e) => {
                      setRange([range[0], Math.min(pEnd, Number(e.target.value))])
                      setDirty(true)
                    }}
                  />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">{t.editor.clickSets}</span>
                {(["seek", "start", "end"] as const).map((m) => (
                  <Button key={m} size="xs" variant={clickMode === m ? "default" : "outline"} onClick={() => setClickMode(m)} data-testid={`click-${m}`}>
                    {m === "seek" ? t.editor.seekOnly : m === "start" ? t.editor.setStart : t.editor.setEnd}
                  </Button>
                ))}
              </div>
              <ScrollArea className="h-48 rounded-lg border p-3">
                <p className="text-sm leading-7" data-testid="transcript">
                  {clip.words.map((w) => {
                    const inClip = w.e > range[0] && w.s < range[1]
                    const active = curTime >= w.s && curTime < w.e
                    const edited = edit.word_edits[String(w.i)] !== undefined
                    return (
                      <span key={w.i}>
                        <button
                          type="button"
                          onClick={() => onWordClick(w)}
                          onDoubleClick={() => {
                            setEditingWord(w)
                            setWordText(edit.word_edits[String(w.i)] ?? w.w)
                          }}
                          className={cn(
                            "rounded px-0.5 transition-colors hover:bg-primary/30",
                            inClip ? "text-foreground" : "text-muted-foreground/50",
                            active && "bg-primary text-primary-foreground",
                            edited && "underline decoration-primary decoration-dotted",
                          )}
                          title={`${formatDuration(w.s)} – ${t.editor.transcriptHint}`}
                        >
                          {edit.word_edits[String(w.i)] ?? w.w}
                        </button>{" "}
                      </span>
                    )
                  })}
                </p>
              </ScrollArea>
              <p className="text-xs text-muted-foreground">{t.editor.transcriptHint}</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Tabs defaultValue="style">
                <TabsList className="mb-4">
                  <TabsTrigger value="style">{t.editor.style}</TabsTrigger>
                  <TabsTrigger value="video">{t.editor.video}</TabsTrigger>
                  <TabsTrigger value="texts">{t.editor.texts}</TabsTrigger>
                </TabsList>
                <TabsContent value="style">
                  <StylePanel
                    data={presets}
                    presetId={edit.preset_id}
                    style={style}
                    onPreset={(pid) => patchEdit({ preset_id: pid, style: {} })}
                    onStyle={patchStyle}
                    reloadPresets={reloadPresets}
                  />
                </TabsContent>
                <TabsContent value="video" className="space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">{t.editor.aspect}</Label>
                      <div className="grid grid-cols-3 gap-1">
                        {["9:16", "1:1", "16:9"].map((a) => (
                          <Button key={a} size="sm" variant={edit.aspect === a ? "default" : "outline"} onClick={() => patchEdit({ aspect: a })} data-testid={`aspect-${a}`}>
                            {a}
                          </Button>
                        ))}
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">{t.editor.layout}</Label>
                      <Select value={edit.layout} onValueChange={(x) => patchEdit({ layout: x })}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {Object.entries(t.editor.layouts).map(([k, l]) => (
                            <SelectItem key={k} value={k}>
                              {l}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">{t.editor.resolution}</Label>
                      <Select value={edit.resolution} onValueChange={(x) => patchEdit({ resolution: x })}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {Object.entries(t.editor.resolutions).map(([k, l]) => (
                            <SelectItem key={k} value={k}>
                              {l}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">{t.editor.brand}</Label>
                      <Select value={edit.brand_template_id || "none"} onValueChange={(x) => patchEdit({ brand_template_id: x === "none" ? null : x })}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">{t.editor.noBrand}</SelectItem>
                          {brands?.map((b) => (
                            <SelectItem key={b.id} value={b.id}>
                              {b.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  {plan && plan.layout !== "blur" && edit.layout === "auto" && plan.speakers >= 2 && (
                    <p className="text-xs text-muted-foreground">Ve videu jsou {plan.speakers} mluvčí – zkuste i layout Split screen.</p>
                  )}
                  <div className="space-y-2">
                    {(
                      [
                        ["captions_enabled", t.editor.captions],
                        ["hook_enabled", t.editor.hook],
                        ["remove_silence", t.editor.removeSilence],
                        ["remove_fillers", t.editor.removeFillers],
                      ] as const
                    ).map(([key, label]) => (
                      <div key={key} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                        <Label htmlFor={key}>{label}</Label>
                        <Switch id={key} checked={!!edit[key]} onCheckedChange={(x) => patchEdit({ [key]: x } as Partial<ClipEdit>)} data-testid={`switch-${key}`} />
                      </div>
                    ))}
                  </div>
                  {edit.hook_enabled && (
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">{t.editor.hookText}</Label>
                      <Input value={edit.hook_text} maxLength={200} onChange={(e) => patchEdit({ hook_text: e.target.value })} />
                    </div>
                  )}
                  {(edit.remove_silence || edit.remove_fillers) && <p className="text-xs text-muted-foreground">{t.editor.cutsNote}</p>}
                </TabsContent>
                <TabsContent value="texts" className="space-y-4">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">{t.editor.titleLabel}</Label>
                    <Input value={meta.title} onChange={(e) => (setMeta({ ...meta, title: e.target.value }), setDirty(true))} />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">{t.editor.description}</Label>
                    <Textarea rows={4} value={meta.description} onChange={(e) => (setMeta({ ...meta, description: e.target.value }), setDirty(true))} />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">{t.editor.hashtags}</Label>
                    <Input value={meta.hashtags} onChange={(e) => (setMeta({ ...meta, hashtags: e.target.value }), setDirty(true))} />
                  </div>
                  <div className="space-y-2 rounded-lg border p-3">
                    <ScoreBars scores={clip.scores} />
                    <p className="text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{t.clip.why}: </span>
                      {clip.reason}
                    </p>
                  </div>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* sticky action bar */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-3">
          <span className={cn("mr-auto text-sm", dirty || clip.dirty ? "text-amber-400" : "text-muted-foreground")}>
            {dirty ? t.editor.unsaved : clip.dirty ? t.clip.notRendered : ""}
          </span>
          <Button variant="outline" onClick={save} disabled={!dirty || saving} data-testid="save-clip">
            <Save /> {t.editor.save}
          </Button>
          <Button onClick={saveAndRender} disabled={saving || rendering} data-testid="render-clip">
            {rendering ? <Loader2 className="animate-spin" /> : <Wand2 />} {dirty ? t.editor.renderSaved : t.editor.render}
          </Button>
        </div>
      </div>

      <Dialog open={!!editingWord} onOpenChange={(o) => !o && setEditingWord(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.editor.editWord}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            „{editingWord?.w}“ · {formatDuration(editingWord?.s)}
          </p>
          <Input
            value={wordText}
            onChange={(e) => setWordText(e.target.value)}
            autoFocus
            data-testid="word-input"
            onKeyDown={(e) => {
              if (e.key === "Enter" && editingWord) {
                patchEdit({ word_edits: { ...edit.word_edits, [String(editingWord.i)]: wordText } })
                setEditingWord(null)
              }
            }}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                if (!editingWord) return
                const we = { ...edit.word_edits }
                delete we[String(editingWord.i)]
                patchEdit({ word_edits: we })
                setEditingWord(null)
              }}
            >
              Původní text
            </Button>
            <Button
              onClick={() => {
                if (!editingWord) return
                patchEdit({ word_edits: { ...edit.word_edits, [String(editingWord.i)]: wordText } })
                setEditingWord(null)
              }}
              data-testid="word-save"
            >
              {t.dashboard.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
