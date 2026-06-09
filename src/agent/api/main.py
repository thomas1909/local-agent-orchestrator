"""FastAPI app — agent orchestrator HTTP API on :8100."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException

from agent.cloud_client import CloudClient, CloudModelError
from agent.config import get_config
from agent.schemas import TaskRequest
from agent.api.schemas import ApprovalDecision, RunCreate

from .deps import get_clients, get_llm, get_registry, get_trace, init_clients
from .runner import execute_run
from .schemas import HealthResponse

logger = logging.getLogger(__name__)

# ── Lifespan: create CloudClients at startup ────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        clients = init_clients()
        logger.info("CloudClients initialized: %s", {r: c.model for r, c in clients.items()})
    except (ValueError, CloudModelError) as exc:
        logger.error("Startup validation failed: %s", exc)
        raise SystemExit(f"Cloud model validation failed: {exc}") from exc
    yield


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agent Local — cloud-only orchestrator",
    version="0.3.0",
    lifespan=lifespan,
)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health(clients: dict[str, CloudClient] = Depends(get_clients)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        api="agent-local",
        cloud_models={role: client.model for role, client in clients.items()},
        validated=all(
            any(s in client.model for s in (":cloud", "-cloud"))
            for client in clients.values()
        ),
    )


@app.post("/run", status_code=201)
async def create_run(
    body: RunCreate,
    clients: dict[str, CloudClient] = Depends(get_clients),
    registry=Depends(get_registry),
    trace=Depends(get_trace),
):
    task = TaskRequest(question=body.question)
    run_id = trace.new_run(task)
    trace.set_run_status(run_id, "running")

    import asyncio
    asyncio.create_task(
        execute_run(run_id, task, clients, registry, trace)
    )
    return {"run_id": run_id, "status": "running"}


@app.get("/runs")
async def list_runs(trace=Depends(get_trace)):
    return trace.list_runs()


@app.get("/runs/{run_id}")
async def get_run(run_id: str, trace=Depends(get_trace)):
    detail = trace.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


@app.post("/runs/{run_id}/approve", status_code=200)
async def approve_run(
    run_id: str,
    body: ApprovalDecision,
    clients: dict[str, CloudClient] = Depends(get_clients),
    registry=Depends(get_registry),
    trace=Depends(get_trace),
):
    detail = trace.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_status = detail.get("status", "")
    if run_status != "approval_required":
        raise HTTPException(status_code=409, detail="Run is not pending approval")

    if body.decision == "accept":
        task_data = detail.get("task", {})
        task = TaskRequest(
            id=task_data.get("id", run_id),
            question=task_data.get("question", ""),
        )
        trace.set_run_status(run_id, "running")
        import asyncio
        asyncio.create_task(
            execute_run(run_id, task, clients, registry, trace, approved=True)
        )
        return {"ok": True, "run_id": run_id, "message": "Run approved — resuming"}

    if body.decision == "modify":
        # modify — not fully implemented in Phase 2
        return {"ok": True, "run_id": run_id, "message": "Modification acknowledged (Phase 3)"}

    # reject
    trace.set_run_status(run_id, "failed")
    return {"ok": True, "run_id": run_id, "message": "Run rejected"}