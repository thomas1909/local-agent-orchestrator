"""Tests: graph approval trigger on HIGH risk + end-to-end fallback run."""
from __future__ import annotations

from agent.cloud_client import CloudClient
from agent.graph import _initial_state, build_graph, run_task
from agent.schemas import (
    AgentResult,
    ExecutionPlan,
    ReviewResult,
    RiskLevel,
    SubTask,
    TaskRequest,
    ToolCall,
)
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

# ── Mock LLM helpers ──────────────────────────────────────────────────────────


class _MockLLM:
    def __init__(self, plan: ExecutionPlan) -> None:
        self._plan = plan
        self._call_count = 0

    def predict(self, **kwargs):
        self._call_count += 1
        if kwargs['response_model'] is ExecutionPlan:
            return self._plan
        if kwargs['response_model'] is AgentResult:
            task = kwargs.get('task')
            tid = task.id if task is not None else 't'
            return AgentResult(task_id=tid, answer="Réponse synthétisée")
        if kwargs['response_model'] is ReviewResult:
            task = kwargs.get('task')
            tid = task.id if task is not None else 't'
            return ReviewResult(task_id=tid, verdict="approved")
        raise ValueError(f"Unexpected response_model: {kwargs['response_model']}")

    def is_fallback_mode(self) -> bool:
        return False

    @property
    def role(self):
        return "supervisor"

    @property
    def model(self):
        return "test:cloud"


class _MockLLMReviewer:
    """Mock reviewer that returns needs_revision once then approved."""

    def __init__(self) -> None:
        self._call_count = 0

    def predict(self, **kwargs):
        self._call_count += 1
        if kwargs['response_model'] is ExecutionPlan:
            t = kwargs.get('task')
            return ExecutionPlan(task_id=t.id if t else '', subtasks=[])
        if kwargs['response_model'] is AgentResult:
            t = kwargs.get('task')
            return AgentResult(task_id=t.id if t else 't', answer="Réponse itération")
        if kwargs['response_model'] is ReviewResult:
            self._call_count += 1
            if self._call_count <= 1:
                t = kwargs.get('task')
                return ReviewResult(task_id=t.id if t else 't', verdict="needs_revision", notes="Corrige")
            t = kwargs.get('task')
            return ReviewResult(task_id=t.id if t else 't', verdict="approved", notes="OK")
        raise ValueError(f"Unexpected response_model: {kwargs['response_model']}")

    @property
    def role(self):
        return "reviewer"

    @property
    def model(self):
        return "test:cloud"

    def is_fallback_mode(self) -> bool:
        return False


def _make_clients(llm, reviewer=None):
    """Create a clients dict where all roles share the same mock LLM, except reviewer."""
    return {
        "supervisor": llm,
        "coder": llm,
        "researcher": llm,
        "reviewer": reviewer or llm,
    }


def _plan_with_high_risk(task: TaskRequest) -> ExecutionPlan:
    return ExecutionPlan(
        task_id=task.id,
        subtasks=[SubTask(
            description="Execute dangerous op",
            tool_calls=[ToolCall(tool_name="dangerous_op", arguments={})],
        )],
    )


def _plan_with_low_risk(task: TaskRequest) -> ExecutionPlan:
    return ExecutionPlan(
        task_id=task.id,
        subtasks=[SubTask(
            description="Calculate",
            tool_calls=[ToolCall(tool_name="calculator", arguments={"expression": "1+1"})],
        )],
    )


# ── Registry helpers ──────────────────────────────────────────────────────────

def _calc_fn(expression: str) -> str:
    return str(eval(expression))  # noqa: S307


def _registry_with_high_risk() -> ToolRegistry:
    r = ToolRegistry()
    r.register_tool("dangerous_op", "Dangerous!", lambda: "executed", RiskLevel.HIGH)
    r.register_tool("calculator", "Math", _calc_fn, RiskLevel.LOW)
    return r


def _low_risk_only_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register_tool("calculator", "Math", _calc_fn, RiskLevel.LOW)
    return r


# ── Approval trigger tests ────────────────────────────────────────────────────

def test_high_risk_tool_triggers_approval_needed():
    task = TaskRequest(question="Run dangerous operation")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_high_risk(task)))
    final = build_graph(clients, _registry_with_high_risk(), trace).invoke(state)
    assert final["approval_needed"] is True


def test_high_risk_tool_sets_approval_required_verdict():
    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_high_risk(task)))
    final = build_graph(clients, _registry_with_high_risk(), trace).invoke(state)
    assert final["review"].verdict == "approval_required"


def test_high_risk_tool_creates_approval_object():
    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_high_risk(task)))
    final = build_graph(clients, _registry_with_high_risk(), trace).invoke(state)
    approval = final.get("approval")
    assert approval is not None
    assert "dangerous_op" in approval.high_risk_tools
    assert approval.status == "pending"


def test_high_risk_tool_not_executed():
    """The HIGH risk tool function must never be called."""
    executed: list[bool] = []

    def _dangerous() -> str:
        executed.append(True)
        return "boom"

    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)

    r = ToolRegistry()
    r.register_tool("dangerous_op", "dangerous", _dangerous, RiskLevel.HIGH)

    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_high_risk(task)))
    build_graph(clients, r, trace).invoke(state)

    assert executed == [], "HIGH risk tool must NOT be executed without approval"


def test_high_risk_approval_stored_in_trace():
    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_high_risk(task)))
    build_graph(clients, _registry_with_high_risk(), trace).invoke(state)
    record = trace.export_run(run_id)
    assert record is not None
    assert record.approval is not None


# ── Full run (low-risk, fallback LLM) ────────────────────────────────────────

_CLOUD_MODELS = {
    "supervisor": "glm-5.1:cloud",
    "coder": "qwen3-coder:480b-cloud",
    "researcher": "minimax-m3:cloud",
    "reviewer": "glm-5.1:cloud",
}


def _fallback_clients():
    from agent.cloud_client import create_clients_from_config
    return create_clients_from_config(
        models=_CLOUD_MODELS,
        base_url="http://localhost:11434/v1",
        force_fallback=True,
        require_cloud=False,
    )


def test_full_run_with_fallback_llm(trace, default_registry, task):
    clients = _fallback_clients()
    final = run_task(task=task, clients=clients, registry=default_registry, trace=trace)
    assert final["result"] is not None
    assert final["review"] is not None
    assert final["approval_needed"] is False


def test_full_run_persists_result_and_plan(trace, default_registry, task):
    """After a run, export_run must expose the structured plan + result (not just spans)."""
    clients = _fallback_clients()
    final = run_task(task=task, clients=clients, registry=default_registry, trace=trace)
    record = trace.export_run(final["run_id"])
    assert record is not None
    assert record.plan is not None
    assert record.result is not None
    assert record.review is not None
    assert record.review.verdict == "approved"


def test_full_run_trace_has_all_nodes(trace, default_registry, task):
    clients = _fallback_clients()
    final = run_task(task=task, clients=clients, registry=default_registry, trace=trace)
    node_names = {s.name for s in trace.get_spans(final["run_id"])}
    assert {"intake", "plan", "execute_subtasks", "review"}.issubset(node_names)


def test_low_risk_run_verdict_approved():
    task = TaskRequest(question="What is 2+2?")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_low_risk(task)))
    final = build_graph(clients, _low_risk_only_registry(), trace).invoke(state)
    assert final["approval_needed"] is False
    assert final["review"].verdict == "approved"


def test_tool_result_captured_in_state():
    task = TaskRequest(question="Combien font 3*7 ?")
    trace = TraceStore(":memory:")
    r = ToolRegistry()
    r.register_tool("calculator", "Math", _calc_fn, RiskLevel.LOW)
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(_plan_with_low_risk(task)))
    final = build_graph(clients, r, trace).invoke(state)
    assert len(final["tool_results"]) == 1
    assert final["tool_results"][0].tool_name == "calculator"


# ── PR #2: multi-agent role routing ────────────────────────────────────────────

def test_assigned_role_coder_uses_coder_client():
    """A SubTask with assigned_role='coder' should cause _execute_subtasks to use clients['coder'] for synthesis."""
    task = TaskRequest(question="Écris un script Python qui calcule la factorielle")
    plan = ExecutionPlan(
        task_id=task.id,
        subtasks=[SubTask(description="Script factorielle", assigned_role="coder", tool_calls=[])],
    )
    calls: dict[str, int] = {}

    class _TrackingLLM:
        def __init__(self, role: str, model: str) -> None:
            self._role = role
            self._model = model
            self._call_count = 0

        def predict(self, **kwargs):
            self._call_count += 1
            calls[self._role] = calls.get(self._role, 0) + 1
            if kwargs['response_model'] is AgentResult:
                return AgentResult(task_id=task.id, answer=f"Résultat {self._role}")
            if kwargs['response_model'] is ExecutionPlan:
                return plan
            if kwargs['response_model'] is ReviewResult:
                return ReviewResult(task_id=task.id, verdict="approved")
            raise ValueError(f"Unexpected: {kwargs['response_model']}")

        @property
        def role(self) -> str:  return self._role

        @property
        def model(self) -> str:  return self._model

        def is_fallback_mode(self) -> bool:  return False

    clients = {
        "supervisor": _TrackingLLM("supervisor", "s:cloud"),
        "coder": _TrackingLLM("coder", "c:cloud"),
        "researcher": _TrackingLLM("researcher", "r:cloud"),
        "reviewer": _TrackingLLM("reviewer", "v:cloud"),
    }
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    final = build_graph(clients, _low_risk_only_registry(), trace).invoke(state)
    assert final["review"].verdict == "approved"
    assert "coder" in calls, "coder client should have been called for synthesis"


def test_tool_routing_respects_assigned_role_in_result():
    """ToolResult.agent_role and model must be populated from the SubTask's assigned_role."""
    task = TaskRequest(question="Exécuter commande")
    plan = ExecutionPlan(
        task_id=task.id,
        subtasks=[
            SubTask(
                description="List directory",
                assigned_role="coder",
                tool_calls=[ToolCall(tool_name="calculator", arguments={"expression": "1+1"})],
            )
        ],
    )
    trace = TraceStore(":memory:")
    r = _low_risk_only_registry()
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(plan))
    final = build_graph(clients, r, trace).invoke(state)
    assert len(final["tool_results"]) >= 1
    tr = final["tool_results"][0]
    assert tr.agent_role == "coder"
    assert tr.model == "test:cloud"


# ── PR #2: review revision loop ──────────────────────────────────────────────

def test_review_needs_revision_loops_max_twice():
    """If reviewer says needs_revision twice, the graph should stop at END after iteration 2."""
    task = TaskRequest(question="Question test")
    plan = ExecutionPlan(task_id=task.id, subtasks=[])

    class _StubReviewer:
        def __init__(self) -> None:
            self._calls = 0

        def predict(self, **kwargs):
            self._calls += 1
            if kwargs['response_model'] is ReviewResult:
                self._calls += 1
                if self._calls <= 1:
                    return ReviewResult(
                        task_id=task.id,
                        verdict="needs_revision",
                        notes="Corrige",
                    )
                return ReviewResult(
                    task_id=task.id,
                    verdict="approved" if self._calls > 1 else "needs_revision",
                    notes="Corrige",
                )
            if kwargs['response_model'] is ExecutionPlan:
                return plan
            if kwargs['response_model'] is AgentResult:
                return AgentResult(task_id=task.id, answer="Réponse")
            raise ValueError(f"Unexpected: {kwargs['response_model']}")

        @property
        def role(self) -> str:  return "reviewer"

        @property
        def model(self) -> str:  return "reviewer:cloud"

        def is_fallback_mode(self) -> bool:  return False

    # Need a plan LLM too
    class _StubPlan:
        def predict(self, **kwargs):
            if kwargs['response_model'] is ExecutionPlan:
                return plan
            if kwargs['response_model'] is AgentResult:
                return AgentResult(task_id=task.id, answer="Réponse")
            if kwargs['response_model'] is ReviewResult:
                return ReviewResult(task_id=task.id, verdict="approved")
            raise ValueError(f"Unexpected: {kwargs['response_model']}")

        @property
        def role(self) -> str:  return "supervisor"

        @property
        def model(self) -> str:  return "s:cloud"

        def is_fallback_mode(self) -> bool:  return False

    reviewer = _StubReviewer()
    plan_llm = _StubPlan()
    clients = {
        "supervisor": plan_llm,
        "coder": plan_llm,
        "researcher": plan_llm,
        "reviewer": reviewer,
    }
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    final = build_graph(clients, _low_risk_only_registry(), trace).invoke(state)
    assert final["review"].verdict == "approved"
    # Should have 4 execute_subtasks spans: 2 loops (needs_revision x2, needs_revision x2 no?)
    # Actually: plan -> execute -> review(needs) -> execute -> review(needs) -> execute -> review(approved)
    # So 3 execute_subtasks spans and 3 review spans
    spans = trace.get_spans(run_id)
    execute_spans = [s for s in spans if s.name == "execute_subtasks"]
    review_spans = [s for s in spans if s.name == "review"]
    assert len(execute_spans) <= 3, f"Expected max 3 execute_subtasks due to loop limits, got {len(execute_spans)}"
    assert len(review_spans) <= 3, f"Expected max 3 review spans, got {len(review_spans)}"


# ── PR #2: trace enrichment ──────────────────────────────────────────────────

def test_trace_spans_contain_agent_role_and_model():
    """Spans for tool/tool and synthesis nodes must include agent_role and model."""
    task = TaskRequest(question="Combien font 2+2 ?")
    plan = ExecutionPlan(
        task_id=task.id,
        subtasks=[
            SubTask(
                description="Calcul",
                assigned_role="coder",
                tool_calls=[ToolCall(tool_name="calculator", arguments={"expression": "1+1"})],
            ),
            SubTask(description="Synthèse", assigned_role="researcher", tool_calls=[]),
        ],
    )
    trace = TraceStore(":memory:")
    r = _low_risk_only_registry()
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    clients = _make_clients(_MockLLM(plan))
    final = build_graph(clients, r, trace).invoke(state)
    spans = trace.get_spans(run_id)
    # Find tool and synthesis spans
    tool_span = next((s for s in spans if s.name == "tool:calculator"), None)
    assert tool_span is not None
    assert tool_span.data.get("agent_role") == "coder", f"tool span data: {tool_span.data}"

    synth_span = next((s for s in spans if s.name == "synthesize:researcher"), None)
    assert synth_span is not None
    assert synth_span.data.get("agent_role") == "researcher"
    assert synth_span.data.get("model") == "test:cloud"


# ── PR #2: fallback plan assigns roles ─────────────────────────────────────────

def test_fallback_plan_assigns_coder_to_edit_task():
    """When FORCE_FALLBACK=true, _route_subtask should assign 'coder' role to edit tasks."""
    from agent.cloud_client import _route_subtask
    subtask = _route_subtask("Écris le fichier rapport.txt avec contenu 'hello'")
    assert subtask.assigned_role == "coder"


# ── PR #2: fallback plan assigns researcher to rag ───────────────────────────

def test_fallback_plan_assigns_researcher_to_rag():
    """When FORCE_FALLBACK=true, _route_subtask should assign 'researcher' role to rag_fiscal."""
    from agent.cloud_client import _route_subtask
    subtask = _route_subtask("Quel est le plafond du quotient familial ?")
    assert subtask.assigned_role == "researcher"
