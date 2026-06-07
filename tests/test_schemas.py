"""Validate the 10 Pydantic v2 schemas."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas import (
    AgentResult,
    ApprovalRequest,
    ExecutionPlan,
    ReviewResult,
    RiskLevel,
    RunRecord,
    SubTask,
    TaskRequest,
    ToolCall,
    ToolResult,
    TraceSpan,
)


def test_task_request_auto_id():
    t = TaskRequest(question="test")
    assert t.id
    assert t.question == "test"
    assert t.context == {}


def test_task_request_missing_question():
    with pytest.raises(ValidationError):
        TaskRequest()  # type: ignore[call-arg]


def test_tool_call_defaults():
    tc = ToolCall(tool_name="calculator")
    assert tc.arguments == {}


def test_subtask_empty_tool_calls():
    st = SubTask(description="step 1")
    assert st.tool_calls == []


def test_execution_plan_round_trip():
    plan = ExecutionPlan(
        task_id="abc",
        subtasks=[
            SubTask(description="s1", tool_calls=[ToolCall(tool_name="list_files")])
        ],
    )
    back = ExecutionPlan.model_validate_json(plan.model_dump_json())
    assert back.task_id == "abc"
    assert back.subtasks[0].tool_calls[0].tool_name == "list_files"


def test_tool_result_error_optional():
    r = ToolResult(tool_name="calc", output="42")
    assert r.error is None
    assert r.latency_ms == 0


def test_agent_result_sources_default():
    r = AgentResult(task_id="t1", answer="hello")
    assert r.sources == []
    assert r.tool_results == []


def test_review_result_verdict():
    rv = ReviewResult(task_id="t1", verdict="approved")
    assert rv.verdict == "approved"


def test_approval_request_status_default():
    ap = ApprovalRequest(
        run_id="r1", task_id="t1", reason="HIGH risk", high_risk_tools=["rm_file"]
    )
    assert ap.status == "pending"
    assert ap.high_risk_tools == ["rm_file"]


def test_trace_span_parent_optional():
    span = TraceSpan(id="s1", run_id="r1", name="test")
    assert span.parent_id is None


def test_run_record_status_default():
    task = TaskRequest(question="q")
    rec = RunRecord(id="r1", task=task)
    assert rec.status == "pending"
    assert rec.spans == []


def test_risk_level_values():
    assert RiskLevel.LOW == "LOW"
    assert RiskLevel.MEDIUM == "MEDIUM"
    assert RiskLevel.HIGH == "HIGH"
