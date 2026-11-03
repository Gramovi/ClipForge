import type { Metadata, Viewport } from "next"
import { GeistMono } from "geist/font/mono"
import { GeistSans } from "geist/font/sans"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { t } from "@/lib/i18n"

import "./globals.css"

export const metadata: Metadata = {
  title: `${t.app.name} – AI klipy z dlouhých videí`,
  description: t.app.tagline,
}

export const viewport: Viewport = { themeColor: "#14151c", width: "device-width", initialScale: 1 }

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="cs" className={`dark ${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="bg-forge min-h-dvh font-sans antialiased">
        <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
        <Toaster richColors position="top-center" />
      </body>
    </html>
  )
}
