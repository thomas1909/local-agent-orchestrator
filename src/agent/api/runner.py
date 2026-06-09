"""Background execution helpers — run graph in a thread, track per-run events."""
from __future__ import annotations

import asyncio

from agent.cloud_client import CloudClient
from agent.config import get_config
from agent.graph import _initial_state, build_graph
from agent.schemas import TaskRequest
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore


def execute_run_sync(
    run_id: str,
    task: TaskRequest,
    clients: dict[str, CloudClient],
    registry: ToolRegistry,
    trace: TraceStore,
    approved: bool = False,
) -> None:
    """Synchronous LangGraph execution — called via asyncio.to_thread."""
    try:
        trace.set_run_status(run_id, "running")
        state = _initial_state(task, approved=approved)
        state["run_id"] = run_id
        graph = build_graph(clients=clients, registry=registry, trace=trace)
        graph.invoke(state)
    except Exception:
        trace.set_run_status(run_id, "failed")
        raise


async def execute_run(
    run_id: str,
    task: TaskRequest,
    clients: dict[str, CloudClient],
    registry: ToolRegistry,
    trace: TraceStore,
    approved: bool = False,
) -> None:
    """Async wrapper used by BackgroundTasks."""
    await asyncio.to_thread(
        execute_run_sync, run_id, task, clients, registry, trace, approved
    )