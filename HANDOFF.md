# HANDOFF — Agent Local (BASWE Project 15)

_Last updated: 2026-06-07 (Phase 3 — Next.js UI)._
_Read `CLAUDE.md` first for architecture/config/commands._

---

## Session close — 2026-06-07 (Phase 3 — Next.js UI premium)

**Resumed green (81 tests), built Phase 3 frontend from scratch.**
Backend (Python) untouched — no Python file changed.

**Health at close:**
- Python: `ruff check .` ✅ · `pytest -v` → **81 passed** (unchanged)
- Frontend: `npx tsc --noEmit` ✅ · `npm run lint` ✅ (0 warnings) · `npm run build` ✅
  - 4 routes: `/` (redirect) · `/runs` (static) · `/runs/[id]` (dynamic) · `/_not-found`
  - First Load JS: 101 kB shared, 14.5 kB per page

---

## Phase 3 deliverables

### Stack frontend (`frontend/`)
Next.js 15.3.3 (App Router, Turbopack) · TypeScript strict · Tailwind v4 ·
shadcn new-york (zinc + CSS vars) · next-themes · sonner toasts · lucide-react

### shadcn components installed (via MCP `get_add_command_for_items`)
button · card · badge · dialog · table · tabs · skeleton · sonner · tooltip · input ·
textarea · separator · scroll-area · spinner

### Pages

| Route | Fichier | Description |
|---|---|---|
| `/` | `app/page.tsx` | Redirect → `/runs` |
| `/runs` | `app/runs/page.tsx` | Liste searchable, dialog New Run, refresh |
| `/runs/[id]` | `app/runs/[id]/page.tsx` | Détail run : header + tabs (Résultat/Trace/Plan) + SSE live |

### Composants (`src/components/`)

| Fichier | Rôle |
|---|---|
| `header.tsx` | Sticky nav + health badge (poll /health 30s) + theme toggle |
| `theme-provider.tsx` | Wrapper next-themes |
| `theme-toggle.tsx` | Bouton sun/moon avec tooltip |
| `status-badge.tsx` | Badge coloré par statut (running/completed/approval_required/failed) |
| `offline-banner.tsx` | Bannière rouge quand l'API est hors ligne |
| `new-run-dialog.tsx` | Dialog "Nouvelle tâche" avec chips suggestions + ⌘↵ |
| `span-tree.tsx` | Arbre spans parent/child cliquable (expand → payload JSON + copy) |
| `approve-panel.tsx` | Panneau approbation (accept/reject + note) → toast + reload |
| `tool-result-card.tsx` | Card outil : output code block + copy button + badge OK/Erreur |

### API client TS (`src/lib/api.ts`)
Typage complet des 6 routes. `ApiError` pour gestion d'erreurs. Timeout configurable.
`NEXT_PUBLIC_API_URL=http://localhost:8100` via `.env.local`.

### UX features
- **SSE live** : `/runs/[id]/stream` branché sur EventSource ; span tree se peuple en temps réel
- **Approval flow UI** : si `status=approval_required`, panneau `ApprovePanel` avec bouttons
  accept/reject → toast → reload automatique
- **Offline** : `OfflineBanner` + message d'erreur sur toutes les pages en cas d'API down
- **Skeletons** : loading state miroir de la mise en page résultat
- **Copy button** : code blocks pour outputs d'outils et payloads de spans
- **Search** : filtre client-side sur la liste des runs
- **Responsive** : layout max-w-6xl centré, wrapping des badges/métriques

---

## NEXT — Phase 4 (ne pas commencer avant validation Phase 3)

1. **Mémoire** — injecter les N derniers runs dans le prompt du planificateur.
   TraceStore déjà persisté en SQLite ; il suffit d'un `get_recent_runs()`.
2. **Multi-agent routing** — ajouter un nœud `route` avant `plan` qui dispatch
   vers un agent spécialisé (fiscal / math / fichiers).
3. **Eval & démo** — 18 questions labellisées (analogie avec 6-RAG eval) pour mesurer
   le taux de réponse correcte avec Ollama local vs cloud.
4. **Docker** — `frontend` service Next.js dans `docker-compose.yml` (dépend de l'API).

### Contraintes inchangées
- Tests JAMAIS avec un vrai Ollama.
- ruff + pytest verts sur le backend.
- Build Next.js doit passer avant tout arrêt.
- Ne PAS toucher au projet 6-RAG.

---

## Commandes de reprise

```powershell
# Backend (depuis 7-Agent-Local/)
uv run --no-sync pytest -q              # 81 passed
uv run --no-sync ruff check .           # All checks passed
$env:PYTHONPATH = "src"
uv run --no-sync uvicorn agent.api.main:app --port 8100 --reload

# Frontend (depuis 7-Agent-Local/frontend/)
npm run dev        # → http://localhost:3000
npm run build      # vérification build production
npm run lint       # 0 warnings
```

## Captures attendues (portfolio)

1. **Page /runs, light** : table avec 3-4 runs, badges colorés, bouton "Nouveau run"
2. **Dialog New Run, dark** : textarea + chips suggestion + ⌘↵
3. **Page détail, onglet Résultat** : réponse texte + tool result card (output RAG fiscal)
4. **Page détail, onglet Trace, dark** : arbre de spans déployé (intake→plan→tool:rag_fiscal→write→review)
5. **Approval panel** : panneau amber avec badge HIGH-risk + boutons approve/reject
6. **Bannière offline** : rouge, avec commande uvicorn
