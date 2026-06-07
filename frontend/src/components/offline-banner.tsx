"use client"

import { WifiOffIcon } from "lucide-react"

export function OfflineBanner() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      <WifiOffIcon className="size-4 shrink-0" />
      <span>
        <strong>Backend non joignable</strong> — démarrez l&apos;API avec&nbsp;:
        <code className="ml-1 rounded bg-destructive/10 px-1 font-mono text-xs">
          PYTHONPATH=src uv run uvicorn agent.api.main:app --port 8100
        </code>
      </span>
    </div>
  )
}
