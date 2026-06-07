"""10 Pydantic v2 models for the agent orchestrator."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── 1. TaskRequest ────────────────────────────────────────────────────────────
class TaskRequest(BaseModel):
    id: str = Field(default_factory=_uid)
    question: str
    context: dict[str, Any] = Field(default_factory=dict)


# ── 2. ToolCall ───────────────────────────────────────────────────────────────
class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


# ── 3. SubTask ────────────────────────────────────────────────────────────────
class SubTask(BaseModel):
    id: str = Field(default_factory=_uid)
    description: str
    tool_calls: list[ToolCall] = Field(default_factory=list)


# ── 4. ExecutionPlan ──────────────────────────────────────────────────────────
class ExecutionPlan(BaseModel):
    task_id: str
    subtasks: list[SubTask]
    reasoning: str = ""


# ── 5. ToolResult ─────────────────────────────────────────────────────────────
class ToolResult(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: str
    error: str | None = None
    latency_ms: int = 0


# ── 6. AgentResult ────────────────────────────────────────────────────────────
class AgentResult(BaseModel):
    task_id: str
    answer: str
    sources: list[str] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)


# ── 7. ReviewResult ───────────────────────────────────────────────────────────
class ReviewResult(BaseModel):
    task_id: str
    # "approved" | "needs_revision" | "approval_required"
    verdict: str
    notes: str = ""


# ── 8. ApprovalRequest ────────────────────────────────────────────────────────
class ApprovalRequest(BaseModel):
    run_id: str
    task_id: str
    reason: str
    high_risk_tools: list[str]
    # "pending" | "approved" | "rejected"
    status: str = "pending"
    created_at: datetime = Field(default_factory=_now)


# ── 9. TraceSpan ──────────────────────────────────────────────────────────────
class TraceSpan(BaseModel):
    id: str = Field(default_factory=_uid)
    run_id: str
    parent_id: str | None = None
    name: str
    data: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    duration_ms: int | None = None


# ── 10. RunRecord ─────────────────────────────────────────────────────────────
class RunRecord(BaseModel):
    id: str
    task: TaskRequest
    plan: ExecutionPlan | None = None
    result: AgentResult | None = None
    review: ReviewResult | None = None
    approval: ApprovalRequest | None = None
    spans: list[TraceSpan] = Field(default_factory=list)
    # "pending" | "running" | "completed" | "approval_required" | "failed"
    status: str = "pending"
    created_at: datetime = Field(default_factory=_now)
