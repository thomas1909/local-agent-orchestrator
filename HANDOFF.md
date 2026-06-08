# HANDOFF — Agent Local (BASWE Project 15)

_Last updated: 2026-06-08 (Phase 6 — DONE: screenshots captured + 3 bug fixes)._
_Read `CLAUDE.md` first for architecture/config/commands._

---

## Session close — 2026-06-08 (Phase 6 DONE — screenshots + fixes)

**Phase 6 is now complete.** The 12 portfolio screenshots are captured and the
gallery in `README.md` renders. Along the way, three real issues that blocked
recruiter-ready screens were fixed.

**Health at close:**
- `ruff check .` ✅ · `pytest -q` → **87 passed** (was 81, +6)
- `eval/run_eval.py` → **10/10 passed (100 %)**, fully offline
- Frontend now renders **styled** (Tailwind v4 was previously generating no CSS)

**Shipped this session:**
1. **HIGH-risk demo tool** `delete_file` (sandbox) added to the live registry +
   a **keyword-aware offline planner** (math→`calculator`, destructive verb→`delete_file`,
   else→`rag_fiscal`). Makes the human-in-the-loop gate demonstrable in the running app.
2. **Bug fix — TraceStore never persisted `plan`/`result`/`review`.** The graph built
   them in memory but only spans were saved, so the API's `RunDetail` always returned
   `result=null` → the UI Result & Plan tabs were empty in real use. Added 3 JSON columns
   (`plan_json`/`result_json`/`review_json`) + `save_plan/result/review` + export wiring
   (with a PRAGMA migration for older DBs).
3. **Bug fix — frontend had no PostCSS config.** Tailwind v4 (`@import "tailwindcss"`)
   generated zero utilities → unstyled UI. Added `frontend/postcss.config.mjs` +
   `@tailwindcss/postcss` devDep.

**Screenshot pipeline:** this machine has **no npm/PyPI egress**, so Playwright can't be
installed. Captures are produced by `frontend/scripts/capture.mjs` — a zero-dependency
Chrome DevTools Protocol driver using Node's built-in WebSocket and the Chromium already
cached under `ms-playwright`. Re-run: seed runs against an API in `FORCE_FALLBACK=true`
mode (`TRACE_DB_PATH=data/screenshots.db`), write `frontend/.capture-runs.json`, then
`CAPTURE_MODE=online|offline node scripts/capture.mjs`.

**Reproducibility caveat:** `package-lock.json` was NOT updated (no network here). On a
machine with internet, run `npm install` once from `frontend/` to pin `@tailwindcss/postcss`.

---

## Session close — 2026-06-07 (Phase 6 — portfolio)

**Resumed green (81 tests), added the portfolio layer. No product code changed**
(only a new `eval/` harness + docs). Backend and frontend untouched.

**Health at close:**
- `ruff check .` ✅ · `pytest -q` → **81 passed** (unchanged)
- `eval/run_eval.py` → **10/10 passed (100 %)**, fully offline
- Frontend unchanged since Phase 3 (last build green: 4 routes)

---

## Phase 6 deliverables

### Offline eval (`eval/`)
| File | Role |
|---|---|
| `golden_set.json` | 10 tasks, each with a scripted plan + expectations (status, answer_contains, tool_calls, escalation) |
| `run_eval.py` | Runs the real LangGraph pipeline with a deterministic `ScriptedPlanner` (zero Ollama). Measures success / tool calls / latency / escalations. Writes `report.json` + `report.md`. Bypasses corporate proxy for localhost so the offline-RAG path fails fast. |
| `fixtures/notes.txt` | Seed file for the `read_file` / `search_text` / `list_files` tasks |
| `report.json` / `report.md` | Generated report (committed as a portfolio artifact) |

**Coverage:** calculator numeric correctness (3), file tools (3), offline-safe RAG (1),
multi-step plan (1), HIGH-risk escalation (1), post-approval execution (1).
**Result:** 10/10, 10 tool calls, 1 escalation, orchestration overhead median 0 ms.

**Key design choice:** the eval uses a `ScriptedPlanner` (fixed `ExecutionPlan` per task,
delegates AgentResult/ReviewResult to the deterministic fallback) so it measures
*orchestration* — tool routing, numeric results, HIGH-risk escalation, approved re-run —
independently of LLM quality, and runs with no quota.

### Portfolio docs
| File | Role |
|---|---|
| `README.md` | Portfolio-ready (English): what-it-is, Mermaid architecture, why-it-matters, quickstart, eval numbers, screenshot gallery, link to the 6-RAG project |
| `docs/CASE_STUDY.md` | Problem → architecture → the deterministic offline-fallback decision → eval numbers → next steps |
| `docs/DEMO_SCRIPT.md` | Timed < 3-min demo (pitch → launch → plan/tools/trace → approval flow → tests+eval) |
| `docs/screenshots/` | Placeholder + naming guide for the 6 light/dark captures |

---

## NEXT — Phase 4 (deferred) + capture

1. **Take the 6 screenshots** (light + dark) per `docs/screenshots/README.md` and
   the README gallery — the only remaining manual step for a recruiter-ready repo.
   Pre-seed runs: one completed, one `approval_required`, optionally one `failed`.
2. **Record the < 3-min demo** following `docs/DEMO_SCRIPT.md`.
3. **Memory** — `get_recent_runs()` on TraceStore → inject last N runs into the planner prompt.
4. **Multi-agent routing** — a `route` node before `plan` dispatching to a specialist.
5. **Answer-quality eval** — a model-on eval scoring correctness vs labelled references.

### Contraintes inchangées
- Tests JAMAIS avec un vrai Ollama (eval inclus: `ScriptedPlanner` + fallback).
- ruff + pytest verts sur le backend; build Next.js vert.
- Ne PAS toucher au projet 6-RAG.

---

## Commandes de reprise

```powershell
# Backend (depuis 7-Agent-Local/)
uv run --no-sync pytest -q                       # 81 passed
uv run --no-sync ruff check .                    # clean
$env:FORCE_FALLBACK="true"
uv run --no-sync python eval/run_eval.py         # 10/10 → eval/report.{json,md}

$env:PYTHONPATH="src"
uv run --no-sync uvicorn agent.api.main:app --port 8100 --reload

# Frontend (depuis 7-Agent-Local/frontend/)
npm run dev        # → http://localhost:3000
```

## Captures attendues (placer dans `docs/screenshots/`)

1. `runs-{light,dark}.png` — liste des runs + badges + bouton "New run"
2. `new-run-{light,dark}.png` — dialog : textarea + chips + ⌘↵
3. `detail-result-{light,dark}.png` — onglet Résultat : réponse + tool output card
4. `detail-trace-{light,dark}.png` — onglet Trace : arbre de spans déployé
5. `approval-{light,dark}.png` — panneau amber HIGH-risk + accept/reject
6. `offline-{light,dark}.png` — bannière rouge (arrêter l'API pour capturer)
