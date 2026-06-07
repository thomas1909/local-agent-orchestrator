"""API tests — all offline, no Ollama calls (force_fallback=True + dep overrides)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.api.deps import get_llm, get_registry, get_trace
from agent.api.main import app
from agent.llm import OllamaClient
from agent.schemas import (
    AgentResult,
    ExecutionPlan,
    ReviewResult,
    RiskLevel,
    SubTask,
    ToolCall,
)
from agent.tools.builtins import build_default_registry
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

# ── Mock helpers ──────────────────────────────────────────────────────────────

class _FallbackLLM:
    """LLM that uses deterministic fallback — zero Ollama calls."""
    def __init__(self):
        self._inner = OllamaClient(force_fallback=True)

    def predict(self, messages, response_model, task=None):
        return self._inner.predict(messages, response_model, task=task)

    def is_fallback_mode(self):
        return True


class _HighRiskLLM:
    """Returns a plan that calls a HIGH-risk tool."""
    def predict(self, messages, response_model, task=None):
        task_id = task.id if task else "test"
        if response_model is ExecutionPlan:
            return ExecutionPlan(
                task_id=task_id,
                subtasks=[SubTask(
                    description="Dangerous op",
                    tool_calls=[ToolCall(tool_name="dangerous_op", arguments={})],
                )],
            )
        if response_model is AgentResult:
            return AgentResult(task_id=task_id, answer="Done (approved)")
        if response_model is ReviewResult:
            return ReviewResult(task_id=task_id, verdict="approved")
        raise ValueError(f"Unexpected model: {response_model}")

    def is_fallback_mode(self):
        return False


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_trace():
    return TraceStore(":memory:")


@pytest.fixture()
def client(mem_trace):
    """Standard test client — force_fallback LLM, default registry, in-memory trace."""
    llm = _FallbackLLM()
    registry = build_default_registry(rag_api_url="http://127.0.0.1:8000")

    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_trace] = lambda: mem_trace

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def client_high_risk(mem_trace):
    """Client wired with a HIGH-risk LLM plan and a registry that has the tool."""
    llm = _HighRiskLLM()
    registry = ToolRegistry()
    registry.register_tool("dangerous_op", "Danger!", lambda: "executed", RiskLevel.HIGH)

    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_trace] = lambda: mem_trace

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["api"] == "agent-local"
    assert data["ollama"] in ("online", "offline")


def test_health_shows_offline_when_fallback(client):
    resp = client.get("/health")
    assert resp.json()["ollama"] == "offline"


# ── POST /run ─────────────────────────────────────────────────────────────────

def test_create_run_returns_run_id(client):
    resp = client.post("/run", json={"question": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["run_id"]


def test_create_run_background_completes(client, mem_trace):
    resp = client.post("/run", json={"question": "Quel est le barème IR ?"})
    run_id = resp.json()["run_id"]
    # BackgroundTasks complete before TestClient returns
    status = mem_trace.get_run_status(run_id)
    assert status in ("completed", "approval_required", "failed")


def test_create_run_with_context(client):
    resp = client.post("/run", json={"question": "test", "context": {"lang": "fr"}})
    assert resp.status_code == 200


# ── GET /runs ─────────────────────────────────────────────────────────────────

def test_list_runs_empty_initially(client):
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_runs_after_create(client):
    client.post("/run", json={"question": "q1"})
    client.post("/run", json={"question": "q2"})
    resp = client.get("/runs")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert all("id" in r and "status" in r and "question" in r for r in items)


def test_list_runs_most_recent_first(client):
    client.post("/run", json={"question": "first"})
    client.post("/run", json={"question": "second"})
    runs = client.get("/runs").json()
    assert runs[0]["question"] == "second"


# ── GET /runs/{id} ────────────────────────────────────────────────────────────

def test_get_run_detail(client):
    run_id = client.post("/run", json={"question": "detail test"}).json()["run_id"]
    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run_id
    assert data["task"]["question"] == "detail test"
    assert "spans" in data
    assert isinstance(data["spans"], list)


def test_get_run_not_found(client):
    resp = client.get("/runs/not-a-real-id")
    assert resp.status_code == 404


def test_get_run_has_status(client):
    run_id = client.post("/run", json={"question": "status check"}).json()["run_id"]
    data = client.get(f"/runs/{run_id}").json()
    assert data["status"] in ("completed", "approval_required", "failed", "running")


def test_get_run_has_trace_spans(client):
    run_id = client.post("/run", json={"question": "spans check"}).json()["run_id"]
    data = client.get(f"/runs/{run_id}").json()
    assert len(data["spans"]) > 0
    span_names = {s["name"] for s in data["spans"]}
    assert "intake" in span_names


# ── POST /runs/{id}/approve ───────────────────────────────────────────────────

def test_approve_not_found(client):
    resp = client.post("/runs/fake-id/approve", json={"decision": "accept"})
    assert resp.status_code == 404


def test_approve_non_pending_run(client):
    run_id = client.post("/run", json={"question": "normal run"}).json()["run_id"]
    # A standard run has no HIGH-risk tools so status is "completed"
    resp = client.post(f"/runs/{run_id}/approve", json={"decision": "accept"})
    assert resp.status_code == 409


def test_approve_reject_sets_failed(client_high_risk, mem_trace):
    run_id = client_high_risk.post("/run", json={"question": "dangerous"}).json()["run_id"]
    assert mem_trace.get_run_status(run_id) == "approval_required"
    resp = client_high_risk.post(f"/runs/{run_id}/approve", json={"decision": "reject"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert mem_trace.get_run_status(run_id) == "failed"


# ── Approval flow: HIGH risk → awaiting_approval → accept → completed ─────────

def test_approval_flow_high_risk_enters_approval_required(client_high_risk, mem_trace):
    run_id = client_high_risk.post("/run", json={"question": "danger"}).json()["run_id"]
    data = client_high_risk.get(f"/runs/{run_id}").json()
    assert data["status"] == "approval_required"
    assert data["approval"] is not None
    assert "dangerous_op" in data["approval"]["high_risk_tools"]


def test_approval_flow_accept_resumes_and_completes(client_high_risk, mem_trace):
    run_id = client_high_risk.post("/run", json={"question": "danger"}).json()["run_id"]
    assert mem_trace.get_run_status(run_id) == "approval_required"

    # Accept — re-run with approved=True happens in background (TestClient = sync)
    resp = client_high_risk.post(f"/runs/{run_id}/approve", json={"decision": "accept"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Background re-run completed by now
    assert mem_trace.get_run_status(run_id) == "completed"


def test_approval_flow_rejected_run_not_rerun(client_high_risk, mem_trace):
    run_id = client_high_risk.post("/run", json={"question": "danger"}).json()["run_id"]
    client_high_risk.post(f"/runs/{run_id}/approve", json={"decision": "reject"})
    assert mem_trace.get_run_status(run_id) == "failed"
    # Should not be re-runnable
    resp = client_high_risk.post(f"/runs/{run_id}/approve", json={"decision": "accept"})
    assert resp.status_code == 409


# ── GET /runs/{id}/stream (SSE) ───────────────────────────────────────────────

def test_sse_returns_event_stream(client):
    run_id = client.post("/run", json={"question": "sse test"}).json()["run_id"]
    resp = client.get(f"/runs/{run_id}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


def test_sse_contains_span_events(client):
    run_id = client.post("/run", json={"question": "sse spans"}).json()["run_id"]
    resp = client.get(f"/runs/{run_id}/stream")
    content = resp.text
    assert "data:" in content


def test_sse_contains_done_event(client):
    run_id = client.post("/run", json={"question": "sse done"}).json()["run_id"]
    resp = client.get(f"/runs/{run_id}/stream")
    assert '"event": "done"' in resp.text


# ── Fallback: full flow without Ollama ────────────────────────────────────────

def test_full_fallback_flow(client):
    resp = client.post("/run", json={"question": "Quel est le plafond du quotient familial ?"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] in ("completed", "approval_required")
    assert detail["task"]["question"] == "Quel est le plafond du quotient familial ?"
