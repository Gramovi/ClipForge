import { Badge } from "@/components/ui/badge"
import { t } from "@/lib/i18n"
import { cn } from "@/lib/utils"

const COLORS: Record<string, string> = {
  queued: "bg-zinc-700 text-zinc-100",
  processing: "bg-amber-500/90 text-black",
  done: "bg-emerald-500/90 text-black",
  failed: "bg-red-500/90 text-white",
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge className={cn("border-0", COLORS[status] ?? COLORS.queued)}>
      {(t.status as Record<string, string>)[status] ?? status}
    </Badge>
  )
}

export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  const color = score >= 80 ? "bg-emerald-500 text-black" : score >= 60 ? "bg-amber-400 text-black" : "bg-zinc-600 text-white"
  return (
    <span className={cn("inline-flex h-7 min-w-9 items-center justify-center rounded-md px-1.5 text-sm font-bold tabular-nums", color, className)}>
      {Math.round(score)}
    </span>
  )
}
