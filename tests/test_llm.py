"""Tests: OllamaClient deterministic fallback — zero Ollama calls."""
from __future__ import annotations

from agent.llm import _FALLBACK_MARKER, OllamaClient
from agent.schemas import AgentResult, ExecutionPlan, ReviewResult


def _client() -> OllamaClient:
    return OllamaClient(force_fallback=True)


# ── Fallback correctness ──────────────────────────────────────────────────────

def test_fallback_returns_execution_plan(task):
    client = _client()
    plan = client.predict([], ExecutionPlan, task=task)
    assert isinstance(plan, ExecutionPlan)
    assert plan.task_id == task.id
    assert len(plan.subtasks) >= 1
    assert _FALLBACK_MARKER in plan.reasoning


def test_fallback_plan_contains_rag_tool(task):
    client = _client()
    plan = client.predict([], ExecutionPlan, task=task)
    all_tools = [
        call.tool_name
        for subtask in plan.subtasks
        for call in subtask.tool_calls
    ]
    assert "rag_fiscal" in all_tools


def test_fallback_plan_passes_question(task):
    client = _client()
    plan = client.predict([], ExecutionPlan, task=task)
    args = plan.subtasks[0].tool_calls[0].arguments
    assert args.get("question") == task.question


def test_fallback_returns_agent_result(task):
    client = _client()
    result = client.predict([], AgentResult, task=task)
    assert isinstance(result, AgentResult)
    assert result.task_id == task.id
    assert _FALLBACK_MARKER in result.answer


def test_fallback_returns_review_result(task):
    client = _client()
    review = client.predict([], ReviewResult, task=task)
    assert isinstance(review, ReviewResult)
    assert review.verdict == "approved"
    assert _FALLBACK_MARKER in review.notes


def test_fallback_without_task():
    client = _client()
    plan = client.predict([], ExecutionPlan, task=None)
    assert isinstance(plan, ExecutionPlan)
    assert plan.task_id  # auto-generated


def test_is_fallback_mode_when_forced():
    client = OllamaClient(force_fallback=True)
    assert client.is_fallback_mode() is True


def test_is_fallback_mode_when_unreachable():
    client = OllamaClient(base_url="http://127.0.0.1:19999", force_fallback=False)
    assert client.is_fallback_mode() is True


def test_fallback_does_not_call_instructor(task, monkeypatch):
    """Ensure force_fallback=True never touches instructor/ollama imports."""
    called = []

    def _fake_get_client(self):
        called.append("instructor_called")

    monkeypatch.setattr(OllamaClient, "_get_client", _fake_get_client)

    client = OllamaClient(force_fallback=True)
    client.predict([], ExecutionPlan, task=task)

    assert called == [], "instructor must NOT be invoked in fallback mode"
