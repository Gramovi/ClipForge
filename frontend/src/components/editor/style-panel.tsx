"use client"

import { Save, Upload } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { PresetPicker } from "@/components/preset-picker"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import type { PresetDef, PresetsResponse, Style } from "@/lib/types"

type Props = {
  data: PresetsResponse
  presetId: string
  style: Style
  onPreset: (id: string) => void
  onStyle: (patch: Partial<Style>) => void
  reloadPresets: () => Promise<void>
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function ColorInput({ value, onChange, testId }: { value: string; onChange: (v: string) => void; testId?: string }) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        className="h-8 w-10 cursor-pointer rounded border bg-transparent"
        data-testid={testId}
      />
      <span className="font-mono text-xs text-muted-foreground">{value}</span>
    </div>
  )
}

function SliderRow({ label, value, min, max, step = 1, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void }) {
  return (
    <Row label={`${label}: ${Number.isInteger(step) ? Math.round(value) : value.toFixed(2)}`}>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={([v]) => onChange(v)} />
    </Row>
  )
}

export function StylePanel({ data, presetId, style, onPreset, onStyle, reloadPresets }: Props) {
  const fontInput = useRef<HTMLInputElement>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState("")

  async function uploadFont(f: File) {
    const fd = new FormData()
    fd.append("file", f)
    try {
      const font = await api<{ id: string; family: string }>("/api/fonts", { method: "POST", body: fd })
      await reloadPresets()
      onStyle({ font: font.id })
      toast.success(`Font ${font.family} nahrán`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function savePreset() {
    try {
      const builtin = data.presets.find((p) => p.id === presetId)
      const p = await api<PresetDef>("/api/presets", {
        method: "POST",
        json: { name, base_id: builtin ? builtin.id : "bold-pop", style },
      })
      await reloadPresets()
      onPreset(p.id)
      setSaveOpen(false)
      toast.success(`Preset „${p.name}“ uložen`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div className="space-y-5">
      <PresetPicker data={data} value={presetId} onChange={onPreset} compact />
      <div className="grid gap-4 sm:grid-cols-2">
        <Row label={t.editor.font}>
          <div className="flex gap-2">
            <Select value={style.font} onValueChange={(v) => onStyle({ font: v })}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {data.fonts.map((f) => (
                  <SelectItem key={f.id} value={f.id}>
                    <span style={{ fontFamily: `cf-${f.id.replace(/[^a-z0-9-]/gi, "-")}` }}>{f.label}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="icon" title={t.editor.uploadFont} onClick={() => fontInput.current?.click()}>
              <Upload />
            </Button>
            <input
              ref={fontInput}
              type="file"
              accept=".ttf,.otf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void uploadFont(f)
                e.target.value = ""
              }}
            />
          </div>
        </Row>
        <SliderRow label={t.editor.fontSize} value={style.font_size} min={30} max={160} onChange={(v) => onStyle({ font_size: v })} />
        <Row label={t.editor.textColor}>
          <ColorInput value={style.text_color} onChange={(v) => onStyle({ text_color: v })} testId="text-color" />
        </Row>
        <Row label={t.editor.highlightColor}>
          <ColorInput value={style.highlight_color} onChange={(v) => onStyle({ highlight_color: v })} />
        </Row>
        <Row label={t.editor.highlightMode}>
          <Select value={style.highlight_mode} onValueChange={(v) => onStyle({ highlight_mode: v as Style["highlight_mode"] })}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(t.editor.highlightModes).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Row>
        <Row label={t.editor.animation}>
          <Select value={style.animation} onValueChange={(v) => onStyle({ animation: v as Style["animation"] })}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(t.editor.animations).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Row>
        <SliderRow label={t.editor.outline} value={style.outline_width} min={0} max={14} onChange={(v) => onStyle({ outline_width: v })} />
        <Row label={t.editor.outlineColor}>
          <ColorInput value={style.outline_color} onChange={(v) => onStyle({ outline_color: v })} />
        </Row>
        <SliderRow label={t.editor.shadow} value={style.shadow_depth} min={0} max={12} onChange={(v) => onStyle({ shadow_depth: v })} />
        <Row label={t.editor.wordsPerGroup}>
          <div className="grid grid-cols-4 gap-1">
            {[1, 2, 3, 4].map((n) => (
              <Button key={n} size="sm" variant={style.words_per_group === n ? "default" : "outline"} onClick={() => onStyle({ words_per_group: n })}>
                {n}
              </Button>
            ))}
          </div>
        </Row>
        <Row label={t.editor.position}>
          <div className="grid grid-cols-3 gap-1">
            {(["top", "middle", "bottom"] as const).map((pos) => (
              <Button key={pos} size="sm" variant={style.position === pos ? "default" : "outline"} onClick={() => onStyle({ position: pos })} data-testid={`pos-${pos}`}>
                {t.editor.positions[pos]}
              </Button>
            ))}
          </div>
        </Row>
        <SliderRow label={t.editor.offset} value={style.offset_y} min={-25} max={25} onChange={(v) => onStyle({ offset_y: v })} />
        <div className="flex items-center justify-between rounded-lg border px-3 py-2">
          <Label htmlFor="uc">{t.editor.uppercase}</Label>
          <Switch id="uc" checked={style.uppercase} onCheckedChange={(v) => onStyle({ uppercase: v })} />
        </div>
        <div className="flex items-center justify-between rounded-lg border px-3 py-2">
          <Label htmlFor="em">{t.editor.emoji}</Label>
          <Switch id="em" checked={style.emoji} onCheckedChange={(v) => onStyle({ emoji: v })} />
        </div>
        <div className="flex items-center justify-between rounded-lg border px-3 py-2">
          <Label htmlFor="bg">{t.editor.background}</Label>
          <Switch id="bg" checked={style.background.enabled} onCheckedChange={(v) => onStyle({ background: { ...style.background, enabled: v } })} />
        </div>
        {style.background.enabled && (
          <>
            <Row label={t.editor.backgroundColor}>
              <ColorInput value={style.background.color} onChange={(v) => onStyle({ background: { ...style.background, color: v } })} />
            </Row>
            <SliderRow
              label={t.editor.backgroundOpacity}
              value={style.background.opacity}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => onStyle({ background: { ...style.background, opacity: v } })}
            />
          </>
        )}
      </div>
      <Button variant="outline" onClick={() => setSaveOpen(true)}>
        <Save /> {t.editor.savePreset}
      </Button>
      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.editor.savePreset}</DialogTitle>
          </DialogHeader>
          <Input placeholder={t.editor.presetName} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <DialogFooter>
            <Button onClick={savePreset} disabled={!name.trim()}>
              {t.dashboard.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
