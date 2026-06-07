# CLAUDE.md — Agent Local (BASWE Project 15)

## Goal
Local agent orchestrator: LangGraph pipeline + ToolRegistry + TraceStore SQLite +
OllamaClient (instructor structured outputs) + deterministic offline fallback.
**The RAG fiscal API (projet 6-RAG) runs on :8000 and serves as the `rag_fiscal` tool.**

## Stack
Python 3.11 · `uv` · Pydantic v2 · pydantic-settings · LangGraph · instructor ·
ollama (Python client) · Typer · httpx · rich · pytest · ruff.

## Architecture (`src/agent/`)
- **schemas.py** — 10 Pydantic v2 models: TaskRequest, ToolCall, SubTask,
  ExecutionPlan, ToolResult, AgentResult, ReviewResult, ApprovalRequest,
  TraceSpan, RunRecord. Plus `RiskLevel` enum (LOW/MEDIUM/HIGH).
- **config.py** — pydantic-settings `AgentConfig` (OLLAMA_BASE_URL, OLLAMA_MODEL,
  RAG_API_URL, TRACE_DB_PATH, FORCE_FALLBACK).
- **tools/registry.py** — `ToolRegistry`: register_tool / tool decorator / execute
  (captures inputs+outputs+latency) / get_risk / schema_for_llm.
- **tools/builtins.py** — 5 safe tools:
  - `list_files` (LOW) · `read_file` (LOW) · `search_text` (LOW) · `calculator` (LOW, no eval())
  - `rag_fiscal` (MEDIUM) — POST http://127.0.0.1:8000/query; graceful offline message.
  - `build_default_registry(rag_api_url=...)` factory.
- **trace.py** — `TraceStore` (SQLite, `:memory:` for tests): new_run / start_span /
  end_span / finish_run / save_approval / approve_run / export_run_json.
  Parent/child spans. `_SpanCtx` context manager.
- **llm.py** — `OllamaClient`: instructor.from_ollama() + deterministic fallback when
  `force_fallback=True` or Ollama unreachable. NEVER calls LLM in tests.
- **graph.py** — LangGraph 5 nodes: intake → plan → research → write → review → END.
  HIGH risk tool in plan → `approval_needed=True` → tool NOT executed → review sets
  verdict="approval_required" + saves ApprovalRequest to TraceStore.
  `run_task()` convenience wrapper.
- **cli.py** — Typer: `agent run <question>` / `agent runs list` / `agent runs show <id>`
  / `agent approve <id>`.

## Config (`.env` / env vars)
```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:1.7b-q4_K_M
RAG_API_URL=http://127.0.0.1:8000
TRACE_DB_PATH=data/traces.db
FORCE_FALLBACK=false   # set true to run 100% offline, no Ollama quota
```

## Commands
> **Windows + OneDrive gotcha:** same as 6-RAG — use `--link-mode=copy`.

```bash
# Setup
uv sync --extra dev --link-mode=copy

# Tests (NEVER call real Ollama — all mocked/force_fallback)
uv run --no-sync pytest -v

# Lint
uv run --no-sync ruff check .

# CLI
uv run --no-sync agent run "Quel est le barème de l'IR ?"
uv run --no-sync agent runs list
uv run --no-sync agent runs show <run_id>
uv run --no-sync agent approve <run_id>

# Force offline mode (no Ollama needed)
$env:FORCE_FALLBACK="true"; uv run --no-sync agent run "test"
```

## Hard rules
- **Tests NEVER call real Ollama.** Use `force_fallback=True` or mock `predict`.
- **calculator** uses AST, never `eval()`.
- **rag_fiscal** tool has a clear French offline message, never throws.
- **HIGH risk tools are NEVER executed without approval** (graph blocks them).
- Retrieval + verifier from 6-RAG are UNCHANGED — this project only calls the API.
- Answers in French where applicable.
- ruff + pytest green before stopping.

## Phase status
- ✅ Phase 1 — foundations (schemas, tools, trace, LLM, graph, CLI, frontend scaffold)
- ⬜ Phase 2 — FastAPI wrapper + Next.js UI
- ⬜ Phase 3 — multi-agent routing + memory
