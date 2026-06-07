# Case Study — Local Agent Orchestrator

## The problem

I had already built a [local RAG pipeline](../../6-RAG): hybrid retrieval, a
cross-encoder reranker, and a deterministic grounding verifier over French tax
documents, served behind a FastAPI endpoint. It answers **one question at a time**.

Real work isn't one question. "Compute this household's quotient, then check the
ceiling, then look up the bracket" is a **multi-step task** that needs planning,
several tools, and — when an action is destructive — a human in the loop. That's
not a retrieval problem; it's an **orchestration** problem.

So the goal was to build the layer that sits *above* a RAG service: an agent runtime
that plans, calls tools, gates risk, and is fully observable — and to do it
**local-first**, so it costs nothing to run and never depends on cloud quota.

## The architecture

A LangGraph state machine with five nodes — `intake → plan → research → write →
review` — over a typed Pydantic state. Three pillars hang off it:

1. **Tool Registry.** Every tool is registered with a name, description, callable,
   and a **risk level** (LOW/MEDIUM/HIGH). Execution captures inputs, outputs, and
   latency into a `ToolResult`, and converts exceptions into structured errors
   rather than crashes. Five built-ins ship: `calculator` (AST-based, never `eval`),
   `list_files` / `read_file` / `search_text`, and `rag_fiscal` — which calls the
   companion RAG API. The RAG project becomes **one tool among many**.

2. **Trace Store.** A SQLite store of runs and spans. Spans have parent/child links,
   start/end timestamps, and computed `duration_ms`. A run exports to JSON, streams
   to the UI over SSE, and is the single source of truth for "what did the agent do?"

3. **Approval gate.** The research node refuses to execute a HIGH-risk tool unless
   the run was explicitly approved. Instead it flags `approval_needed`, the reviewer
   persists an `ApprovalRequest`, and the run lands in `approval_required`. A human
   `accept` re-runs the graph with `approved=True` and the tool finally executes.

On top: a FastAPI service (`/run`, `/runs`, `/runs/{id}`, `/approve`, `/health`,
SSE `/stream`, and an **MCP** mount) and a Next.js 15 / shadcn UI with a live span
tree and an approval panel.

## The decision I'm proudest of: a deterministic, offline-safe fallback

The hard constraint was **"must run with zero cloud quota, and the test suite must
never call a real model."** A naive agent is useless without its LLM — the planner
*is* an LLM call. So I made the LLM boundary degrade deterministically.

`OllamaClient.predict()` is typed by the Pydantic model it must return. When
`FORCE_FALLBACK=true`, or when Ollama is unreachable (a 2-second health probe), it
returns a **deterministic stub per response type**: a plan that routes the question
to the RAG tool, a review verdict of `approved`, and so on. The graph's write node
then substitutes real tool outputs into the answer. The result:

- **The entire pipeline runs offline** — planning, tool execution, escalation,
  tracing — without a single model call.
- **The 81-test suite is hermetic and fast** (~8 s), using either `FORCE_FALLBACK`
  or a tiny scripted planner. No quota, no flakiness, no network.
- **The eval is reproducible** — a scripted planner injects a fixed plan per task,
  so the golden set measures *orchestration* (did the right tools fire? did HIGH-risk
  escalate?) independently of model quality.

This is the difference between a demo and a system: the orchestration is correct and
testable on its own terms, and the model is a swappable component — local Ollama
today, a larger model tomorrow — that the runtime degrades around instead of
depending on.

A close second: **HIGH-risk tools are blocked by construction, not by prompt.** The
gate lives in the graph, not in an instruction the model might ignore — so the
guarantee holds even when the model misbehaves.

## The numbers

A 10-task golden set, run fully offline through the real pipeline
([`eval/report.md`](../eval/report.md)):

| Metric | Value |
|---|---|
| Tasks passed | **10 / 10 (100 %)** |
| Tool calls dispatched | 10 |
| Human-in-the-loop escalations | 1 (HIGH-risk `delete_file`, blocked then approved) |
| Orchestration overhead | **median 0 ms / task** |

Coverage: numeric correctness via `calculator` (3 tasks), file tools (3), offline-safe
RAG degradation (1), a multi-step plan (1), HIGH-risk escalation (1), and
post-approval execution (1). The two RAG-routed tasks include a real network
round-trip to the (deliberately down) RAG endpoint; that time is environment
dependent and is *not* orchestration cost — the median orchestration overhead is
sub-millisecond.

## What I'd do next

- **Memory** — feed the last N runs into the planner prompt for cross-task continuity.
- **Multi-agent routing** — a `route` node before `plan` that dispatches to a
  specialist (fiscal / math / files) instead of one generalist planner.
- **Answer-quality eval** — pair the orchestration eval with a model-on eval that
  scores answer correctness against labelled references, local vs. cloud.
