"use client"

import { useState } from "react"
import { CheckIcon, CopyIcon, WrenchIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { ToolResult } from "@/lib/api"

export function ToolResultCard({ result }: { result: ToolResult }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(result.output)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="rounded-lg border bg-card text-card-foreground">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <WrenchIcon className="size-3.5 text-violet-500" />
        <span className="font-mono text-xs font-medium">{result.tool_name}</span>
        <span className="ml-auto text-xs text-muted-foreground">{result.latency_ms}ms</span>
        {result.error ? (
          <Badge variant="outline" className="border-destructive text-destructive text-xs">Erreur</Badge>
        ) : (
          <Badge variant="outline" className="border-emerald-400 text-emerald-600 dark:text-emerald-400 text-xs">OK</Badge>
        )}
      </div>

      <div className="relative group">
        <ScrollArea className="max-h-48">
          <pre className={cn(
            "p-3 text-xs font-mono whitespace-pre-wrap break-words",
            result.error && "text-destructive",
          )}>
            {result.error ?? result.output}
          </pre>
        </ScrollArea>
        <button
          onClick={copy}
          className="absolute right-2 top-2 hidden rounded border bg-background p-1 text-muted-foreground hover:text-foreground group-hover:flex items-center gap-1 text-[10px]"
        >
          {copied ? <CheckIcon className="size-3" /> : <CopyIcon className="size-3" />}
          {copied ? "Copié" : "Copy"}
        </button>
      </div>
    </div>
  )
}
