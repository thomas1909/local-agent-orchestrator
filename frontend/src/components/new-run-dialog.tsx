"use client"

import { useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { PlusIcon } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Spinner } from "@/components/ui/spinner"
import { api } from "@/lib/api"

const SUGGESTIONS = [
  "Quel est le plafond du quotient familial ?",
  "Explique le barème de l'impôt sur le revenu.",
  "Comment déclarer des revenus fonciers (case 2042) ?",
]

export function NewRunDialog({ onCreated }: { onCreated?: (id: string) => void }) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState("")
  const [isPending, startTransition] = useTransition()

  function handleSubmit() {
    if (!question.trim()) return
    startTransition(async () => {
      try {
        const { run_id } = await api.createRun(question.trim())
        toast.success("Run lancé", { description: `ID: ${run_id.slice(0, 8)}…` })
        setOpen(false)
        setQuestion("")
        onCreated?.(run_id)
        router.push(`/runs/${run_id}`)
      } catch (err) {
        toast.error("Erreur", { description: String(err) })
      }
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <PlusIcon className="size-4" />
          Nouveau run
        </Button>
      </DialogTrigger>

      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Nouvelle tâche</DialogTitle>
          <DialogDescription>
            Posez une question à l&apos;agent — il planifie, recherche et synthétise.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Textarea
            placeholder="Votre question…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={4}
            className="resize-none"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSubmit()
            }}
          />
          <p className="text-xs text-muted-foreground">⌘↵ pour soumettre</p>

          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setQuestion(s)}
                className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:border-[var(--brand)] hover:text-foreground transition-colors"
              >
                {s.length > 40 ? s.slice(0, 40) + "…" : s}
              </button>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={isPending}>
            Annuler
          </Button>
          <Button onClick={handleSubmit} disabled={!question.trim() || isPending}>
            {isPending ? <Spinner className="mr-2 size-4" /> : null}
            Lancer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
