"""Offline golden-set eval for the agent orchestrator.

Runs each golden task through the REAL LangGraph pipeline with a deterministic
scripted planner (no Ollama, no quota). Measures success, tool calls, latency
and human-in-the-loop escalations, then writes a JSON + Markdown report.

Usage (from project root):
    uv run --no-sync python eval/run_eval.py
    uv run --no-sync python eval/run_eval.py --out eval/report
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Bypass any corporate HTTP proxy for localhost so the offline-RAG path fails
# fast (connection refused) instead of round-tripping through a proxy. This is
# an eval-environment setting only — product code (builtins.rag_fiscal) is
# untouched.
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Make `agent` importable when run as a plain script.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.graph import run_task  # noqa: E402
from agent.llm import OllamaClient  # noqa: E402
from agent.schemas import ExecutionPlan, RiskLevel, SubTask, TaskRequest, ToolCall  # noqa: E402
from agent.tools.builtins import build_default_registry  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.trace import TraceStore  # noqa: E402

# rag_fiscal is pointed at a closed high port so the eval is hermetic: it always
# exercises the graceful offline-degradation path (connection refused), never a
# live RAG instance. A high ephemeral port refuses fast on a normal host.
_OFFLINE_RAG_URL = "http://127.0.0.1:53999"


# ── Scripted planner (deterministic, zero Ollama) ─────────────────────────────

class ScriptedPlanner:
    """Returns a fixed ExecutionPlan for the plan step; delegates the rest to
    the deterministic offline fallback (which substitutes tool outputs into the
    final answer). 100% offline — no model is ever called."""

    def __init__(self, plan: ExecutionPlan) -> None:
        self._plan = plan
        self._fallback = OllamaClient(force_fallback=True)

    def predict(self, messages, response_model, task=None):  # noqa: ANN001
        if response_model is ExecutionPlan:
            return self._plan
        return self._fallback.predict(messages, response_model, task=task)

    def is_fallback_mode(self) -> bool:
        return True


# ── Registry with a demo HIGH-risk tool ───────────────────────────────────────

def _delete_file(path: str) -> str:
    """Sandboxed HIGH-risk demo tool — never touches the filesystem."""
    return f"Suppression simulée (sandbox, aucune action réelle) : {path}"


def build_eval_registry() -> ToolRegistry:
    registry = build_default_registry(rag_api_url=_OFFLINE_RAG_URL)
    registry.register_tool(
        "delete_file",
        "Supprime un fichier (DÉMO à risque élevé — sandbox, aucune action réelle).",
        _delete_file,
        RiskLevel.HIGH,
    )
    return registry


# ── Plan construction from the golden JSON ────────────────────────────────────

def _build_plan(task_id: str, plan_spec: list[dict[str, Any]]) -> ExecutionPlan:
    subtasks = [
        SubTask(
            description=st["description"],
            tool_calls=[
                ToolCall(tool_name=tc["tool_name"], arguments=tc.get("arguments", {}))
                for tc in st.get("tool_calls", [])
            ],
        )
        for st in plan_spec
    ]
    return ExecutionPlan(task_id=task_id, subtasks=subtasks, reasoning="[eval] plan scripté")


# ── Single task run ───────────────────────────────────────────────────────────

def run_one(task_def: dict[str, Any]) -> dict[str, Any]:
    registry = build_eval_registry()
    trace = TraceStore(":memory:")

    task = TaskRequest(question=task_def["question"])
    plan = _build_plan(task.id, task_def["plan"])
    planner = ScriptedPlanner(plan)
    approved = bool(task_def.get("approved", False))

    t0 = time.monotonic()
    final = run_task(task=task, llm=planner, registry=registry, trace=trace, approved=approved)
    latency_ms = int((time.monotonic() - t0) * 1000)

    run_id = final["run_id"]
    record = trace.export_run(run_id)
    status = record.status if record else "unknown"
    spans = trace.get_spans(run_id)
    tool_calls = sum(1 for s in spans if s.name.startswith("tool:"))
    escalation = bool(final.get("approval_needed", False))
    answer = final["result"].answer if final.get("result") else ""

    # ── Check expectations ────────────────────────────────────────────────────
    exp = task_def["expect"]
    checks: dict[str, bool] = {}
    checks["status"] = status == exp["status"]
    checks["tool_calls"] = tool_calls == exp["tool_calls"]
    checks["escalation"] = escalation == exp["escalation"]
    needle = exp.get("answer_contains", "")
    checks["answer_contains"] = (needle.lower() in answer.lower()) if needle else True

    success = all(checks.values())

    return {
        "id": task_def["id"],
        "title": task_def["title"],
        "question": task_def["question"],
        "success": success,
        "status": status,
        "tool_calls": tool_calls,
        "latency_ms": latency_ms,
        "escalation": escalation,
        "answer": answer,
        "checks": checks,
        "expected": exp,
    }


# ── Report rendering ──────────────────────────────────────────────────────────

def render_markdown(results: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Agent Orchestrator — Eval Report\n")
    lines.append(f"_Generated: {summary['generated_at']} · mode: **offline / deterministic** (no Ollama)._\n")

    lines.append("## Summary\n")
    lines.append(f"- **Tasks:** {summary['total']}")
    lines.append(f"- **Passed:** {summary['passed']} / {summary['total']} "
                 f"(**{summary['success_rate']:.0%}** success rate)")
    lines.append(f"- **Total tool calls executed:** {summary['total_tool_calls']}")
    lines.append(f"- **Human-in-the-loop escalations:** {summary['total_escalations']}")
    lines.append(f"- **Latency:** mean {summary['mean_latency_ms']} ms · "
                 f"median {summary['median_latency_ms']} ms · max {summary['max_latency_ms']} ms\n")

    lines.append("## Per-task results\n")
    lines.append("| Task | Status | Tools | Latency | Escalation | Result |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        mark = "✅" if r["success"] else "❌"
        esc = "⚠️ yes" if r["escalation"] else "—"
        lines.append(
            f"| {mark} `{r['id']}` — {r['title']} | {r['status']} | "
            f"{r['tool_calls']} | {r['latency_ms']} ms | {esc} | "
            f"{mark} |"
        )

    failed = [r for r in results if not r["success"]]
    if failed:
        lines.append("\n## Failures\n")
        for r in failed:
            bad = [k for k, v in r["checks"].items() if not v]
            lines.append(f"- `{r['id']}`: failed checks {bad} "
                         f"(got status={r['status']}, tools={r['tool_calls']}, "
                         f"escalation={r['escalation']})")

    lines.append("\n## What this measures\n")
    lines.append("- **Tool routing** — the planner's tool calls are dispatched and executed.")
    lines.append("- **Numeric correctness** — `calculator` results are checked against expected values.")
    lines.append("- **Offline safety** — `rag_fiscal` degrades gracefully when the RAG API is down.")
    lines.append("- **Human-in-the-loop** — HIGH-risk tools escalate to `approval_required` and are "
                 "**not** executed; after approval they run and the task completes.")
    lines.append("- **Observability** — every step is a trace span with latency.\n")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Offline golden-set eval")
    parser.add_argument("--golden", default=str(Path(__file__).parent / "golden_set.json"))
    parser.add_argument("--out", default=str(Path(__file__).parent / "report"),
                        help="Output path prefix (writes <out>.json and <out>.md)")
    args = parser.parse_args()

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    tasks = golden["tasks"]

    print(f"Running {len(tasks)} golden tasks (offline, deterministic)…\n")
    results = []
    for t in tasks:
        r = run_one(t)
        mark = "✅" if r["success"] else "❌"
        print(f"  {mark} {r['id']:<22} status={r['status']:<18} "
              f"tools={r['tool_calls']} {r['latency_ms']}ms")
        results.append(r)

    passed = sum(1 for r in results if r["success"])
    latencies = [r["latency_ms"] for r in results]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "total": len(results),
        "passed": passed,
        "success_rate": passed / len(results) if results else 0.0,
        "total_tool_calls": sum(r["tool_calls"] for r in results),
        "total_escalations": sum(1 for r in results if r["escalation"]),
        "mean_latency_ms": round(statistics.mean(latencies)) if latencies else 0,
        "median_latency_ms": round(statistics.median(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    json_path = out.with_suffix(".json")
    md_path = out.with_suffix(".md")
    json_path.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(results, summary), encoding="utf-8")

    print(f"\n{passed}/{len(results)} passed ({summary['success_rate']:.0%}). "
          f"Reports: {json_path.name}, {md_path.name}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
