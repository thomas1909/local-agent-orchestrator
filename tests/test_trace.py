"""Tests: TraceStore — parent/child spans + JSON export."""
from __future__ import annotations

import json
import time

from agent.schemas import TaskRequest


def test_new_run_creates_record(trace):
    task = TaskRequest(question="test question")
    run_id = trace.new_run(task)
    assert run_id
    runs = trace.list_runs()
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert runs[0]["status"] == "running"


def test_finish_run_updates_status(trace):
    task = TaskRequest(question="q")
    run_id = trace.new_run(task)
    trace.finish_run(run_id, "completed")
    runs = trace.list_runs()
    assert runs[0]["status"] == "completed"


def test_span_created_and_ended(trace):
    task = TaskRequest(question="q")
    run_id = trace.new_run(task)

    span_id = trace.start_span(run_id, "intake", data={"x": 1})
    time.sleep(0.01)
    trace.end_span(span_id, data={"result": "ok"})

    spans = trace.get_spans(run_id)
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "intake"
    assert span.run_id == run_id
    assert span.parent_id is None
    assert span.ended_at is not None
    assert span.duration_ms is not None
    assert span.duration_ms >= 0


def test_spans_parent_child_relationship(trace):
    task = TaskRequest(question="q")
    run_id = trace.new_run(task)

    root_id = trace.start_span(run_id, "root")
    child_id = trace.start_span(run_id, "child", parent_id=root_id)
    grandchild_id = trace.start_span(run_id, "grandchild", parent_id=child_id)

    trace.end_span(grandchild_id)
    trace.end_span(child_id)
    trace.end_span(root_id)

    spans = {s.name: s for s in trace.get_spans(run_id)}
    assert spans["root"].parent_id is None
    assert spans["child"].parent_id == root_id
    assert spans["grandchild"].parent_id == child_id


def test_multiple_spans_ordered_by_start(trace):
    task = TaskRequest(question="q")
    run_id = trace.new_run(task)

    for name in ["intake", "plan", "research", "write", "review"]:
        sid = trace.start_span(run_id, name)
        trace.end_span(sid)

    spans = trace.get_spans(run_id)
    names = [s.name for s in spans]
    assert names == ["intake", "plan", "research", "write", "review"]


def test_export_run_json_valid(trace):
    task = TaskRequest(question="What is the tax bracket?")
    run_id = trace.new_run(task)

    sid = trace.start_span(run_id, "plan", data={"subtasks": 2})
    trace.end_span(sid)
    trace.finish_run(run_id, "completed")

    payload = trace.export_run_json(run_id)
    assert payload is not None
    data = json.loads(payload)

    assert data["id"] == run_id
    assert data["task"]["question"] == task.question
    assert data["status"] == "completed"
    assert isinstance(data["spans"], list)
    assert len(data["spans"]) == 1
    assert data["spans"][0]["name"] == "plan"


def test_export_run_json_span_has_data(trace):
    task = TaskRequest(question="q")
    run_id = trace.new_run(task)
    sid = trace.start_span(run_id, "tool:calculator", data={"args": {"expression": "1+1"}})
    trace.end_span(sid, data={"output": "2", "latency_ms": 5})
    payload = trace.export_run_json(run_id)
    assert payload is not None
    parsed = json.loads(payload)
    assert parsed["spans"][0]["name"] == "tool:calculator"


def test_export_run_unknown_id_returns_none(trace):
    assert trace.export_run_json("not-a-real-id") is None


def test_approval_save_and_approve(trace):
    from agent.schemas import ApprovalRequest

    task = TaskRequest(question="danger")
    run_id = trace.new_run(task)

    approval = ApprovalRequest(
        run_id=run_id,
        task_id=task.id,
        reason="HIGH risk tool",
        high_risk_tools=["rm_file"],
    )
    trace.save_approval(approval)

    runs = trace.list_runs()
    assert runs[0]["status"] == "approval_required"

    ok = trace.approve_run(run_id)
    assert ok is True

    runs = trace.list_runs()
    assert runs[0]["status"] == "completed"


def test_approve_unknown_run_returns_false(trace):
    assert trace.approve_run("does-not-exist") is False


def test_export_run_persists_plan_result_review(trace):
    from agent.schemas import (
        AgentResult,
        ExecutionPlan,
        ReviewResult,
        SubTask,
        ToolCall,
    )

    task = TaskRequest(question="Combien font 6*7 ?")
    run_id = trace.new_run(task)

    plan = ExecutionPlan(
        task_id=task.id,
        subtasks=[SubTask(
            description="Calculer",
            tool_calls=[ToolCall(tool_name="calculator", arguments={"expression": "6*7"})],
        )],
    )
    trace.save_plan(run_id, plan)
    trace.save_result(run_id, AgentResult(task_id=task.id, answer="42"))
    trace.save_review(run_id, ReviewResult(task_id=task.id, verdict="approved"))

    record = trace.export_run(run_id)
    assert record is not None
    assert record.plan is not None
    assert record.plan.subtasks[0].tool_calls[0].tool_name == "calculator"
    assert record.result is not None
    assert record.result.answer == "42"
    assert record.review is not None
    assert record.review.verdict == "approved"


def test_span_context_manager(trace):
    task = TaskRequest(question="q")
    run_id = trace.new_run(task)

    with trace.span(run_id, "intake") as ctx:
        assert ctx.span_id

    spans = trace.get_spans(run_id)
    assert spans[0].ended_at is not None
