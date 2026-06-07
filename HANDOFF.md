# HANDOFF — Agent Local (BASWE Project 15)

_Last updated: 2026-06-07 (Phase 2 — FastAPI API + approval flow)._
_Read `CLAUDE.md` first for architecture/config/commands._

---

## Session close — 2026-06-07 (Phase 2 — FastAPI API)

**Resumed green (59 tests), built Phase 2 from scratch.**
Did NOT touch Phase 1 code except two minimal, non-breaking additions:
- `graph.py`: added `approved: bool` to `GraphState` + `_initial_state`; `_research` now
  skips blocking HIGH-risk tools when `approved=True`; `run_task()` accepts `approved=`.
- `trace.py`: added `set_run_status`, `get_run_status`, `get_run_task`, enriched `list_runs`
  (now returns `question` from stored task). All 59 Phase 1 tests still pass unchanged.

**Health at close:**
- `ruff check .` → **All checks passed!**
- `pytest -v` → **81 passed**, 0 failed, 43.8 s
- 0 Ollama calls in any test — all via `force_fallback=True` or `_HighRiskLLM` mock.

---

## Phase 2 deliverables

### FastAPI app (`src/agent/api/`)

| File | Role |
|---|---|
| `schemas.py` | API DTOs: RunRequest · RunCreateResponse · RunSummary · RunDetail · ApproveRequest · ApproveResponse · HealthResponse |
| `deps.py` | Lazy singletons `get_llm / get_registry / get_trace`; `reset_deps()` for tests |
| `runner.py` | `execute_run_sync` (LangGraph in thread) + `execute_run` (async BackgroundTasks wrapper) |
| `main.py` | FastAPI app on :8100, CORS, MCP (`FastApiMCP.mount_http()` at `/mcp`), 6 routes |

### Routes

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{status, api, ollama: online\|offline, version}` |
| POST | `/run` | Submit task → `{run_id, status}` (background exec) |
| GET | `/runs` | List all runs (most recent first) |
| GET | `/runs/{id}` | Full detail: task + status + plan + result + review + approval + spans |
| POST | `/runs/{id}/approve` | `{decision: accept\|reject\|modify, note?}` |
| GET | `/runs/{id}/stream` | SSE — emits spans as they're written + `{event:done,status}` |

### Approval flow
1. `POST /run` → graph encounters HIGH-risk tool → `approval_required` status
2. `GET /runs/{id}` shows `approval` object with `high_risk_tools` list
3. `POST /runs/{id}/approve {decision: accept}` → re-runs graph with `approved=True`
   → HIGH-risk tools execute → status becomes `completed`
4. `POST /runs/{id}/approve {decision: reject}` → status becomes `failed`

### MCP
`FastApiMCP` mounts at `/mcp` (HTTP transport). All API routes are exposed as MCP tools.
Connect any MCP client to `http://localhost:8100/mcp`.

---

## Tests (81, 0 Ollama calls)

| Catégorie | Fichier | Tests |
|---|---|---|
| Schémas | `test_schemas.py` | 12 |
| Permissions + logging | `test_tools.py` | 19 |
| TraceStore spans | `test_trace.py` | 13 |
| Fallback déterministe | `test_llm.py` | 9 |
| Approval trigger + graph | `test_graph.py` | 9 |
| **API routes (Phase 2)** | **`test_api.py`** | **22** |

---

## NEXT — Phase 3 (ne pas commencer avant validation Phase 2)

1. **Next.js UI** — brancher le scaffold existant (`frontend/`) sur l'API :8100 :
   - Page **Runs** (`/runs`) : tableau des runs avec status badge, lien vers le détail
   - Page **Run detail** (`/runs/[id]`) : timeline des spans, réponse, bouton Approve
   - Page **New run** (`/`) : textarea + chip suggestions + ⌘↵, SSE live progress bar
   - API client TS : miroir des schémas `RunSummary` / `RunDetail` / `ApproveRequest`
2. **Multi-agent routing** — ajouter un nœud `route` avant `plan` qui dispatch vers
   un agent spécialisé (fiscal / math / fichiers) selon la question.
3. **Mémoire** — injecter l'historique des runs précédents dans le prompt du planificateur.

### Contraintes inchangées
- Tests JAMAIS avec un vrai Ollama.
- Calculator sans `eval()`.
- HIGH-risk tools jamais exécutés sans approval.
- ruff + pytest verts avant de s'arrêter.
- Ne PAS toucher au projet 6-RAG.
- Ne PAS changer l'API (`/run`, `/runs`, etc.) sans ajouter des tests.

---

## Commandes de reprise

```powershell
cd "C:\...\Projets_perso\7-Agent-Local"

# Santé
uv run --no-sync ruff check .
uv run --no-sync pytest -v     # 81 passed attendus

# Démarrer l'API (port 8100 — RAG fiscal occupe :8000)
$env:PYTHONPATH="src"
uv run --no-sync uvicorn agent.api.main:app --port 8100 --reload

# Tester l'API manuellement
curl http://localhost:8100/health
curl -X POST http://localhost:8100/run -H "Content-Type: application/json" `
     -d '{"question":"Quel est le barème de l'\''impôt sur le revenu ?"}'

# CLI offline (toujours dispo)
$env:FORCE_FALLBACK="true"
uv run --no-sync agent run "test question"
uv run --no-sync agent runs list
```
