import { cn } from "@/lib/utils"

/** ClipForge wordmark: an anvil-spark glyph made of two stacked play-chevrons. */
export function Logo({ size = "md", className }: { size?: "md" | "lg"; className?: string }) {
  const s = size === "lg" ? 36 : 26
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", size === "lg" ? "text-2xl" : "text-lg", className)}>
      <svg width={s} height={s} viewBox="0 0 32 32" aria-hidden>
        <defs>
          <linearGradient id="cf-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#FFB547" />
            <stop offset="1" stopColor="#FF4D6D" />
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="28" height="28" rx="8" fill="url(#cf-g)" />
        <path d="M11 9.5 L21.5 16 L11 22.5 Z" fill="#17131f" />
        <path d="M17.5 7 L19 10.5 L22.5 12 L19 13.5 L17.5 17 L16 13.5 L12.5 12 L16 10.5 Z" fill="#fff" opacity=".9" transform="translate(5 -3) scale(.6)" />
      </svg>
      <span>
        Clip<span className="text-primary">Forge</span>
      </span>
    </span>
  )
}
