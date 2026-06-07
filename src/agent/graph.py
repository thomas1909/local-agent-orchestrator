"""LangGraph 5-node agent graph: intake → plan → research → write → review."""
from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent.llm import OllamaClient
from agent.schemas import (
    AgentResult,
    ApprovalRequest,
    ExecutionPlan,
    ReviewResult,
    RiskLevel,
    TaskRequest,
    ToolResult,
)
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

# ── State ─────────────────────────────────────────────────────────────────────


class GraphState(TypedDict, total=False):
    task: TaskRequest
    plan: ExecutionPlan | None
    tool_results: list[ToolResult]
    result: AgentResult | None
    review: ReviewResult | None
    approval: ApprovalRequest | None
    approval_needed: bool
    run_id: str
    _root_span: str


def _initial_state(task: TaskRequest) -> GraphState:
    return {
        "task": task,
        "plan": None,
        "tool_results": [],
        "result": None,
        "review": None,
        "approval": None,
        "approval_needed": False,
        "run_id": str(uuid.uuid4()),
        "_root_span": "",
    }


# ── Node implementations ──────────────────────────────────────────────────────

def _intake(state: GraphState, *, trace: TraceStore) -> GraphState:
    run_id: str = state["run_id"]
    span_id = trace.start_span(run_id, "intake", data={"question": state["task"].question})
    trace.end_span(span_id)
    return {"_root_span": span_id}


def _plan(state: GraphState, *, llm: OllamaClient, trace: TraceStore) -> GraphState:
    run_id = state["run_id"]
    task: TaskRequest = state["task"]

    span_id = trace.start_span(run_id, "plan", parent_id=state.get("_root_span"))
    plan = llm.predict(
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un planificateur d'agent. "
                    "Décompose la question en sous-tâches avec les outils appropriés. "
                    "Réponds UNIQUEMENT en JSON valide."
                ),
            },
            {"role": "user", "content": f"Question: {task.question}"},
        ],
        response_model=ExecutionPlan,
        task=task,
    )
    trace.end_span(span_id, data={"subtasks": len(plan.subtasks)})
    return {"plan": plan}


def _research(state: GraphState, *, registry: ToolRegistry, trace: TraceStore) -> GraphState:
    run_id = state["run_id"]
    plan: ExecutionPlan | None = state.get("plan")
    if plan is None:
        return {"tool_results": [], "approval_needed": False}

    tool_results: list[ToolResult] = []
    approval_needed = False

    for subtask in plan.subtasks:
        for call in subtask.tool_calls:
            if not registry.has_tool(call.tool_name):
                tool_results.append(
                    ToolResult(
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                        output="",
                        error=f"Tool not registered: {call.tool_name!r}",
                    )
                )
                continue

            if registry.get_risk(call.tool_name) == RiskLevel.HIGH:
                # Do not execute HIGH risk tools without explicit human approval
                approval_needed = True
                continue

            span_id = trace.start_span(
                run_id,
                f"tool:{call.tool_name}",
                data={"tool": call.tool_name, "args": call.arguments},
            )
            result = registry.execute(call)
            trace.end_span(
                span_id,
                data={
                    "tool": call.tool_name,
                    "args": call.arguments,
                    "output_preview": result.output[:120],
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                },
            )
            tool_results.append(result)

    return {"tool_results": tool_results, "approval_needed": approval_needed}


def _write(state: GraphState, *, llm: OllamaClient, trace: TraceStore) -> GraphState:
    run_id = state["run_id"]
    task: TaskRequest = state["task"]
    tool_results: list[ToolResult] = state.get("tool_results", [])

    span_id = trace.start_span(run_id, "write", data={"approval_needed": state.get("approval_needed")})

    if state.get("approval_needed"):
        result = AgentResult(
            task_id=task.id,
            answer="Approbation humaine requise avant d'exécuter des outils à risque élevé.",
        )
        trace.end_span(span_id, data={"answer_len": len(result.answer)})
        return {"result": result}

    if tool_results:
        context = "\n\n".join(
            f"[{r.tool_name}]: {r.output}" for r in tool_results if not r.error
        )
        messages = [
            {"role": "system", "content": "Tu es un assistant. Synthétise la réponse en français."},
            {"role": "user", "content": f"Question: {task.question}\n\nSources:\n{context}"},
        ]
    else:
        messages = [
            {"role": "system", "content": "Tu es un assistant. Réponds en français."},
            {"role": "user", "content": task.question},
        ]

    result = llm.predict(messages=messages, response_model=AgentResult, task=task)

    # When in fallback mode but tool results are available, use them directly
    if result.answer.startswith("[Mode hors-ligne]") and tool_results:
        best = next((r for r in tool_results if not r.error), None)
        if best:
            result = AgentResult(
                task_id=task.id,
                answer=best.output,
                sources=[r.tool_name for r in tool_results],
                tool_results=tool_results,
            )

    trace.end_span(span_id, data={"answer_len": len(result.answer)})
    return {"result": result}


def _review(state: GraphState, *, registry: ToolRegistry, trace: TraceStore) -> GraphState:
    run_id = state["run_id"]
    task: TaskRequest = state["task"]
    plan: ExecutionPlan | None = state.get("plan")

    span_id = trace.start_span(run_id, "review")

    if state.get("approval_needed") and plan is not None:
        high_risk = [
            call.tool_name
            for subtask in plan.subtasks
            for call in subtask.tool_calls
            if registry.has_tool(call.tool_name)
            and registry.get_risk(call.tool_name) == RiskLevel.HIGH
        ]
        approval = ApprovalRequest(
            run_id=run_id,
            task_id=task.id,
            reason="Outils à risque élevé détectés dans le plan",
            high_risk_tools=high_risk,
        )
        review = ReviewResult(
            task_id=task.id,
            verdict="approval_required",
            notes=f"Approbation requise pour: {', '.join(high_risk)}",
        )
        trace.save_approval(approval)
        trace.end_span(span_id, data={"verdict": "approval_required", "tools": high_risk})
        return {"review": review, "approval": approval}

    review = ReviewResult(
        task_id=task.id,
        verdict="approved",
        notes="Réponse vérifiée automatiquement.",
    )
    trace.finish_run(run_id, "completed")
    trace.end_span(span_id, data={"verdict": "approved"})
    return {"review": review}


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(
    llm: OllamaClient,
    registry: ToolRegistry,
    trace: TraceStore,
):
    """Return a compiled LangGraph StateGraph."""
    builder = StateGraph(GraphState)

    builder.add_node("intake", lambda s: _intake(s, trace=trace))
    builder.add_node("plan", lambda s: _plan(s, llm=llm, trace=trace))
    builder.add_node("research", lambda s: _research(s, registry=registry, trace=trace))
    builder.add_node("write", lambda s: _write(s, llm=llm, trace=trace))
    builder.add_node("review", lambda s: _review(s, registry=registry, trace=trace))

    builder.set_entry_point("intake")
    builder.add_edge("intake", "plan")
    builder.add_edge("plan", "research")
    builder.add_edge("research", "write")
    builder.add_edge("write", "review")
    builder.add_edge("review", END)

    return builder.compile()


# ── Convenience runner ────────────────────────────────────────────────────────

def run_task(
    task: TaskRequest,
    llm: OllamaClient,
    registry: ToolRegistry,
    trace: TraceStore,
) -> GraphState:
    run_id = trace.new_run(task)
    state = _initial_state(task)
    state["run_id"] = run_id
    graph = build_graph(llm=llm, registry=registry, trace=trace)
    final = graph.invoke(state)
    return final
