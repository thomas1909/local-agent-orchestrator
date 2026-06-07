"""Background execution helpers — run graph in a thread, track per-run events."""
from __future__ import annotations

import asyncio

from agent.graph import _initial_state, build_graph
from agent.llm import OllamaClient
from agent.schemas import TaskRequest
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore


def execute_run_sync(
    run_id: str,
    task: TaskRequest,
    llm: OllamaClient,
    registry: ToolRegistry,
    trace: TraceStore,
    approved: bool = False,
) -> None:
    """Synchronous LangGraph execution — called via asyncio.to_thread."""
    try:
        trace.set_run_status(run_id, "running")
        state = _initial_state(task, approved=approved)
        state["run_id"] = run_id
        graph = build_graph(llm=llm, registry=registry, trace=trace)
        graph.invoke(state)
    except Exception:
        trace.set_run_status(run_id, "failed")
        raise


async def execute_run(
    run_id: str,
    task: TaskRequest,
    llm: OllamaClient,
    registry: ToolRegistry,
    trace: TraceStore,
    approved: bool = False,
) -> None:
    """Async wrapper used by BackgroundTasks."""
    await asyncio.to_thread(
        execute_run_sync, run_id, task, llm, registry, trace, approved
    )
