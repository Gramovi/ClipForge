"use client"

import { CheckCircle2, Trash2, XCircle } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { api } from "@/lib/api"
import { useFetch, usePresets, useSystem } from "@/lib/hooks"
import { t } from "@/lib/i18n"
import type { BrandTemplate } from "@/lib/types"

function usd(v: number | null | undefined) {
  if (v == null) return "–"
  return v < 0.01 ? `< $0.01` : `$${v.toFixed(2)}`
}

export default function SettingsPage() {
  const { data: sys } = useSystem()
  const { data: presets, reload: reloadPresets } = usePresets()
  const { data: brands, reload: reloadBrands } = useFetch<BrandTemplate[]>("/api/brand-templates")
  const [brand, setBrand] = useState({ name: "", logo_position: "top-right", logo_opacity: 0.85, logo_scale: 0.18, primary_color: "#FFFFFF", accent_color: "#FFD400" })
  const [files, setFiles] = useState<{ logo?: File; intro?: File; outro?: File }>({})
  const [busy, setBusy] = useState(false)

  async function createBrand(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    const fd = new FormData()
    Object.entries(brand).forEach(([k, v]) => fd.append(k, String(v)))
    if (files.logo) fd.append("logo", files.logo)
    if (files.intro) fd.append("intro", files.intro)
    if (files.outro) fd.append("outro", files.outro)
    try {
      await api("/api/brand-templates", { method: "POST", body: fd })
      setBrand({ ...brand, name: "" })
      setFiles({})
      await reloadBrands()
      toast.success(t.editor.saved)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function del(path: string, after: () => Promise<void>) {
    try {
      await api(path, { method: "DELETE" })
      await after()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t.settings.title}</h1>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.ai}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {sys ? (
            <>
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]" data-testid="ai-settings">
                <dt className="text-muted-foreground">{t.settings.provider}</dt>
                <dd className="font-medium">{sys.llm_provider === "anthropic" ? "Anthropic (Claude)" : "Ollama (lokálně)"}</dd>
                <dt className="text-muted-foreground">{t.settings.model}</dt>
                <dd className="font-mono">{sys.llm_model}</dd>
                <dt className="text-muted-foreground">{t.settings.whisper}</dt>
                <dd className="font-mono">{sys.whisper_model}</dd>
                <dt className="text-muted-foreground">Export</dt>
                <dd className="font-mono">
                  H.264 High · CRF {sys.x264_crf} · preset {sys.x264_preset}
                </dd>
                <dt className="text-muted-foreground">{t.settings.status}</dt>
                <dd className="flex items-start gap-1.5">
                  {sys.llm_status.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-400" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-400" />}
                  <span className={sys.llm_status.ok ? "" : "text-red-300"}>{sys.llm_status.message}</span>
                </dd>
              </dl>
              <p className="text-xs text-muted-foreground">{t.settings.keyHelp}</p>
              {sys.cost_per_hour && (
                <div className="space-y-2">
                  <h3 className="text-sm font-medium">{t.settings.costTitle}</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs text-muted-foreground">
                        <tr>
                          <th className="py-1 pr-4 font-normal">{t.settings.model}</th>
                          <th className="py-1 pr-4 font-normal">{t.settings.czech}</th>
                          <th className="py-1 font-normal">{t.settings.english}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(sys.cost_per_hour).map(([m, c]) => (
                          <tr key={m} className="border-t">
                            <td className="py-1.5 pr-4 font-mono">
                              {m} {m === sys.llm_model && <span className="text-xs text-primary">({t.settings.current})</span>}
                            </td>
                            <td className="py-1.5 pr-4 tabular-nums">{usd(c.cs.usd)}</td>
                            <td className="py-1.5 tabular-nums">{usd(c.en.usd)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-xs text-muted-foreground">{t.settings.costNote}</p>
                </div>
              )}
            </>
          ) : (
            t.common.loading
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.presets}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {presets?.user_presets.length ? (
            presets.user_presets.map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                {p.name}
                <Button size="icon-sm" variant="ghost" aria-label={t.settings.delete} onClick={() => del(`/api/presets/${p.id}`, reloadPresets)}>
                  <Trash2 />
                </Button>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">{t.settings.noPresets}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.fonts}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {presets?.fonts.filter((f) => f.custom).length ? (
            presets.fonts
              .filter((f) => f.custom)
              .map((f) => (
                <div key={f.id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                  <span style={{ fontFamily: `cf-${f.id.replace(/[^a-z0-9-]/gi, "-")}` }}>{f.label}</span>
                  <Button size="icon-sm" variant="ghost" aria-label={t.settings.delete} onClick={() => del(`/api/fonts/${f.id}`, reloadPresets)}>
                    <Trash2 />
                  </Button>
                </div>
              ))
          ) : (
            <p className="text-sm text-muted-foreground">{t.settings.noFonts}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.brand}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {brands?.map((b) => (
            <div key={b.id} className="flex items-center gap-3 rounded-lg border px-3 py-2 text-sm">
              {b.logo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={b.logo_url} alt="" className="size-8 rounded object-contain" />
              ) : (
                <span className="size-8 rounded" style={{ background: b.accent_color }} />
              )}
              <span className="flex-1">{b.name}</span>
              <span className="size-4 rounded-full border" style={{ background: b.primary_color }} />
              <span className="size-4 rounded-full border" style={{ background: b.accent_color }} />
              {b.has_intro && <span className="text-xs text-muted-foreground">intro</span>}
              {b.has_outro && <span className="text-xs text-muted-foreground">outro</span>}
              <Button size="icon-sm" variant="ghost" aria-label={t.settings.delete} onClick={() => del(`/api/brand-templates/${b.id}`, reloadBrands)}>
                <Trash2 />
              </Button>
            </div>
          ))}
          <form onSubmit={createBrand} className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2">
            <h3 className="font-medium sm:col-span-2">{t.settings.newBrand}</h3>
            <div className="space-y-1.5">
              <Label>{t.settings.brandName}</Label>
              <Input required value={brand.name} onChange={(e) => setBrand({ ...brand, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>{t.settings.logo}</Label>
              <Input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFiles({ ...files, logo: e.target.files?.[0] })} />
            </div>
            <div className="space-y-1.5">
              <Label>{t.settings.logoPosition}</Label>
              <Select value={brand.logo_position} onValueChange={(v) => setBrand({ ...brand, logo_position: v })}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(t.settings.logoPositions).map(([k, v]) => (
                    <SelectItem key={k} value={k}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-3">
              <Label>
                {t.settings.logoOpacity}: {Math.round(brand.logo_opacity * 100)} %
              </Label>
              <Slider value={[brand.logo_opacity]} min={0.1} max={1} step={0.05} onValueChange={([v]) => setBrand({ ...brand, logo_opacity: v })} />
              <Label>
                {t.settings.logoScale}: {Math.round(brand.logo_scale * 100)} %
              </Label>
              <Slider value={[brand.logo_scale]} min={0.05} max={0.5} step={0.01} onValueChange={([v]) => setBrand({ ...brand, logo_scale: v })} />
            </div>
            <div className="flex items-center gap-4">
              <Label className="flex items-center gap-2">
                <input type="color" value={brand.primary_color} onChange={(e) => setBrand({ ...brand, primary_color: e.target.value.toUpperCase() })} className="h-8 w-10 rounded border bg-transparent" />
                {t.settings.primary}
              </Label>
              <Label className="flex items-center gap-2">
                <input type="color" value={brand.accent_color} onChange={(e) => setBrand({ ...brand, accent_color: e.target.value.toUpperCase() })} className="h-8 w-10 rounded border bg-transparent" />
                {t.settings.accent}
              </Label>
            </div>
            <div className="space-y-1.5">
              <Label>{t.settings.intro}</Label>
              <Input type="file" accept="video/*" onChange={(e) => setFiles({ ...files, intro: e.target.files?.[0] })} />
            </div>
            <div className="space-y-1.5">
              <Label>{t.settings.outro}</Label>
              <Input type="file" accept="video/*" onChange={(e) => setFiles({ ...files, outro: e.target.files?.[0] })} />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={busy || !brand.name.trim()}>
                {t.settings.create}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
      {!sys?.llm_status.ok && sys && (
        <Alert variant="destructive">
          <AlertDescription>{sys.llm_status.message}</AlertDescription>
        </Alert>
      )}
    </div>
  )
}
