"use client"

import { AlertTriangle, CheckCircle2, Link2, Pause, Play, Rocket, UploadCloud, X } from "lucide-react"
import { useRouter } from "next/navigation"
import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"

import { PresetPicker } from "@/components/preset-picker"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, formatBytes, parseTime } from "@/lib/api"
import { useCaptionFonts, useOptions, usePresets, useSystem } from "@/lib/hooks"
import { t } from "@/lib/i18n"
import type { Project } from "@/lib/types"
import { ResumableUpload, type UploadState } from "@/lib/upload"
import { cn } from "@/lib/utils"

export default function NewProjectPage() {
  const router = useRouter()
  const { data: presets } = usePresets()
  const { data: options } = useOptions()
  const { data: system } = useSystem()
  useCaptionFonts(presets?.fonts)

  const [tab, setTab] = useState("upload")
  const [file, setFile] = useState<File | null>(null)
  const [up, setUp] = useState<UploadState | null>(null)
  const uploader = useRef<ResumableUpload | null>(null)
  const [uploadId, setUploadId] = useState<string | null>(null)
  const [url, setUrl] = useState("")
  const [drag, setDrag] = useState(false)

  const [name, setName] = useState("")
  const [length, setLength] = useState("auto")
  const [aspect, setAspect] = useState("9:16")
  const [language, setLanguage] = useState("auto")
  const [whisper, setWhisper] = useState("server")
  const [focus, setFocus] = useState("")
  const [from, setFrom] = useState("")
  const [to, setTo] = useState("")
  const [preset, setPreset] = useState("bold-pop")
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const startUpload = useCallback(
    async (f: File) => {
      if (system && f.size > system.max_upload_bytes) {
        toast.error(`Soubor je příliš velký (limit ${formatBytes(system.max_upload_bytes)}).`)
        return
      }
      setFile(f)
      setUploadId(null)
      if (!name) setName(f.name.replace(/\.[^.]+$/, ""))
      const u = new ResumableUpload(f, setUp)
      uploader.current = u
      const id = await u.start()
      if (id) setUploadId(id)
    },
    [name, system],
  )

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDrag(false)
    const f = e.dataTransfer.files?.[0]
    if (f) void startUpload(f)
  }

  async function resume() {
    if (!uploader.current) return
    const id = await uploader.current.start()
    if (id) setUploadId(id)
  }

  async function submit() {
    if (tab === "upload" && !file) return toast.error(t.newProject.needSource)
    if (tab === "upload" && !uploadId) return toast.error(t.newProject.waitUpload)
    if (tab === "url" && !url.trim()) return toast.error(t.newProject.needSource)
    const rs = parseTime(from)
    const re = parseTime(to)
    if (Number.isNaN(rs) || Number.isNaN(re)) return toast.error(t.newProject.badTime)
    setBusy(true)
    try {
      const p = await api<Project>("/api/projects", {
        method: "POST",
        json: {
          name: name || undefined,
          upload_id: tab === "upload" ? uploadId : undefined,
          url: tab === "url" ? url.trim() : undefined,
          settings: {
            clip_length: length,
            aspect,
            language,
            preset_id: preset,
            focus: focus.trim() || null,
            range_start: rs,
            range_end: re,
            whisper_model: whisper === "server" ? null : whisper,
          },
        },
      })
      router.push(`/projects/${p.id}`)
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(false)
    }
  }

  const pct = up ? (up.received / Math.max(1, up.size)) * 100 : 0
  const whisperWarning = options?.whisper_models.find((m) => m.id === whisper)?.warning
  const czechish = language === "cs" || language === "sk" || language === "auto"

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t.newProject.title}</h1>

      <Card>
        <CardHeader>
          <CardTitle>{t.newProject.sourceTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="upload">
                <UploadCloud /> {t.newProject.tabUpload}
              </TabsTrigger>
              {system?.allow_url_import !== false && (
                <TabsTrigger value="url">
                  <Link2 /> {t.newProject.tabUrl}
                </TabsTrigger>
              )}
            </TabsList>
            <TabsContent value="upload" className="pt-4">
              {!file ? (
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDrag(true)
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={onDrop}
                  data-testid="dropzone"
                  className={cn(
                    "flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed p-10 text-center transition-colors",
                    drag ? "border-primary bg-primary/10" : "border-border hover:border-primary/60",
                  )}
                >
                  <UploadCloud className="size-10 text-primary" />
                  <span className="text-lg font-medium">{t.newProject.drop}</span>
                  <span className="text-sm text-muted-foreground">{t.newProject.dropOr}</span>
                  <span className="text-xs text-muted-foreground">
                    {t.newProject.dropHint(system ? formatBytes(system.max_upload_bytes) : "5 GB")}
                  </span>
                </button>
              ) : (
                <div className="space-y-3 rounded-xl border p-4">
                  <div className="flex items-center gap-3">
                    {up?.status === "done" ? (
                      <CheckCircle2 className="size-5 shrink-0 text-emerald-400" />
                    ) : (
                      <UploadCloud className="size-5 shrink-0 text-primary" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatBytes(up?.received ?? 0)} / {formatBytes(file.size)}
                        {up?.status === "uploading" && up.speed > 0 && ` · ${formatBytes(up.speed)}/s`}
                        {" · "}
                        {up?.status === "done" ? t.newProject.uploaded : up?.status === "paused" ? t.newProject.paused : `${t.newProject.uploading} ${pct.toFixed(0)} %`}
                      </p>
                    </div>
                    {up?.status === "uploading" && (
                      <Button size="sm" variant="outline" onClick={() => uploader.current?.pause()}>
                        <Pause /> {t.newProject.pause}
                      </Button>
                    )}
                    {(up?.status === "paused" || up?.status === "error") && (
                      <Button size="sm" variant="outline" onClick={resume}>
                        <Play /> {t.newProject.resume}
                      </Button>
                    )}
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t.newProject.remove}
                      onClick={() => {
                        uploader.current?.pause()
                        setFile(null)
                        setUp(null)
                        setUploadId(null)
                      }}
                    >
                      <X />
                    </Button>
                  </div>
                  <Progress value={pct} data-testid="upload-progress" />
                  {up?.resumed && <p className="text-xs text-muted-foreground">{t.newProject.resumed}</p>}
                  {up?.error && (
                    <Alert variant="destructive">
                      <AlertDescription>{up.error}</AlertDescription>
                    </Alert>
                  )}
                </div>
              )}
              <input
                ref={inputRef}
                type="file"
                accept="video/*,.mkv,.mov,.mp4,.webm"
                className="hidden"
                data-testid="file-input"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void startUpload(f)
                  e.target.value = ""
                }}
              />
            </TabsContent>
            <TabsContent value="url" className="space-y-3 pt-4">
              <Label htmlFor="url">{t.newProject.urlLabel}</Label>
              <Input id="url" placeholder={t.newProject.urlPlaceholder} value={url} onChange={(e) => setUrl(e.target.value)} />
              <Alert>
                <AlertTriangle />
                <AlertDescription>{t.newProject.rightsNote}</AlertDescription>
              </Alert>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.newProject.settingsTitle}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="name">{t.newProject.name}</Label>
            <Input id="name" value={name} placeholder={t.newProject.namePlaceholder} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>{t.newProject.length}</Label>
            <Select value={length} onValueChange={setLength}>
              <SelectTrigger className="w-full" data-testid="length-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(t.newProject.lengths).map(([k, v]) => (
                  <SelectItem key={k} value={k}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t.newProject.aspect}</Label>
            <div className="grid grid-cols-3 gap-2">
              {Object.keys(t.newProject.aspects).map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAspect(a)}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border p-2 text-xs transition-colors",
                    aspect === a ? "border-primary bg-primary/10" : "hover:border-primary/50",
                  )}
                  title={t.newProject.aspects[a]}
                >
                  <span
                    className="rounded-sm border-2 border-current"
                    style={{ width: a === "16:9" ? 32 : a === "1:1" ? 22 : 16, height: a === "9:16" ? 28 : a === "1:1" ? 22 : 18 }}
                  />
                  {a}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t.newProject.language}</Label>
            <Select value={language} onValueChange={setLanguage}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(options?.languages ?? { auto: "Automaticky", cs: "Čeština" }).map(([k, v]) => (
                  <SelectItem key={k} value={k}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t.newProject.whisper}</Label>
            <Select value={whisper} onValueChange={setWhisper}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="server">{t.newProject.whisperDefault(system?.whisper_model ?? "large-v3")}</SelectItem>
                {options?.whisper_models.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {czechish && (
              <p className={cn("text-xs", whisperWarning ? "text-amber-400" : "text-muted-foreground")}>
                {whisperWarning ? `${whisperWarning} ` : ""}
                {t.newProject.czechHint}
              </p>
            )}
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="focus">{t.newProject.focus}</Label>
            <Input id="focus" value={focus} placeholder={t.newProject.focusPlaceholder} onChange={(e) => setFocus(e.target.value)} />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label>{t.newProject.range}</Label>
            <div className="flex gap-3">
              <Input placeholder={t.newProject.rangeFrom} value={from} onChange={(e) => setFrom(e.target.value)} className="max-w-40" />
              <Input placeholder={t.newProject.rangeTo} value={to} onChange={(e) => setTo(e.target.value)} className="max-w-40" />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.newProject.presetTitle}</CardTitle>
        </CardHeader>
        <CardContent>{presets ? <PresetPicker data={presets} value={preset} onChange={setPreset} /> : t.common.loading}</CardContent>
      </Card>

      <div className="flex justify-end pb-10">
        <Button size="lg" onClick={submit} disabled={busy || (tab === "upload" && !uploadId)} data-testid="start-processing">
          <Rocket /> {t.newProject.start}
        </Button>
      </div>
    </div>
  )
}
