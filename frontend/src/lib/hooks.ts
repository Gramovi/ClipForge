"use client"

import { useCallback, useEffect, useState } from "react"

import { api } from "./api"
import type { Options, PresetsResponse, SystemInfo } from "./types"

type PresetsWithEmoji = PresetsResponse & { emoji_stems: Record<string, string> }

export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!!path)
  const reload = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      setData(await api<T>(path))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [path])
  useEffect(() => {
    void reload()
  }, [reload])
  return { data, error, loading, reload, setData }
}

export const usePresets = () => useFetch<PresetsWithEmoji>("/api/presets")
export const useOptions = () => useFetch<Options>("/api/options")
export const useSystem = () => useFetch<SystemInfo>("/api/system")

/** Inject @font-face rules for all caption fonts so previews use the real render fonts. */
export function useCaptionFonts(fonts: { id: string; url: string }[] | undefined) {
  useEffect(() => {
    if (!fonts?.length) return
    const id = "cf-font-faces"
    let el = document.getElementById(id) as HTMLStyleElement | null
    if (!el) {
      el = document.createElement("style")
      el.id = id
      document.head.appendChild(el)
    }
    el.textContent = fonts
      .map((f) => `@font-face{font-family:"cf-${f.id.replace(/[^a-z0-9-]/gi, "-")}";src:url("${f.url}");font-display:block;}`)
      .join("\n")
  }, [fonts])
}
