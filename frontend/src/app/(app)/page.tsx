"use client"

import { Clapperboard, Film, MoreVertical, Pencil, Plus, Trash2 } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"

import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { api, formatDuration } from "@/lib/api"
import { useFetch } from "@/lib/hooks"
import { t } from "@/lib/i18n"
import type { Project } from "@/lib/types"

export default function DashboardPage() {
  const { data, loading, error, reload, setData } = useFetch<Project[]>("/api/projects")
  const [renaming, setRenaming] = useState<Project | null>(null)
  const [deleting, setDeleting] = useState<Project | null>(null)
  const [name, setName] = useState("")

  async function rename() {
    if (!renaming) return
    try {
      const p = await api<Project>(`/api/projects/${renaming.id}`, { method: "PATCH", json: { name } })
      setData((d) => d?.map((x) => (x.id === p.id ? { ...x, name: p.name } : x)) ?? null)
      setRenaming(null)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function remove() {
    if (!deleting) return
    try {
      await api(`/api/projects/${deleting.id}`, { method: "DELETE" })
      setData((d) => d?.filter((x) => x.id !== deleting.id) ?? null)
      setDeleting(null)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t.dashboard.title}</h1>
        <Button asChild>
          <Link href="/new">
            <Plus /> {t.nav.newProject}
          </Link>
        </Button>
      </div>

      {error && (
        <Card className="p-6 text-sm">
          {error}{" "}
          <Button variant="link" onClick={reload}>
            {t.common.retry}
          </Button>
        </Card>
      )}

      {loading && !data && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="aspect-video rounded-xl" />
          ))}
        </div>
      )}

      {data && data.length === 0 && (
        <Card className="flex flex-col items-center gap-4 p-10 text-center">
          <Clapperboard className="size-10 text-primary" />
          <p className="max-w-md text-muted-foreground">{t.dashboard.empty}</p>
          <Button asChild size="lg">
            <Link href="/new">
              <Plus /> {t.nav.newProject}
            </Link>
          </Button>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="project-list">
          {data.map((p) => (
            <Card key={p.id} className="group gap-0 overflow-hidden p-0">
              <Link href={`/projects/${p.id}`} className="relative block aspect-video bg-muted">
                {p.has_thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`/api/projects/${p.id}/thumbnail`} alt="" className="size-full object-cover transition-transform group-hover:scale-[1.02]" />
                ) : (
                  <div className="flex size-full items-center justify-center text-muted-foreground">
                    <Film className="size-8" />
                  </div>
                )}
                <div className="absolute left-2 top-2">
                  <StatusBadge status={p.status} />
                </div>
                {p.duration ? (
                  <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 text-xs">{formatDuration(p.duration)}</span>
                ) : null}
              </Link>
              <div className="flex items-start gap-2 p-3">
                <div className="min-w-0 flex-1">
                  <Link href={`/projects/${p.id}`} className="block truncate font-medium hover:underline">
                    {p.name}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {new Date(p.created_at).toLocaleDateString("cs-CZ")} · {t.dashboard.clips(p.clip_count)}
                  </p>
                  {(p.status === "processing" || p.status === "queued") && (
                    <Progress value={p.progress} className="mt-2 h-1" />
                  )}
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label="Akce">
                      <MoreVertical />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onSelect={() => {
                        setName(p.name)
                        setRenaming(p)
                      }}
                    >
                      <Pencil /> {t.dashboard.rename}
                    </DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(p)}>
                      <Trash2 /> {t.dashboard.delete}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.dashboard.renameTitle}</DialogTitle>
          </DialogHeader>
          <Input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && rename()} autoFocus />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenaming(null)}>
              {t.dashboard.cancel}
            </Button>
            <Button onClick={rename} disabled={!name.trim()}>
              {t.dashboard.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{deleting?.name}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t.dashboard.deleteConfirm}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              {t.dashboard.cancel}
            </Button>
            <Button variant="destructive" onClick={remove}>
              <Trash2 /> {t.dashboard.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
