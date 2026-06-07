import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const STATUS_MAP: Record<string, { label: string; className: string }> = {
  running:            { label: "En cours",         className: "border-blue-400 text-blue-600 dark:text-blue-400 animate-pulse" },
  completed:          { label: "Terminé",           className: "border-emerald-400 text-emerald-600 dark:text-emerald-400" },
  approval_required:  { label: "Approbation req.", className: "border-amber-400 text-amber-600 dark:text-amber-400" },
  failed:             { label: "Échoué",            className: "border-destructive text-destructive" },
  pending:            { label: "En attente",        className: "border-muted-foreground text-muted-foreground" },
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const cfg = STATUS_MAP[status] ?? { label: status, className: "border-muted-foreground" }
  return (
    <Badge variant="outline" className={cn("font-mono text-xs", cfg.className, className)}>
      {cfg.label}
    </Badge>
  )
}
