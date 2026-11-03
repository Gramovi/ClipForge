"use client"

import { useMemo, type CSSProperties } from "react"

import { anchorY, emojiEvents, emojiGeometry, groupWords, keywordMatch, lerpColor, rgba, scaleFactor, displayText } from "@/lib/captions"
import type { HookDef, Style, Word } from "@/lib/types"

type Props = {
  words: Word[] // output time (seconds from clip start)
  style: Style
  outW: number
  outH: number
  displayW: number
  time: number
  keywords?: string[]
  emojis?: { word: string; emoji: string }[]
  emojiStems?: Record<string, string>
  hook?: { text: string; def: HookDef } | null
  showCaptions?: boolean
}

export const fontFamily = (id: string) => `cf-${id.replace(/[^a-z0-9-]/gi, "-")}`

/**
 * Renders captions exactly as the ASS generator lays them out: same groups, same anchor,
 * same sizes (scaled to the preview width), same colours and animations.
 */
export function CaptionOverlay({
  words, style, outW, outH, displayW, time, keywords = [], emojis = [], emojiStems = {}, hook, showCaptions = true,
}: Props) {
  const groups = useMemo(() => groupWords(words, style, outW, outH), [words, style, outW, outH])
  const emojiEvs = useMemo(() => emojiEvents(groups, style, emojis, emojiStems), [groups, style, emojis, emojiStems])
  const scale = displayW / outW
  const sf = scaleFactor(outW, outH)
  const fs = style.font_size * sf * scale
  const y = anchorY(style, outW, outH) * scale
  const group = showCaptions ? groups.find((g) => time >= g.start && time < g.end) : undefined

  let k = 0
  if (group) {
    for (let i = 0; i < group.words.length; i++) if (group.words[i].s <= time) k = i
  }
  const texts = group ? group.words.map((w) => displayText(w, style)) : []
  const totalChars = texts.reduce((a, t) => a + t.length, 0) + Math.max(0, texts.length - 1)

  const box = style.background?.enabled
  const outline = style.outline_width * sf * scale
  const shadows: string[] = []
  if (!box && style.shadow_depth > 0) {
    const d = style.shadow_depth * sf * scale
    shadows.push(`${d}px ${d}px 0 ${rgba(style.shadow_color, style.shadow_opacity)}`)
  }
  if (!box && style.glow?.enabled) {
    const g = style.glow.strength * sf * scale
    shadows.push(`0 0 ${g}px ${style.glow.color}`, `0 0 ${g * 2}px ${style.glow.color}`, `0 0 ${g * 3}px ${style.glow.color}`)
  }
  let opacity = 1
  if (group && style.animation === "fade") {
    opacity = Math.min(1, (time - group.start) / 0.15, (group.end - time) / 0.12)
  }

  const textStyle: CSSProperties = {
    fontFamily: `${fontFamily(style.font)}, sans-serif`,
    fontSize: fs,
    lineHeight: 1.18,
    letterSpacing: (style.letter_spacing || 0) * sf * scale,
    color: style.text_color,
    WebkitTextStroke: !box && outline > 0 ? `${outline * 2}px ${style.outline_color}` : undefined,
    paintOrder: "stroke fill",
    textShadow: shadows.join(", ") || undefined,
    whiteSpace: "pre-wrap",
  }
  const pad = (style.background?.padding ?? 16) * sf * scale

  const em = emojiEvs.find((e) => time >= e.start && time < e.end)
  const eg = emojiGeometry(style, outW, outH)

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {group && (
        <div
          className="absolute text-center"
          style={{
            left: "50%",
            top: y,
            width: (outW - 80) * scale,
            transform: `translate(-50%, -50%) rotate(${style.rotation || 0}deg)`,
            opacity,
          }}
        >
          <span
            style={{
              ...textStyle,
              background: box ? rgba(style.background.color, style.background.opacity) : undefined,
              padding: box ? `${pad * 0.35}px ${pad}px` : undefined,
              boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone",
            }}
          >
            {group.words.map((w, j) => {
              const t = texts[j]
              let color = style.text_color
              if (style.highlight_mode === "keywords" && keywordMatch(w.w, keywords)) color = style.highlight_color
              if (style.highlight_mode === "active_word" && j === k) color = style.highlight_color
              const charOffset = texts.slice(0, j).reduce((a, x) => a + x.length + 1, 0)
              const animate = j === k && (style.animation === "pop" || style.animation === "bounce") && style.highlight_mode !== "none"
              const staticScale = j === k && style.highlight_mode === "none" && style.animation !== "none" && style.animation !== "fade" && style.animation !== "typewriter" ? style.active_scale : 1
              const a = animate ? style.active_scale : staticScale
              const spanStyle: CSSProperties = {
                display: "inline-block",
                fontSize: fs * a,
                ["--cf-a" as string]: `${fs * a}px`,
                animation: animate ? `${style.animation === "pop" ? "cf-pop" : "cf-bounce"} ${style.animation === "pop" ? 120 : 180}ms ease-out` : undefined,
                whiteSpace: "pre",
              }
              let content: React.ReactNode
              if (style.highlight_mode === "karaoke") {
                const next = j + 1 < group.words.length ? group.words[j + 1].s : w.e
                const dur = Math.max(0.05, next - w.s)
                const p = Math.max(0, Math.min(1, (time - w.s) / dur)) * 100
                // two layers like libass \kf: base text + highlight colour revealed left-to-right
                content = (
                  <span style={{ position: "relative", display: "inline-block", color: style.text_color }}>
                    {t}
                    <span
                      aria-hidden
                      style={{ position: "absolute", left: 0, top: 0, color: style.highlight_color, clipPath: `inset(0 ${100 - p}% 0 0)` }}
                    >
                      {t}
                    </span>
                  </span>
                )
              } else if (style.gradient?.enabled) {
                content = Array.from(t).map((ch, i) => (
                  <span key={i} style={{ color: lerpColor(style.gradient.from, style.gradient.to, (charOffset + i) / Math.max(1, totalChars - 1)) }}>
                    {ch}
                  </span>
                ))
              } else if (style.animation === "typewriter") {
                if (j > k) content = <span style={{ visibility: "hidden" }}>{t}</span>
                else if (j < k) content = <span style={{ color }}>{t}</span>
                else {
                  const sliceEnd = k === group.words.length - 1 ? group.end : group.words[k + 1].s
                  const wd = Math.max(0.05, Math.min(w.e, sliceEnd) - w.s)
                  const shown = time < w.s ? 0 : Math.min(t.length, Math.floor((time - w.s) / (wd / Math.max(1, t.length))) + 1)
                  content = (
                    <span style={{ color }}>
                      {t.slice(0, shown)}
                      <span style={{ visibility: "hidden" }}>{t.slice(shown)}</span>
                    </span>
                  )
                }
              } else content = <span style={{ color }}>{t}</span>
              return (
                <span key={`${group.start}-${j}-${j === k ? "a" : "i"}`}>
                  <span style={spanStyle}>{content}</span>
                  {j + 1 < group.words.length ? " " : ""}
                </span>
              )
            })}
          </span>
        </div>
      )}
      {em && (
        <div
          className="absolute"
          style={{
            left: eg.cx * scale,
            top: eg.cy * scale,
            fontSize: eg.size * scale * 0.82,
            lineHeight: 1,
            transform: "translate(-50%, -50%)",
            fontFamily: "'Noto Color Emoji', 'Apple Color Emoji', 'Segoe UI Emoji', sans-serif",
          }}
        >
          {em.emoji}
        </div>
      )}
      {hook && hook.text && time < hook.def.duration && (
        <div
          className="absolute text-center"
          style={{
            left: "50%",
            top: outH * hook.def.position_y * scale,
            width: outW * 0.84 * scale,
            transform: `translate(-50%, -50%) scale(${Math.min(1, 0.8 + (time / 0.16) * 0.2)})`,
            opacity: Math.min(1, time / 0.12, (hook.def.duration - time) / 0.2),
          }}
        >
          <span
            style={{
              fontFamily: `${fontFamily(hook.def.font)}, sans-serif`,
              fontSize: hook.def.font_size * sf * scale,
              lineHeight: 1.2,
              color: hook.def.text_color,
              background: rgba(hook.def.background_color, hook.def.background_opacity),
              padding: `${8 * sf * scale}px ${22 * sf * scale}px`,
              boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone",
            }}
          >
            {hook.text}
          </span>
        </div>
      )}
    </div>
  )
}
