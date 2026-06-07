"use client"

import { use, useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import {
  ArrowLeftIcon,
  ClockIcon,
  WrenchIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { StatusBadge } from "@/components/status-badge"
import { SpanTree } from "@/components/span-tree"
import { ApprovePanel } from "@/components/approve-panel"
import { ToolResultCard } from "@/components/tool-result-card"
import { OfflineBanner } from "@/components/offline-banner"
import { api, type RunDetail, type TraceSpan } from "@/lib/api"

// ── Props ─────────────────────────────────────────────────────────────────────

interface PageProps {
  params: Promise<{ id: string }>
}

// ── Live SSE hook ─────────────────────────────────────────────────────────────

function useLiveSpans(
  runId: string,
  isRunning: boolean,
  onDone: () => void,
) {
  const [liveSpans, setLiveSpans] = useState<TraceSpan[]>([])
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!isRunning) return
    const es = api.streamRun(runId)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data as string) as Record<string, unknown>
        if (data.event === "done") {
          onDone()
          es.close()
          return
        }
        // It's a span
        setLiveSpans((prev) => {
          const existing = prev.find((s) => s.id === data.id)
          if (existing) return prev.map((s) => (s.id === data.id ? (data as unknown as TraceSpan) : s))
          return [...prev, data as unknown as TraceSpan]
        })
      } catch {}
    }

    es.onerror = () => { es.close(); onDone() }
    return () => { es.close() }
  }, [runId, isRunning, onDone])

  return liveSpans
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RunDetailPage({ params }: PageProps) {
  const { id } = use(params)
  const [run, setRun] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [apiOffline, setApiOffline] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api.getRun(id)
      setRun(data)
      setApiOffline(false)
    } catch {
      setApiOffline(true)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const isRunning = run?.status === "running"
  const liveSpans = useLiveSpans(id, isRunning, load)

  const allSpans = [...(run?.spans ?? []), ...liveSpans.filter((ls) => !run?.spans.some((s) => s.id === ls.id))]

  // ── Skeleton ──────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-6 w-64" />
        </div>
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (apiOffline) {
    return (
      <div className="space-y-4">
        <Link href="/runs">
          <Button variant="ghost" size="sm"><ArrowLeftIcon className="mr-2 size-4" />Retour</Button>
        </Link>
        <OfflineBanner />
      </div>
    )
  }

  if (!run) {
    return (
      <div className="space-y-4">
        <Link href="/runs">
          <Button variant="ghost" size="sm"><ArrowLeftIcon className="mr-2 size-4" />Retour</Button>
        </Link>
        <p className="text-muted-foreground">Run introuvable : {id}</p>
      </div>
    )
  }

  const toolCallCount = allSpans.filter((s) => s.name.startsWith("tool:")).length
  const totalMs = allSpans.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0)

  return (
    <div className="space-y-6">
      {/* ── Breadcrumb ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/runs" className="hover:text-foreground transition-colors">Runs</Link>
        <span>/</span>
        <span className="font-mono">{run.id.slice(0, 8)}…</span>
      </div>

      {/* ── Header card ───────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-4">
            <CardTitle className="text-lg leading-snug">
              {run.task.question}
            </CardTitle>
            <StatusBadge status={run.status} className="shrink-0" />
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="font-mono text-foreground/60">ID</span>
              <span className="font-mono">{run.id}</span>
            </span>
            {totalMs > 0 && (
              <span className="flex items-center gap-1">
                <ClockIcon className="size-3" />
                {totalMs}ms total
              </span>
            )}
            {toolCallCount > 0 && (
              <span className="flex items-center gap-1">
                <WrenchIcon className="size-3" />
                {toolCallCount} tool call{toolCallCount !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── Approval panel ────────────────────────────────────────────── */}
      {run.status === "approval_required" && run.approval && (
        <ApprovePanel runId={run.id} approval={run.approval} onDone={load} />
      )}

      {/* ── Main tabs ─────────────────────────────────────────────────── */}
      <Tabs defaultValue="result">
        <TabsList>
          <TabsTrigger value="result">Résultat</TabsTrigger>
          <TabsTrigger value="trace">
            Trace
            {allSpans.length > 0 && (
              <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-mono">
                {allSpans.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="plan">Plan</TabsTrigger>
        </TabsList>

        {/* Result tab */}
        <TabsContent value="result" className="mt-4 space-y-4">
          {isRunning && !run.result ? (
            <div className="space-y-3">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : run.result ? (
            <>
              {/* Answer */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Réponse
                    {run.review && (
                      <span className="ml-2 text-xs">
                        — verdict:{" "}
                        <span className={
                          run.review.verdict === "approved"
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-amber-600 dark:text-amber-400"
                        }>
                          {run.review.verdict}
                        </span>
                      </span>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{run.result.answer}</p>
                </CardContent>
              </Card>

              {/* Tool results */}
              {(run.result.tool_results?.length ?? 0) > 0 && (
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-muted-foreground">Résultats d&apos;outils</h3>
                  {run.result.tool_results!.map((tr, i) => (
                    <ToolResultCard key={i} result={tr} />
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {run.status === "approval_required"
                ? "Approbation requise avant l'exécution des outils à risque élevé."
                : "Aucun résultat disponible."}
            </p>
          )}
        </TabsContent>

        {/* Trace tab */}
        <TabsContent value="trace" className="mt-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Arbre de spans
                {isRunning && (
                  <span className="ml-2 text-xs text-blue-500 animate-pulse">● live</span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <SpanTree spans={allSpans} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Plan tab */}
        <TabsContent value="plan" className="mt-4">
          {run.plan ? (
            <div className="space-y-3">
              {run.plan.reasoning && (
                <p className="text-xs text-muted-foreground italic">{run.plan.reasoning}</p>
              )}
              {run.plan.subtasks.map((st, i) => (
                <Card key={st.id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">
                      <span className="text-muted-foreground mr-2">#{i + 1}</span>
                      {st.description}
                    </CardTitle>
                  </CardHeader>
                  {st.tool_calls.length > 0 && (
                    <CardContent>
                      <Separator className="mb-3" />
                      <div className="space-y-1">
                        {st.tool_calls.map((tc, j) => (
                          <div key={j} className="flex items-center gap-2 text-xs font-mono">
                            <WrenchIcon className="size-3 text-violet-500 shrink-0" />
                            <span className="font-medium">{tc.tool_name}</span>
                            {tc.arguments && Object.keys(tc.arguments).length > 0 && (
                              <span className="text-muted-foreground truncate">
                                {JSON.stringify(tc.arguments).slice(0, 80)}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  )}
                </Card>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {isRunning ? "Planification en cours…" : "Aucun plan disponible."}
            </p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
