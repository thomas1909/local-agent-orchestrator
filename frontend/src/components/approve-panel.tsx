"use client"

import { useState, useTransition } from "react"
import { AlertTriangleIcon } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Spinner } from "@/components/ui/spinner"
import { api, type ApprovalRequest } from "@/lib/api"

interface ApprovePanelProps {
  runId: string
  approval: ApprovalRequest
  onDone: () => void
}

export function ApprovePanel({ runId, approval, onDone }: ApprovePanelProps) {
  const [note, setNote] = useState("")
  const [isPending, startTransition] = useTransition()

  function decide(decision: "accept" | "reject") {
    startTransition(async () => {
      try {
        const res = await api.approveRun(runId, decision, note)
        toast.success(
          decision === "accept" ? "Run approuvé" : "Run rejeté",
          { description: res.message },
        )
        onDone()
      } catch (err) {
        toast.error("Erreur lors de l'approbation", { description: String(err) })
      }
    })
  }

  return (
    <div className="rounded-lg border border-amber-400/40 bg-amber-50/30 dark:bg-amber-900/10 p-4 space-y-4">
      <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
        <AlertTriangleIcon className="size-5 shrink-0" />
        <span className="font-semibold">Approbation requise</span>
      </div>

      <p className="text-sm text-muted-foreground">{approval.reason}</p>

      <div className="flex flex-wrap gap-2">
        <span className="text-xs text-muted-foreground self-center">Outils à risque élevé :</span>
        {approval.high_risk_tools.map((t) => (
          <Badge key={t} variant="outline" className="border-amber-400 text-amber-600 dark:text-amber-400 font-mono text-xs">
            {t}
          </Badge>
        ))}
      </div>

      <Separator />

      <Textarea
        placeholder="Note optionnelle (motif d'approbation, modification…)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        className="resize-none text-sm"
      />

      <div className="flex gap-2">
        <Button
          variant="default"
          className="bg-emerald-600 hover:bg-emerald-700 text-white"
          onClick={() => decide("accept")}
          disabled={isPending}
        >
          {isPending ? <Spinner className="mr-2 size-4" /> : null}
          Approuver
        </Button>
        <Button
          variant="outline"
          className="border-destructive text-destructive hover:bg-destructive/10"
          onClick={() => decide("reject")}
          disabled={isPending}
        >
          Rejeter
        </Button>
      </div>
    </div>
  )
}
