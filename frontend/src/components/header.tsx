"use client"

import { BotIcon, CircleIcon } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ThemeToggle } from "./theme-toggle"
import { useHealth } from "@/hooks/use-health"

export function Header() {
  const { health, offline } = useHealth()

  const ollamaOk = !offline && health?.ollama === "online"
  const apiOk = !offline && health?.status === "ok"

  return (
    <header className="sticky top-0 z-50 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
        {/* Brand */}
        <Link href="/runs" className="flex items-center gap-2 font-semibold">
          <BotIcon className="size-5 text-[var(--brand)]" />
          <span className="bg-gradient-to-r from-[var(--brand)] to-[var(--brand-2)] bg-clip-text text-transparent">
            Agent Local
          </span>
        </Link>

        {/* Nav */}
        <nav className="flex items-center gap-1 text-sm text-muted-foreground">
          <Link
            href="/runs"
            className="rounded px-2 py-1 hover:text-foreground transition-colors"
          >
            Runs
          </Link>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {/* Health badge */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge
                variant="outline"
                className="flex cursor-default items-center gap-1.5 text-xs"
              >
                <CircleIcon
                  className={`size-2 fill-current ${
                    offline
                      ? "text-destructive animate-pulse"
                      : apiOk
                        ? "text-emerald-500 animate-pulse"
                        : "text-amber-400"
                  }`}
                />
                {offline ? "API offline" : apiOk ? "API online" : "..."}
              </Badge>
            </TooltipTrigger>
            <TooltipContent className="text-xs">
              {offline ? (
                "Backend FastAPI non joignable"
              ) : (
                <div className="space-y-1">
                  <p>API: {health?.api} v{health?.version}</p>
                  <p>Ollama: {ollamaOk ? "🟢 online" : "🔴 offline"}</p>
                </div>
              )}
            </TooltipContent>
          </Tooltip>

          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
