/**
 * Browser port of backend/app/pipeline/captions.py (grouping, positions, keyword + emoji
 * matching). Both read the same preset JSON (shared/caption-presets.json via /api/presets),
 * so the preview matches the final libass render. Keep the two files in sync.
 */
import type { PresetsResponse, Style, Word } from "./types"

export const GROUP_PAUSE = 0.6
export const GROUP_TAIL = 0.5
export const GROUP_BRIDGE = 0.6
const SENT_PUNCT = /[.!?…]$/

const ANCHORS: Record<string, Record<string, number>> = {
  portrait: { top: 0.2, middle: 0.5, bottom: 0.72 },
  square: { top: 0.14, middle: 0.5, bottom: 0.8 },
  landscape: { top: 0.12, middle: 0.5, bottom: 0.86 },
}

export type Group = { words: Word[]; start: number; end: number }

export function aspectFamily(w: number, h: number): string {
  const r = w / h
  if (r < 0.9) return "portrait"
  if (r > 1.1) return "landscape"
  return "square"
}

export const scaleFactor = (w: number, h: number) => Math.min(w, h) / 1080

export function displayText(word: Word, style: Style): string {
  const t = word.t ?? word.w
  return style.uppercase ? t.toLocaleUpperCase("cs-CZ") : t
}

export function maxCharsPerGroup(style: Style, w: number, h: number): number {
  const px = style.font_size * scaleFactor(w, h)
  const avg = px * 0.62 + (style.letter_spacing || 0) * scaleFactor(w, h)
  return Math.max(8, Math.floor((w * 0.86) / Math.max(1, avg)))
}

export function groupWords(words: Word[], style: Style, w: number, h: number): Group[] {
  const n = Math.round(style.words_per_group)
  const maxChars = maxCharsPerGroup(style, w, h)
  const groups: Word[][] = []
  let cur: Word[] = []
  const len = (ws: Word[]) => ws.reduce((a, x) => a + displayText(x, style).length, 0) + Math.max(0, ws.length - 1)
  for (const word of words) {
    if (!displayText(word, style).trim()) continue
    if (
      cur.length &&
      (cur.length >= n || word.s - cur[cur.length - 1].e > GROUP_PAUSE || len([...cur, word]) > maxChars)
    ) {
      groups.push(cur)
      cur = []
    }
    cur.push(word)
    if (SENT_PUNCT.test(word.w)) {
      groups.push(cur)
      cur = []
    }
  }
  if (cur.length) groups.push(cur)
  return groups.map((g, i) => {
    const start = g[0].s
    let end = g[g.length - 1].e + GROUP_TAIL
    if (i + 1 < groups.length) {
      const nxt = groups[i + 1][0].s
      if (nxt - g[g.length - 1].e < GROUP_BRIDGE) end = nxt
      end = Math.min(end, nxt)
    }
    return { words: g, start, end: Math.max(end, g[g.length - 1].e) }
  })
}

export function anchorY(style: Style, w: number, h: number): number {
  return h * (ANCHORS[aspectFamily(w, h)][style.position] + (style.offset_y || 0) / 100)
}

export function emojiGeometry(style: Style, w: number, h: number) {
  const sc = scaleFactor(w, h)
  return { size: Math.floor(style.font_size * sc * 1.5), cx: w / 2, cy: anchorY(style, w, h) - style.font_size * sc * 1.45 }
}

export function normWord(w: string): string {
  return w.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")
}

export function keywordMatch(word: string, keywords: string[]): boolean {
  const w = normWord(word)
  if (w.length < 3) return false
  for (const k of keywords) {
    for (const part of normWord(k).split(/\s+/)) {
      if (part.length < 3) continue
      const stem = part.length > 4 ? part.slice(0, Math.max(4, part.length - 2)) : part
      if (w === part || w.startsWith(stem)) return true
    }
  }
  return false
}

export function emojiForWords(
  words: string[],
  ai: { word: string; emoji: string }[],
  stems: Record<string, string>,
): [number, string] | null {
  const aiN = ai.filter((e) => e.emoji).map((e) => [normWord(e.word), e.emoji] as const)
  for (let i = 0; i < words.length; i++) {
    const w = normWord(words[i])
    if (w.length < 3) continue
    for (const [k, em] of aiN) {
      if (k && (w === k || (k.length >= 4 && w.startsWith(k.slice(0, Math.max(4, k.length - 2)))))) return [i, em]
    }
  }
  for (let i = 0; i < words.length; i++) {
    const w = normWord(words[i])
    if (w.length < 2) continue
    for (const [stem, em] of Object.entries(stems)) {
      if ((stem.length <= 3 && w === stem) || (stem.length > 3 && w.startsWith(stem))) return [i, em]
    }
  }
  return null
}

export type EmojiEvent = { start: number; end: number; emoji: string }

export function emojiEvents(
  groups: Group[],
  style: Style,
  ai: { word: string; emoji: string }[],
  stems: Record<string, string>,
): EmojiEvent[] {
  if (!style.emoji) return []
  const out: EmojiEvent[] = []
  let lastEnd = -1
  for (const g of groups) {
    const found = emojiForWords(g.words.map((w) => w.w), ai, stems)
    if (!found) continue
    const [idx, em] = found
    const s = g.words[idx].s
    if (s < lastEnd + 0.4) continue
    const e = Math.max(g.end, s + 0.9)
    out.push({ start: s, end: e, emoji: em })
    lastEnd = e
  }
  return out
}

export function lerpColor(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16))
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16))
  return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("")
}

export function rgba(hex: string, alpha: number): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return `rgba(${r},${g},${b},${alpha})`
}

function deepMerge<T>(base: T, over: unknown): T {
  if (!over || typeof over !== "object") return base
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) }
  for (const [k, v] of Object.entries(over as Record<string, unknown>)) {
    if (v === null || v === undefined) continue
    const bv = out[k]
    out[k] = v && typeof v === "object" && !Array.isArray(v) && bv && typeof bv === "object" ? deepMerge(bv, v) : v
  }
  return out as T
}

/** defaults <- preset (built-in or user) <- overrides; mirrors presets.resolve_style. */
export function resolveStyle(data: PresetsResponse, presetId: string, overrides?: Partial<Style>): Style {
  let style = { ...data.defaults }
  const user = data.user_presets.find((p) => p.id === presetId)
  if (user) style = deepMerge(style, user.style)
  else {
    const p = data.presets.find((x) => x.id === presetId) ?? data.presets.find((x) => x.id === "bold-pop")
    style = deepMerge(style, p?.style)
  }
  style = deepMerge(style, overrides)
  style.words_per_group = Math.max(1, Math.min(4, Math.round(style.words_per_group)))
  return style
}
