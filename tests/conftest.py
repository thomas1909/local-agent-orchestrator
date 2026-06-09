"""Shared fixtures — all offline (no cloud calls, no network)."""
from __future__ import annotations

import pytest

from agent.cloud_client import CloudClient
from agent.schemas import ExecutionPlan, SubTask, TaskRequest, ToolCall
from agent.tools.builtins import build_default_registry
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

_CLOUD_MODELS = {
    "supervisor": "glm-5.1:cloud",
    "coder": "qwen3-coder:480b-cloud",
    "researcher": "minimax-m3:cloud",
    "reviewer": "glm-5.1:cloud",
}


@pytest.fixture()
def trace() -> TraceStore:
    """In-memory SQLite trace store — fresh per test."""
    return TraceStore(":memory:")


@pytest.fixture()
def fallback_llm() -> CloudClient:
    """CloudClient in fallback mode (no cloud calls, deterministic routing)."""
    return CloudClient(
        role="supervisor",
        models=_CLOUD_MODELS,
        force_fallback=True,
        require_cloud=False,
    )


@pytest.fixture()
def default_registry() -> ToolRegistry:
    """Default built-in tool registry."""
    return build_default_registry(rag_api_url="http://127.0.0.1:8000")


@pytest.fixture()
def task() -> TaskRequest:
    return TaskRequest(question="Quel est le plafond du quotient familial ?")


@pytest.fixture()
def simple_plan(task: TaskRequest) -> ExecutionPlan:
    return ExecutionPlan(
        task_id=task.id,
        subtasks=[
            SubTask(
                description="Appel RAG",
                tool_calls=[ToolCall(tool_name="rag_fiscal", arguments={"question": task.question})],
            )
        ],
    )