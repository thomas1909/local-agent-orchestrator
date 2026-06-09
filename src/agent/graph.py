"""LangGraph 5-node agent graph: intake → plan → research → write → review.

Each node uses the CloudClient for its designated role:
  - plan → supervisor
  - research → coder or researcher (based on tool)
  - write → researcher
  - review → reviewer
"""
from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent.cloud_client import CloudClient
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
    approved: bool          # set to True when human approved a HIGH-risk run
    run_id: str
    _root_span: str
    iteration: int          # revision loop counter (max 2)


def _initial_state(task: TaskRequest, approved: bool = False) -> GraphState:
    return {
        "task": task,
        "plan": None,
        "tool_results": [],
        "result": None,
        "review": None,
        "approval": None,
        "approval_needed": False,
        "approved": approved,
        "run_id": str(uuid.uuid4()),
        "_root_span": "",
        "iteration": 0,
    }


# ── Node implementations ──────────────────────────────────────────────────────

def _intake(state: GraphState, *, trace: TraceStore) -> GraphState:
    run_id: str = state["run_id"]
    span_id = trace.start_span(run_id, "intake", data={"question": state["task"].question})
    trace.end_span(span_id)
    return {"_root_span": span_id}


def _plan(
    state: GraphState,
    *,
    clients: dict[str, CloudClient],
    trace: TraceStore,
) -> GraphState:
    run_id = state["run_id"]
    task: TaskRequest = state["task"]
    llm = clients["supervisor"]

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
    trace.save_plan(run_id, plan)
    trace.end_span(span_id, data={"subtasks": len(plan.subtasks)})
    return {"plan": plan}


def _execute_subtasks(
    state: GraphState,
    *,
    clients: dict[str, CloudClient],
    registry: ToolRegistry,
    trace: TraceStore,
) -> GraphState:
    """Execute tool_calls for each SubTask, then synthesize via assigned_role LLM."""
    run_id = state["run_id"]
    plan: ExecutionPlan | None = state.get("plan")
    task: TaskRequest = state["task"]
    iteration = state.get("iteration", 0)

    span_id = trace.start_span(run_id, "execute_subtasks", data={"iteration": iteration})

    if plan is None:
        trace.end_span(span_id)
        return {"tool_results": [], "result": None, "approval_needed": False}

    tool_results: list[ToolResult] = []
    approval_needed = False

    for subtask in plan.subtasks:
        role = subtask.assigned_role
        for call in subtask.tool_calls:
            if not registry.has_tool(call.tool_name):
                tool_results.append(
                    ToolResult(
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                        output="",
                        error=f"Tool not registered: {call.tool_name!r}",
                        agent_role=role,
                        model=clients.get(role, clients["researcher"]).model if role in clients else "",
                    )
                )
                continue

            if registry.get_risk(call.tool_name) == RiskLevel.HIGH and not state.get("approved"):
                approval_needed = True
                continue

            span_id = trace.start_span(
                run_id,
                f"tool:{call.tool_name}",
                data={"tool": call.tool_name, "args": call.arguments, "agent_role": role},
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
                    "agent_role": role,
                },
            )
            # Enrich result with role/model for trace
            result.agent_role = role
            result.model = clients.get(role, clients["researcher"]).model if role in clients else ""
            tool_results.append(result)

    if approval_needed:
        result = AgentResult(
            task_id=task.id,
            answer="Approbation humaine requise avant d'exécuter des outils à risque élevé.",
        )
        trace.save_result(run_id, result)
        trace.end_span(span_id)
        return {"tool_results": tool_results, "result": result, "approval_needed": True}

    # Synthesize: for each subtask without tool_calls, call assigned_role client
    answers: list[str] = []
    for subtask in plan.subtasks:
        if subtask.tool_calls:
            continue
        role = subtask.assigned_role
        llm = clients.get(role, clients["researcher"])
        span_id = trace.start_span(
            run_id,
            f"synthesize:{role}",
            data={"subtask_id": subtask.id, "agent_role": role, "model": llm.model},
        )
        synthesis = llm.predict(
            messages=[
                {"role": "system", "content": "Tu es un assistant. Réponds en français."},
                {"role": "user", "content": f"Question: {task.question}\n\nSous-tâche: {subtask.description}"},
            ],
            response_model=AgentResult,
            task=task,
        )
        trace.end_span(span_id, data={"answer_len": len(synthesis.answer), "agent_role": role, "model": llm.model})
        answers.append(synthesis.answer)

    if answers:
        final_answer = "\n\n".join(answers)
    elif tool_results:
        final_answer = next((r.output for r in tool_results if not r.error), "")
    else:
        final_answer = ""

    result = AgentResult(
        task_id=task.id,
        answer=final_answer,
        sources=list({r.tool_name for r in tool_results}),
        tool_results=tool_results,
    )

    from agent.cloud_client import _FALLBACK_MARKER
    if result.answer.startswith(_FALLBACK_MARKER) and tool_results:
        best = next((r for r in tool_results if not r.error), None)
        if best:
            result = AgentResult(
                task_id=task.id,
                answer=best.output,
                sources=[r.tool_name for r in tool_results],
                tool_results=tool_results,
            )

    trace.save_result(run_id, result)
    trace.end_span(span_id)
    return {"tool_results": tool_results, "result": result, "approval_needed": False}


def _review(
    state: GraphState,
    *,
    clients: dict[str, CloudClient],
    registry: ToolRegistry,
    trace: TraceStore,
) -> GraphState:
    run_id = state["run_id"]
    task: TaskRequest = state["task"]
    plan: ExecutionPlan | None = state.get("plan")
    iteration = state.get("iteration", 0)

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
        trace.save_review(run_id, review)
        trace.save_approval(approval)
        trace.end_span(span_id, data={"verdict": "approval_required", "tools": high_risk})
        return {"review": review, "approval": approval}

    llm = clients["reviewer"]
    review = llm.predict(
        messages=[
            {"role": "system", "content": "Tu es un réviseur. Valide la cohérence et la qualité du résultat."},
            {"role": "user", "content": f"Question: {task.question}\nRéponse: {state.get('result', '')}"},
        ],
        response_model=ReviewResult,
        task=task,
    )
    trace.save_review(run_id, review)

    # Revision loop: increment counter if needs_revision, stop at max 2 iterations
    if review.verdict == "needs_revision" and iteration < 2:
        trace.end_span(span_id, data={"verdict": review.verdict, "iteration": iteration + 1})
        return {"review": review, "iteration": iteration + 1}

    trace.finish_run(run_id, "completed")
    trace.end_span(span_id, data={"verdict": review.verdict})
    return {"review": review}


# ── Conditional routing ─────────────────────────────────────────────────────

def _review_router(state: GraphState) -> str:
    review = state.get("review")
    iteration = state.get("iteration", 0)
    if review and review.verdict == "needs_revision" and iteration < 2:
        return "execute_subtasks"
    return END


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(
    clients: dict[str, CloudClient],
    registry: ToolRegistry,
    trace: TraceStore,
):
    """Return a compiled LangGraph StateGraph."""
    builder = StateGraph(GraphState)

    builder.add_node("intake", lambda s: _intake(s, trace=trace))
    builder.add_node("plan", lambda s: _plan(s, clients=clients, trace=trace))
    builder.add_node("execute_subtasks", lambda s: _execute_subtasks(s, clients=clients, registry=registry, trace=trace))
    builder.add_node("review", lambda s: _review(s, clients=clients, registry=registry, trace=trace))

    builder.set_entry_point("intake")
    builder.add_edge("intake", "plan")
    builder.add_edge("plan", "execute_subtasks")
    builder.add_edge("execute_subtasks", "review")
    builder.add_conditional_edges("review", lambda s: _review_router(s))

    return builder.compile()


# ── Convenience runner ────────────────────────────────────────────────────────

def run_task(
    task: TaskRequest,
    clients: dict[str, CloudClient],
    registry: ToolRegistry,
    trace: TraceStore,
    approved: bool = False,
) -> GraphState:
    run_id = trace.new_run(task)
    state = _initial_state(task, approved=approved)
    state["run_id"] = run_id
    graph = build_graph(clients=clients, registry=registry, trace=trace)
    final = graph.invoke(state)
    return final