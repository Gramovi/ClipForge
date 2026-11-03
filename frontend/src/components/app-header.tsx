"use client"

import { FolderOpen, LogOut, Plus, Settings } from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"

import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "/", label: t.nav.projects, icon: FolderOpen },
  { href: "/settings", label: t.nav.settings, icon: Settings },
]

export function AppHeader({ email }: { email?: string }) {
  const pathname = usePathname()
  const router = useRouter()
  async function logout() {
    await api("/api/auth/logout", { method: "POST" }).catch(() => null)
    router.replace("/login")
    router.refresh()
  }
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4">
        <Link href="/" className="mr-2 shrink-0">
          <Logo />
        </Link>
        <nav className="flex items-center gap-1">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground",
                (n.href === "/" ? pathname === "/" || pathname.startsWith("/projects") : pathname.startsWith(n.href)) &&
                  "bg-muted text-foreground",
              )}
            >
              <n.icon className="size-4" />
              <span className="hidden sm:inline">{n.label}</span>
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Button asChild size="sm" data-testid="nav-new">
            <Link href="/new">
              <Plus /> <span className="hidden sm:inline">{t.nav.newProject}</span>
            </Link>
          </Button>
          {email && <span className="hidden max-w-40 truncate text-xs text-muted-foreground md:inline">{email}</span>}
          <Button variant="ghost" size="icon-sm" onClick={logout} title={t.nav.logout} aria-label={t.nav.logout}>
            <LogOut />
          </Button>
        </div>
      </div>
    </header>
  )
}
