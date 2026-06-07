"use client"

import { useEffect, useState, useCallback } from "react"
import Link from "next/link"
import { RefreshCwIcon, SearchIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { StatusBadge } from "@/components/status-badge"
import { OfflineBanner } from "@/components/offline-banner"
import { NewRunDialog } from "@/components/new-run-dialog"
import { api, type RunSummary } from "@/lib/api"

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  })
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [apiOffline, setApiOffline] = useState(false)
  const [search, setSearch] = useState("")

  const load = useCallback(async () => {
    try {
      const data = await api.listRuns()
      setRuns(data)
      setApiOffline(false)
    } catch {
      setApiOffline(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = runs.filter(
    (r) =>
      r.question.toLowerCase().includes(search.toLowerCase()) ||
      r.id.includes(search) ||
      r.status.includes(search),
  )

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="text-sm text-muted-foreground">
            {runs.length} run{runs.length !== 1 ? "s" : ""} enregistrés
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={load} title="Rafraîchir">
            <RefreshCwIcon className="size-4" />
          </Button>
          <NewRunDialog onCreated={load} />
        </div>
      </div>

      {apiOffline && <OfflineBanner />}

      {/* Search */}
      <div className="relative max-w-sm">
        <SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Filtrer par question, ID, statut…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Table */}
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-32">Run ID</TableHead>
              <TableHead>Question</TableHead>
              <TableHead className="w-40">Statut</TableHead>
              <TableHead className="w-36">Date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 4 }).map((__, j) => (
                    <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                  ))}
                </TableRow>
              ))
            ) : filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                  {search ? "Aucun run correspondant." : "Aucun run — lancez votre première tâche !"}
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((run) => (
                <TableRow key={run.id} className="cursor-pointer hover:bg-muted/40">
                  <TableCell className="font-mono text-xs">
                    <Link href={`/runs/${run.id}`} className="hover:underline">
                      {run.id.slice(0, 8)}…
                    </Link>
                  </TableCell>
                  <TableCell className="max-w-xs">
                    <Link
                      href={`/runs/${run.id}`}
                      className="block truncate text-sm hover:underline"
                      title={run.question}
                    >
                      {run.question}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={run.status} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {formatDate(run.created_at)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
