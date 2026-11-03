"use client"

import { useEffect, useState } from "react"

import { AppHeader } from "@/components/app-header"
import { api } from "@/lib/api"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [email, setEmail] = useState<string>()
  useEffect(() => {
    api<{ email: string }>("/api/auth/me").then((u) => setEmail(u.email)).catch(() => null)
  }, [])
  return (
    <div className="min-h-dvh">
      <AppHeader email={email} />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  )
}
