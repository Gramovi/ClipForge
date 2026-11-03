/** Minimal fetch wrapper for the same-origin /api proxy (cookies carry the session). */

export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

function messageFrom(data: unknown, status: number): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail
    if (typeof d === "string") return d
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message)
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String(x.msg) : String(x))).join("; ")
  }
  if (status === 413) return "Soubor je příliš velký."
  if (status >= 500) return "Server je dočasně nedostupný. Zkuste to prosím znovu."
  return `Chyba ${status}`
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init
  let res: Response
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      ...rest,
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    })
  } catch {
    throw new ApiError(0, "Nelze se spojit se serverem. Zkontrolujte připojení.")
  }
  const ct = res.headers.get("content-type") || ""
  const data = ct.includes("application/json") ? await res.json().catch(() => null) : await res.text().catch(() => null)
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/")) {
      window.location.href = "/login"
    }
    throw new ApiError(res.status, messageFrom(data, res.status), data)
  }
  return data as T
}

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "–"
  const s = Math.max(0, Math.round(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`
}

export function formatEta(sec: number | null | undefined): string {
  if (sec == null) return ""
  if (sec < 60) return `${Math.max(1, Math.round(sec))} s`
  if (sec < 3600) return `${Math.round(sec / 60)} min`
  return `${Math.floor(sec / 3600)} h ${Math.round((sec % 3600) / 60)} min`
}

export function formatBytes(b: number): string {
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(1)} GB`
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(0)} MB`
  return `${Math.round(b / 1024)} kB`
}

export function parseTime(v: string): number | null {
  const s = v.trim()
  if (!s) return null
  if (!/^\d+(:\d{1,2}){0,2}(\.\d+)?$/.test(s)) return NaN
  return s.split(":").reduce((acc, p) => acc * 60 + parseFloat(p), 0)
}
