export type Word = { w: string; s: number; e: number; i?: number; p?: number; t?: string }

export type Scores = { hook?: number; flow?: number; value?: number; trend?: number }

export type ProjectSettings = {
  clip_length: string
  aspect: string
  resolution: string
  layout: string
  language: string
  preset_id: string
  style: Partial<Style>
  focus?: string | null
  range_start?: number | null
  range_end?: number | null
  whisper_model?: string | null
  brand_template_id?: string | null
}

export type Clip = {
  id: string
  project_id: string
  start: number
  end: number
  duration: number
  title: string
  hook: string
  reason: string
  description: string
  hashtags: string[]
  keywords: string[]
  scores: Scores
  virality_score: number
  render_status: "pending" | "queued" | "rendering" | "ready" | "failed"
  render_progress: number
  render_error: string | null
  dirty: boolean
  has_video: boolean
  render_info: { width?: number; height?: number; layout?: string; upscale?: number; duration?: number }
  edit: Partial<ClipEdit>
  updated_at: string | null
}

export type ClipEdit = {
  aspect: string
  resolution: string
  layout: string
  preset_id: string
  style: Partial<Style>
  word_edits: Record<string, string>
  remove_silence: boolean
  remove_fillers: boolean
  hook_enabled: boolean
  hook_text: string
  brand_template_id: string | null
  captions_enabled: boolean
}

export type ClipDetail = Clip & {
  effective_edit: ClipEdit
  emojis: { word: string; emoji: string }[]
  language: string | null
  preview_offset: number
  preview_duration: number | null
  has_preview: boolean
  project: { id: string; name: string; duration: number; width: number; height: number; fps: number }
  words: Word[]
}

export type Project = {
  id: string
  name: string
  status: "queued" | "processing" | "done" | "failed"
  step: string
  progress: number
  step_progress: number
  eta_seconds: number | null
  message: string | null
  error: string | null
  source_type: string
  source_url: string | null
  duration: number | null
  width: number | null
  height: number | null
  fps: number | null
  language: string | null
  settings: ProjectSettings
  llm_usage: { provider?: string; model?: string; input_tokens?: number; output_tokens?: number; cost_usd?: number | null }
  has_thumbnail: boolean
  clip_count: number
  created_at: string
  updated_at: string
  clips?: Clip[]
  clips_ready?: number
}

export type Style = {
  font: string
  font_size: number
  uppercase: boolean
  letter_spacing: number
  text_color: string
  highlight_color: string
  highlight_mode: "active_word" | "karaoke" | "keywords" | "none"
  outline_color: string
  outline_width: number
  shadow_color: string
  shadow_opacity: number
  shadow_depth: number
  background: { enabled: boolean; color: string; opacity: number; padding: number }
  glow: { enabled: boolean; color: string; strength: number }
  gradient: { enabled: boolean; from: string; to: string }
  position: "top" | "middle" | "bottom"
  offset_y: number
  words_per_group: number
  animation: "none" | "pop" | "bounce" | "fade" | "typewriter"
  active_scale: number
  emoji: boolean
  rotation: number
}

export type PresetDef = { id: string; name: string; description: string; style: Partial<Style>; custom?: boolean; base_id?: string }
export type FontDef = { id: string; label: string; family: string; file: string; weight: number; url: string; custom?: boolean }
export type HookDef = {
  font: string
  font_size: number
  text_color: string
  background_color: string
  background_opacity: number
  duration: number
  position_y: number
}

export type PresetsResponse = {
  defaults: Style
  presets: PresetDef[]
  user_presets: PresetDef[]
  fonts: FontDef[]
  hook: HookDef
}

export type CropPlan = {
  layout: "track" | "split" | "blur" | "full" | "center"
  crop_w: number
  crop_h: number
  src_w: number
  src_h: number
  out_w: number
  out_h: number
  times: number[]
  xs: number[]
  ys: number[]
  xs2: number[] | null
  ys2: number[] | null
  face_ratio: number
  speakers: number
}

export type BrandTemplate = {
  id: string
  name: string
  logo_position: string
  logo_opacity: number
  logo_scale: number
  primary_color: string
  accent_color: string
  font_id: string | null
  has_logo: boolean
  has_intro: boolean
  has_outro: boolean
  logo_url: string | null
}

export type SystemInfo = {
  llm_provider: string
  llm_model: string
  whisper_model: string
  max_upload_bytes: number
  upload_chunk_bytes: number
  allow_url_import: boolean
  x264_preset: string
  x264_crf: number
  llm_status: { ok: boolean; message: string }
  cost_per_hour?: Record<string, Record<string, { input_tokens: number; output_tokens: number; usd: number | null }>>
  current_cost_per_hour?: Record<string, { input_tokens: number; output_tokens: number; usd: number | null }>
}

export type Options = {
  languages: Record<string, string>
  whisper_models: { id: string; label: string; warning: string }[]
  lengths: Record<string, { min: number; max: number }>
}
