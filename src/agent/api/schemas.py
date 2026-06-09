"""API request/response DTOs — separate from domain schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.schemas import (
    AgentResult,
    ApprovalRequest,
    ExecutionPlan,
    ReviewResult,
    TaskRequest,
    TraceSpan,
)

# ── Requests ──────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    question: str
    context: dict[str, Any] = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    decision: Literal["accept", "reject", "modify"]
    note: str = ""


# Alias for main.py — clear name for the request body
RunCreate = RunRequest
ApprovalDecision = ApproveRequest


# ── Responses ─────────────────────────────────────────────────────────────────

class RunCreateResponse(BaseModel):
    run_id: str
    status: str


class RunSummary(BaseModel):
    id: str
    status: str
    created_at: str
    question: str


class RunDetail(BaseModel):
    id: str
    task: TaskRequest
    status: str
    plan: ExecutionPlan | None = None
    result: AgentResult | None = None
    review: ReviewResult | None = None
    approval: ApprovalRequest | None = None
    spans: list[TraceSpan] = Field(default_factory=list)


class ApproveResponse(BaseModel):
    ok: bool
    run_id: str
    message: str = ""


class HealthResponse(BaseModel):
    status: str
    api: str
    cloud_models: dict[str, str] = Field(default_factory=dict)
    validated: bool = True
    version: str = "0.3.0"