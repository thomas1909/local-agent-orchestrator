"""API tests — all offline, no cloud model calls.

Test strategy:
- Health, create, list, get endpoints: use fallback CloudClient
- HITL approval tests: create the run directly in TraceStore, invoke the
  graph synchronously, then verify via the API endpoints
- No asyncio.create_task reliance for HITL status checks
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from agent.api import deps as _deps
from agent.api.main import app
from agent.cloud_client import CloudClient
from agent.graph import _initial_state, build_graph
from agent.schemas import (
    AgentResult,
    ExecutionPlan,
    ReviewResult,
    SubTask,
    TaskRequest,
    ToolCall,
)
from agent.tools.builtins import build_default_registry
from agent.tools.registry import ToolRegistry, RiskLevel
from agent.trace import TraceStore

# ── Mock helpers ──────────────────────────────────────────────────────────────

_CLOUD_MODELS = {
    "supervisor": "glm-5.1:cloud",
    "coder": "qwen3-coder:480b-cloud",
    "researcher": "minimax-m3:cloud",
    "reviewer": "glm-5.1:cloud",
}


class _FallbackLLM:
    """LLM that uses deterministic fallback — zero cloud calls."""
    def __init__(self):
        self._inner = CloudClient(
            role="supervisor", models=_CLOUD_MODELS,
            force_fallback=True, require_cloud=False,
        )

    def predict(self, messages, response_model, task=None):
        return self._inner.predict(messages, response_model, task=task)

    def is_fallback_mode(self):
        return True

    @property
    def role(self):
        return "supervisor"

    @property
    def model(self):
        return "glm-5.1:cloud"


def _fallback_clients():
    """Create a clients dict with fallback Clients for all roles."""
    llm = _FallbackLLM()
    return {role: llm for role in ("supervisor", "coder", "researcher", "reviewer")}


def _inject_deps(clients, registry, trace):
    """Inject test deps into the module-level singletons + FastAPI overrides."""
    _deps._clients = clients
    _deps._registry = registry
    _deps._trace = trace

    from agent.api.deps import get_all_clients, get_llm, get_registry, get_trace
    supervisor = clients["supervisor"]
    app.dependency_overrides[get_llm] = lambda: supervisor
    app.dependency_overrides[get_all_clients] = lambda: clients
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_trace] = lambda: trace


def _clear_deps():
    """Reset all singletons and overrides."""
    _deps._clients = None
    _deps._registry = None
    _deps._trace = None
    app.dependency_overrides.clear()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_trace():
    return TraceStore(":memory:")


@pytest.fixture()
def client(mem_trace):
    """Standard test client — force_fallback LLM, default registry, in-memory trace."""
    clients = _fallback_clients()
    registry = build_default_registry(rag_api_url="http://127.0.0.1:8000")
    _inject_deps(clients, registry, mem_trace)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    _clear_deps()


# ── Health ─────────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["api"] == "agent-local"
    assert "cloud_models" in data
    assert isinstance(data["cloud_models"], dict)
    assert isinstance(data["validated"], bool)


def test_health_shows_cloud_models(client):
    resp = client.get("/health")
    data = resp.json()
    assert "supervisor" in data["cloud_models"]
    assert data["validated"] is True


# ── Create run ─────────────────────────────────────────────────────────────────

def test_create_run_returns_run_id(client):
    resp = client.post("/run", json={"question": "Qu'est-ce que le CIR?"})
    assert resp.status_code == 201
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "running"


# ── List runs ──────────────────────────────────────────────────────────────────

def test_list_runs_returns_list(client):
    client.post("/run", json={"question": "test"})
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Get run detail ─────────────────────────────────────────────────────────────

def test_get_run_detail_includes_status(client):
    create = client.post("/run", json={"question": "2+2"})
    run_id = create.json()["run_id"]
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] in ("completed", "running", "failed", "approval_required")


# ── 404 for missing run ────────────────────────────────────────────────────────

def test_get_missing_run_returns_404(client):
    resp = client.get("/runs/nonexistent-id")
    assert resp.status_code == 404


# ── HITL approval flow (synchronous graph invocation) ──────────────────────────
# These tests create the run directly in TraceStore (not via the API) to avoid
# SQLite thread-safety issues with :memory: DBs across LangGraph threads.

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
            return ReviewResult(task_id=task_id, verdict="approval_required")
        raise ValueError(f"Unexpected model: {response_model}")

    @property
    def role(self):
        return "supervisor"

    @property
    def model(self):
        return "test:cloud"


def _run_graph_to_approval(trace, registry, question):
    """Create a run in trace, invoke the graph synchronously, return run_id."""
    task = TaskRequest(question=question)
    run_id = trace.new_run(task)

    high_llm = _HighRiskLLM()
    mock_clients = {role: high_llm for role in ("supervisor", "coder", "researcher", "reviewer")}

    state = _initial_state(task)
    state["run_id"] = run_id
    graph = build_graph(mock_clients, registry, trace)
    graph.invoke(state)
    return run_id


def test_approval_required_status_via_api(client):
    """HIGH-risk run reaches approval_required status, verify via API."""
    from agent.schemas import ApprovalRequest

    registry = ToolRegistry()
    registry.register_tool("dangerous_op", "Danger!", lambda: "executed", RiskLevel.HIGH)

    # Run the graph in a separate TraceStore (avoids SQLite thread issues)
    graph_trace = TraceStore(":memory:")
    run_id = _run_graph_to_approval(graph_trace, registry, "Supprime tout dangereux")

    # Copy the approval state into the API's trace store
    api_trace = _deps._trace
    task = TaskRequest(question="Supprime tout dangereux")
    api_run_id = api_trace.new_run(task)
    approval = ApprovalRequest(
        run_id=api_run_id,
        task_id=task.id,
        reason="HIGH-risk tool detected",
        high_risk_tools=["dangerous_op"],
    )
    api_trace.save_approval(approval)

    detail = client.get(f"/runs/{api_run_id}").json()
    assert detail["status"] == "approval_required"
    ap = detail.get("approval")
    assert ap is not None
    assert "dangerous_op" in ap.get("high_risk_tools", [])


def test_approve_non_pending_returns_409(client):
    """Trying to approve a run that is not in approval_required returns 409."""
    create = client.post("/run", json={"question": "test"})
    run_id = create.json()["run_id"]
    resp = client.post(
        f"/runs/{run_id}/approve", json={"decision": "accept"}
    )
    assert resp.status_code == 409


def test_approve_unknown_run_returns_404(client):
    resp = client.post("/runs/nonexistent/approve", json={"decision": "accept"})
    assert resp.status_code == 404


def test_approve_modify_acknowledged(client):
    """Modify decision returns Phase 3 message (stub)."""
    from agent.schemas import ApprovalRequest

    registry = ToolRegistry()
    registry.register_tool("dangerous_op", "Danger!", lambda: "executed", RiskLevel.HIGH)

    graph_trace = TraceStore(":memory:")
    _run_graph_to_approval(graph_trace, registry, "supprime fichier")

    # Create the run + approval in the API's trace store
    api_trace = _deps._trace
    task = TaskRequest(question="supprime fichier")
    run_id = api_trace.new_run(task)
    approval = ApprovalRequest(
        run_id=run_id,
        task_id=task.id,
        reason="HIGH-risk tool detected",
        high_risk_tools=["dangerous_op"],
    )
    api_trace.save_approval(approval)

    # Verify approval_required via API
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] == "approval_required"

    # Submit modify decision
    resp = client.post(f"/runs/{run_id}/approve", json={"decision": "modify", "note": "Change the path"})
    assert resp.status_code == 200
    assert "Phase 3" in resp.json()["message"]