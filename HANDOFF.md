# HANDOFF — Agent Local (BASWE Project 15)

_Last updated: 2026-06-07 (Phase 1 — foundations backend)._
_Read `CLAUDE.md` first for architecture/config/commands._

## Session close — 2026-06-07 (Phase 1 — foundations)

**Nouveau projet créé from scratch dans `7-Agent-Local/`** (séparé de 6-RAG).
La session précédente avait échoué sur une erreur 429 Ollama avant toute écriture
sur disque — Phase 1 était à 0 % et a été construite entièrement dans cette session.

**Health at close:**
- `ruff check .` → **All checks passed!**
- `pytest -v` → **59 passed**, 0 failed, 7.63 s
- AUCUN test n'appelle un vrai modèle Ollama : tout passe via `force_fallback=True`
  ou des `_MockLLM` inline.

---

## Ce qui est fait (Phase 1 complète)

### Schémas Pydantic v2 (`src/agent/schemas.py`)
10 modèles : `TaskRequest` · `ToolCall` · `SubTask` · `ExecutionPlan` ·
`ToolResult` · `AgentResult` · `ReviewResult` · `ApprovalRequest` ·
`TraceSpan` · `RunRecord`. Plus `RiskLevel(StrEnum)` (LOW/MEDIUM/HIGH).

### Config (`src/agent/config.py`)
`AgentConfig` (pydantic-settings) : `OLLAMA_BASE_URL` · `OLLAMA_MODEL` ·
`RAG_API_URL` · `TRACE_DB_PATH` · `FORCE_FALLBACK`.

### ToolRegistry (`src/agent/tools/registry.py`)
Register / get_risk / has_tool / execute (capture inputs + outputs + latency_ms
dans `ToolResult`) / schema_for_llm. Decorator `@registry.tool(...)` aussi disponible.

### 5 outils safe (`src/agent/tools/builtins.py`)
| Outil | Risque | Description |
|---|---|---|
| `list_files` | LOW | Lister fichiers/dossiers |
| `read_file` | LOW | Lire un fichier texte |
| `search_text` | LOW | Chercher un motif textuel (sans grep shell) |
| `calculator` | LOW | Calcul arithmétique **sans eval()** — AST seulement |
| `rag_fiscal` | MEDIUM | POST `/query` sur l'API 6-RAG (:8000) ; message FR si offline |

`build_default_registry(rag_api_url=...)` crée le registry prêt à l'emploi.

### TraceStore SQLite (`src/agent/trace.py`)
- Tables `runs` + `spans` (SQLite, `:memory:` pour les tests).
- `new_run` / `finish_run` / `save_approval` / `approve_run` / `list_runs`.
- `start_span` / `end_span` (parent_id pour la hiérarchie, duration_ms auto-calculé).
- `export_run_json(run_id)` → JSON complet (RunRecord).
- Context manager `trace.span(run_id, name)` disponible.

### OllamaClient (`src/agent/llm.py`)
- `instructor.from_ollama()` pour les structured outputs.
- `force_fallback=True` → bypass total d'Ollama (pour les tests).
- Détection auto de disponibilité via `/api/tags` (timeout 2s).
- Fallback déterministe par type de response_model :
  - `ExecutionPlan` → plan avec appel `rag_fiscal`
  - `AgentResult` → message `[Mode hors-ligne]`
  - `ReviewResult` → verdict `approved`

### LangGraph graph (`src/agent/graph.py`)
5 nœuds : **intake → plan → research → write → review → END**
- `intake` : démarre le trace span racine.
- `plan` : appelle OllamaClient (ou fallback) → `ExecutionPlan`.
- `research` : exécute les tool calls. **Les outils HIGH risk ne sont PAS
  exécutés** → met `approval_needed=True`.
- `write` : synthétise via LLM ou use directement les tool results en fallback.
- `review` : si `approval_needed` → verdict `approval_required` + crée
  `ApprovalRequest` + sauvegarde dans TraceStore.

`run_task(task, llm, registry, trace)` : wrapper de haut niveau.

### CLI Typer (`src/agent/cli.py`)
```
agent run <question>          # Lance un run complet
agent runs list               # Liste les runs passés (depuis SQLite)
agent runs show <run_id>      # Affiche le JSON complet du run
agent approve <run_id>        # Approuve un run en attente
```

### Frontend scaffold (`frontend/`)
Next.js 15 + TypeScript + Tailwind v4. Bare placeholder (page.tsx + layout.tsx).
**Pas d'UI complexe** — à construire en Phase 2.

---

## Tests (59, 0 Ollama call)

| Catégorie | Fichier | Tests |
|---|---|---|
| Schémas | `test_schemas.py` | 12 |
| Permissions + logging | `test_tools.py` | 19 |
| TraceStore spans | `test_trace.py` | 13 |
| Fallback déterministe | `test_llm.py` | 9 |
| Approval trigger HIGH risk | `test_graph.py` | 9 |

---

## NEXT — Phase 2 (ne pas commencer avant validation Phase 1)

1. **FastAPI wrapper** — exposer le graph via `POST /run` + `GET /runs` +
   `GET /runs/{id}` + `POST /runs/{id}/approve`. Réutiliser `TraceStore` +
   `run_task()` tels quels. Schémas OpenAPI dérivés des modèles Pydantic existants.
2. **Next.js UI** — page Question (textarea + chip suggestions), page Runs
   (list + detail avec timeline des spans), bouton Approve pour les runs en attente.
   API client TS miroir des schémas Python.
3. **Multi-agent routing** (Phase 3) — ajouter un nœud `route` avant `plan`
   pour sélectionner l'agent spécialisé (fiscal / recherche / calcul).

### Contraintes inchangées
- Tests JAMAIS avec un vrai Ollama.
- `calculator` sans `eval()`.
- HIGH risk tools jamais exécutés sans approval.
- ruff + pytest verts avant de s'arrêter.
- Ne PAS toucher au projet 6-RAG.

---

## Commandes de reprise

```bash
cd ".../Projets_perso/7-Agent-Local"

# Env (OneDrive → link-mode=copy)
uv sync --extra dev --link-mode=copy

# Vérification santé
uv run --no-sync ruff check .               # doit afficher: All checks passed!
uv run --no-sync pytest -v                  # doit afficher: 59 passed

# CLI offline (FORCE_FALLBACK évite tout quota)
$env:FORCE_FALLBACK="true"
uv run --no-sync agent run "Quel est le barème de l'IR ?"
uv run --no-sync agent runs list
uv run --no-sync agent runs show <run_id>

# CLI avec Ollama (si disponible)
uv run --no-sync agent run "Quel est le plafond du quotient familial ?"
```
