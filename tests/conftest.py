"""Shared fixtures — all offline (no Ollama, no network)."""
from __future__ import annotations

import pytest

from agent.llm import OllamaClient
from agent.schemas import ExecutionPlan, SubTask, TaskRequest, ToolCall
from agent.tools.builtins import build_default_registry
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore


@pytest.fixture()
def trace() -> TraceStore:
    """In-memory SQLite trace store — fresh per test."""
    return TraceStore(":memory:")


@pytest.fixture()
def fallback_llm() -> OllamaClient:
    """OllamaClient that always uses the deterministic fallback (no Ollama call)."""
    return OllamaClient(force_fallback=True)


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
