"""Tests: graph approval trigger on HIGH risk + end-to-end fallback run."""
from __future__ import annotations

from agent.graph import _initial_state, build_graph, run_task
from agent.llm import OllamaClient
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

    def predict(self, messages, response_model, task=None):
        self._call_count += 1
        if response_model is ExecutionPlan:
            return self._plan
        if response_model is AgentResult:
            return AgentResult(task_id=task.id if task else "t", answer="Réponse synthétisée")
        if response_model is ReviewResult:
            return ReviewResult(task_id=task.id if task else "t", verdict="approved")
        raise ValueError(f"Unexpected response_model: {response_model}")

    def is_fallback_mode(self) -> bool:
        return False


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
    final = build_graph(_MockLLM(_plan_with_high_risk(task)), _registry_with_high_risk(), trace).invoke(state)
    assert final["approval_needed"] is True


def test_high_risk_tool_sets_approval_required_verdict():
    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    final = build_graph(_MockLLM(_plan_with_high_risk(task)), _registry_with_high_risk(), trace).invoke(state)
    assert final["review"].verdict == "approval_required"


def test_high_risk_tool_creates_approval_object():
    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    final = build_graph(_MockLLM(_plan_with_high_risk(task)), _registry_with_high_risk(), trace).invoke(state)
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
    build_graph(_MockLLM(_plan_with_high_risk(task)), r, trace).invoke(state)

    assert executed == [], "HIGH risk tool must NOT be executed without approval"


def test_high_risk_approval_stored_in_trace():
    task = TaskRequest(question="danger")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    build_graph(_MockLLM(_plan_with_high_risk(task)), _registry_with_high_risk(), trace).invoke(state)
    record = trace.export_run(run_id)
    assert record is not None
    assert record.status == "approval_required"
    assert record.approval is not None


# ── Full run (low-risk, fallback LLM) ────────────────────────────────────────

def test_full_run_with_fallback_llm(trace, default_registry, task):
    final = run_task(task=task, llm=OllamaClient(force_fallback=True), registry=default_registry, trace=trace)
    assert final["result"] is not None
    assert final["review"] is not None
    assert final["approval_needed"] is False


def test_full_run_trace_has_all_nodes(trace, default_registry, task):
    final = run_task(task=task, llm=OllamaClient(force_fallback=True), registry=default_registry, trace=trace)
    node_names = {s.name for s in trace.get_spans(final["run_id"])}
    assert {"intake", "plan", "write", "review"}.issubset(node_names)


def test_low_risk_run_verdict_approved():
    task = TaskRequest(question="What is 2+2?")
    trace = TraceStore(":memory:")
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    final = build_graph(_MockLLM(_plan_with_low_risk(task)), _low_risk_only_registry(), trace).invoke(state)
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
    final = build_graph(_MockLLM(_plan_with_low_risk(task)), r, trace).invoke(state)
    assert len(final["tool_results"]) == 1
    assert final["tool_results"][0].tool_name == "calculator"
