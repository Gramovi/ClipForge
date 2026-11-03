/** Resumable chunked uploader (matches backend /api/uploads). */
import { ApiError, api } from "./api"

type UploadInfo = { id: string; size: number; received: number; status: string; chunk_size: number }

export type UploadState = {
  id: string | null
  received: number
  size: number
  status: "idle" | "uploading" | "paused" | "done" | "error"
  speed: number // bytes/s
  error?: string
  resumed?: boolean
}

const keyFor = (f: File) => `cf-upload:${f.name}:${f.size}:${f.lastModified}`

export class ResumableUpload {
  private file: File
  private onState: (s: UploadState) => void
  private state: UploadState
  private abort: AbortController | null = null

  constructor(file: File, onState: (s: UploadState) => void) {
    this.file = file
    this.onState = onState
    this.state = { id: null, received: 0, size: file.size, status: "idle", speed: 0 }
  }

  private emit(patch: Partial<UploadState>) {
    this.state = { ...this.state, ...patch }
    this.onState(this.state)
  }

  pause() {
    this.abort?.abort()
    this.emit({ status: "paused", speed: 0 })
  }

  async start(): Promise<string | null> {
    this.emit({ status: "uploading", error: undefined })
    try {
      let info: UploadInfo | null = null
      const saved = typeof localStorage !== "undefined" ? localStorage.getItem(keyFor(this.file)) : null
      if (saved) {
        info = await api<UploadInfo>(`/api/uploads/${saved}`).catch(() => null)
        if (info && info.status !== "uploading" && info.status !== "complete") info = null
        if (info) this.emit({ resumed: info.received > 0 })
      }
      if (!info) {
        info = await api<UploadInfo>("/api/uploads", { method: "POST", json: { filename: this.file.name, size: this.file.size } })
        localStorage.setItem(keyFor(this.file), info.id)
      }
      this.emit({ id: info.id, received: info.received })
      let offset = info.received
      const chunk = info.chunk_size
      let failures = 0
      while (offset < this.file.size) {
        if (this.state.status === "paused") return null
        const end = Math.min(this.file.size, offset + chunk)
        const from = offset
        this.abort = new AbortController()
        const t0 = performance.now()
        try {
          const res = await fetch(`/api/uploads/${info.id}?offset=${offset}`, {
            method: "PUT",
            body: this.file.slice(offset, end),
            headers: { "Content-Type": "application/octet-stream" },
            credentials: "same-origin",
            signal: this.abort.signal,
          })
          const data = await res.json().catch(() => null)
          if (res.status === 409 && data?.detail?.received !== undefined) {
            offset = data.detail.received // server knows better -> continue from there
            continue
          }
          if (!res.ok) throw new ApiError(res.status, data?.detail ?? `Chyba ${res.status}`)
          offset = data.received
          failures = 0
          const dt = (performance.now() - t0) / 1000
          this.emit({ received: offset, speed: (end - from) / Math.max(0.05, dt) })
        } catch (e) {
          if ((e as Error).name === "AbortError") return null
          if (e instanceof ApiError && e.status >= 400 && e.status < 500) throw e
          failures += 1
          if (failures > 6) throw e
          await new Promise((r) => setTimeout(r, Math.min(30000, 1000 * 2 ** failures)))
          const st = await api<UploadInfo>(`/api/uploads/${info.id}`).catch(() => null)
          if (st) offset = st.received
        }
      }
      localStorage.removeItem(keyFor(this.file))
      this.emit({ status: "done", received: this.file.size, speed: 0 })
      return info.id
    } catch (e) {
      this.emit({ status: "error", error: e instanceof Error ? e.message : String(e), speed: 0 })
      return null
    }
  }
}
