"use client"

import { useState } from "react"
import { ChevronRightIcon, ClockIcon, TerminalIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { TraceSpan } from "@/lib/api"

interface SpanNode extends TraceSpan {
  children: SpanNode[]
  depth: number
}

function buildTree(spans: TraceSpan[]): SpanNode[] {
  const byId = new Map<string, SpanNode>(
    spans.map((s) => ({ ...s, children: [], depth: 0 })).map((s) => [s.id, s]),
  )
  const roots: SpanNode[] = []
  for (const node of byId.values()) {
    if (node.parent_id && byId.has(node.parent_id)) {
      byId.get(node.parent_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  }
  function setDepth(node: SpanNode, d: number) {
    node.depth = d
    node.children.forEach((c) => setDepth(c, d + 1))
  }
  roots.forEach((r) => setDepth(r, 0))
  return roots
}

function spanColor(name: string, ended: boolean | null | undefined) {
  if (!ended) return "text-blue-500 animate-pulse"
  if (name.startsWith("tool:")) return "text-violet-500"
  if (name === "intake") return "text-emerald-500"
  if (name === "plan") return "text-amber-500"
  if (name === "research") return "text-orange-500"
  if (name === "write") return "text-sky-500"
  if (name === "review") return "text-pink-500"
  return "text-muted-foreground"
}

function SpanRow({ node }: { node: SpanNode }) {
  const [open, setOpen] = useState(false)
  const hasData = Object.keys(node.data ?? {}).length > 0
  const dataStr = hasData ? JSON.stringify(node.data, null, 2) : null

  return (
    <>
      <div
        className={cn(
          "flex items-start gap-2 rounded py-1.5 px-2 hover:bg-muted/30 text-sm",
          node.children.length > 0 || hasData ? "cursor-pointer" : "",
        )}
        style={{ paddingLeft: `${node.depth * 20 + 8}px` }}
        onClick={() => (hasData || node.children.length > 0) && setOpen((p) => !p)}
      >
        {node.children.length > 0 || hasData ? (
          <ChevronRightIcon
            className={cn("mt-0.5 size-3.5 shrink-0 transition-transform text-muted-foreground", open && "rotate-90")}
          />
        ) : (
          <span className="mt-0.5 size-3.5 shrink-0" />
        )}

        {/* Icon */}
        <TerminalIcon className={cn("mt-0.5 size-3.5 shrink-0", spanColor(node.name, !!node.ended_at))} />

        {/* Name */}
        <span className="font-mono font-medium flex-1 truncate">{node.name}</span>

        {/* Duration */}
        {node.duration_ms != null && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground shrink-0">
            <ClockIcon className="size-3" />
            {node.duration_ms}ms
          </span>
        )}

        {!node.ended_at && (
          <Badge variant="outline" className="border-blue-400 text-blue-500 text-xs animate-pulse shrink-0">
            running
          </Badge>
        )}
      </div>

      {/* Data payload */}
      {open && dataStr && (
        <div
          className="mx-2 mb-1 overflow-x-auto rounded border bg-muted/40 p-3 text-xs font-mono"
          style={{ marginLeft: `${node.depth * 20 + 28}px` }}
        >
          <CopyBlock code={dataStr} />
        </div>
      )}

      {/* Children */}
      {open && node.children.map((c) => <SpanRow key={c.id} node={c} />)}
    </>
  )
}

function CopyBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative group">
      <pre className="whitespace-pre-wrap break-words">{code}</pre>
      <button
        onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
        className="absolute right-1 top-1 hidden rounded border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground group-hover:block"
      >
        {copied ? "✓" : "Copy"}
      </button>
    </div>
  )
}

export function SpanTree({ spans }: { spans: TraceSpan[] }) {
  if (!spans.length) {
    return <p className="text-sm text-muted-foreground">Aucun span enregistré.</p>
  }
  const roots = buildTree(spans)
  return (
    <ScrollArea className="max-h-[500px]">
      <div className="min-w-0 space-y-px">
        {roots.map((r) => <SpanRow key={r.id} node={r} />)}
      </div>
    </ScrollArea>
  )
}
