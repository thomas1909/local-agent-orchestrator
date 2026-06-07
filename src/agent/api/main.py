"""FastAPI app — agent orchestrator HTTP API on :8100."""
from __future__ import annotations

import json

import anyio
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.api.deps import get_llm, get_registry, get_trace
from agent.api.runner import execute_run
from agent.api.schemas import (
    ApproveRequest,
    ApproveResponse,
    HealthResponse,
    RunCreateResponse,
    RunDetail,
    RunRequest,
    RunSummary,
)
from agent.llm import OllamaClient
from agent.schemas import TaskRequest
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

app = FastAPI(
    title="Agent Local",
    description="Local agent orchestrator — LangGraph + Ollama + RAG fiscal",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount MCP (optional — graceful if fastapi-mcp API changes) ────────────────
try:
    from fastapi_mcp import FastApiMCP  # type: ignore[import]
    _mcp = FastApiMCP(app, name="Agent Local")
    _mcp.mount_http()
except Exception:
    pass  # MCP is optional; never break the main API


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(llm: OllamaClient = Depends(get_llm)) -> HealthResponse:
    """API + Ollama status."""
    ollama_status = "offline" if llm.is_fallback_mode() else "online"
    return HealthResponse(status="ok", api="agent-local", ollama=ollama_status)


# ── Runs ──────────────────────────────────────────────────────────────────────

@app.post("/run", response_model=RunCreateResponse, tags=["runs"])
async def create_run(
    req: RunRequest,
    background_tasks: BackgroundTasks,
    llm: OllamaClient = Depends(get_llm),
    registry: ToolRegistry = Depends(get_registry),
    trace: TraceStore = Depends(get_trace),
) -> RunCreateResponse:
    """Submit a new task. Returns run_id immediately; execution runs in background."""
    task = TaskRequest(question=req.question, context=req.context)
    run_id = trace.new_run(task)
    background_tasks.add_task(execute_run, run_id, task, llm, registry, trace)
    return RunCreateResponse(run_id=run_id, status="running")


@app.get("/runs", response_model=list[RunSummary], tags=["runs"])
async def list_runs(trace: TraceStore = Depends(get_trace)) -> list[RunSummary]:
    """List all runs (most recent first)."""
    rows = trace.list_runs()
    return [RunSummary(**r) for r in rows]


@app.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
async def get_run(run_id: str, trace: TraceStore = Depends(get_trace)) -> RunDetail:
    """Full run detail including trace spans."""
    record = trace.export_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return RunDetail(
        id=record.id,
        task=record.task,
        status=record.status,
        plan=record.plan,
        result=record.result,
        review=record.review,
        approval=record.approval,
        spans=record.spans,
    )


@app.post("/runs/{run_id}/approve", response_model=ApproveResponse, tags=["runs"])
async def approve_run(
    run_id: str,
    req: ApproveRequest,
    background_tasks: BackgroundTasks,
    llm: OllamaClient = Depends(get_llm),
    registry: ToolRegistry = Depends(get_registry),
    trace: TraceStore = Depends(get_trace),
) -> ApproveResponse:
    """Approve, reject, or request modification of a run awaiting human review."""
    status = trace.get_run_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if status != "approval_required":
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run_id}' is not awaiting approval (status: {status})",
        )

    if req.decision == "accept":
        task = trace.get_run_task(run_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Could not load run task")
        background_tasks.add_task(execute_run, run_id, task, llm, registry, trace, True)
        return ApproveResponse(
            ok=True, run_id=run_id, message="Approved — re-executing with HIGH-risk tools"
        )

    if req.decision == "reject":
        trace.set_run_status(run_id, "failed")
        return ApproveResponse(ok=True, run_id=run_id, message="Run rejected")

    # modify — not fully implemented in Phase 2
    return ApproveResponse(
        ok=True, run_id=run_id, message="Modification acknowledged (Phase 3)"
    )


# ── SSE stream ────────────────────────────────────────────────────────────────

@app.get("/runs/{run_id}/stream", tags=["runs"])
async def stream_run_events(
    run_id: str, trace: TraceStore = Depends(get_trace)
) -> StreamingResponse:
    """Server-Sent Events: pushes spans and a final 'done' event for a run."""

    async def _generate():
        seen: set[str] = set()
        for _ in range(600):  # 300 s max
            spans = trace.get_spans(run_id)
            for span in spans:
                if span.id not in seen:
                    seen.add(span.id)
                    yield f"data: {span.model_dump_json()}\n\n"

            run_status = trace.get_run_status(run_id)
            if run_status in ("completed", "failed", "approval_required"):
                yield f"data: {json.dumps({'event': 'done', 'status': run_status})}\n\n"
                return

            await anyio.sleep(0.5)

        yield 'data: {"event": "timeout"}\n\n'

    return StreamingResponse(_generate(), media_type="text/event-stream")
