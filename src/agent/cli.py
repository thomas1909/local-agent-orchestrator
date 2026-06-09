"""Typer CLI: agent run / agent runs list / agent runs show / agent approve."""
from __future__ import annotations

import json

import typer
from rich import print as rprint
from rich.table import Table

app = typer.Typer(
    name="agent",
    help="Cloud-only agent orchestrator — LangGraph + Instructor + ToolRegistry + HITL",
    no_args_is_help=True,
)

runs_app = typer.Typer(help="Manage past runs.")
app.add_typer(runs_app, name="runs")


def _make_deps(cfg=None):
    """Build cloud clients, registry, and trace from config."""
    from agent.cloud_client import CloudClient, create_clients_from_config
    from agent.config import get_config
    from agent.tools.builtins import build_default_registry
    from agent.trace import TraceStore

    if cfg is None:
        cfg = get_config()

    import os
    os.makedirs("data", exist_ok=True)

    clients = create_clients_from_config(
        models=cfg.models_by_role,
        base_url=cfg.cloud_base_url,
        force_fallback=cfg.force_fallback,
        require_cloud=cfg.should_validate_cloud,
        api_key=cfg.cloud_api_key,
    )
    registry = build_default_registry(rag_api_url=cfg.rag_api_url)
    trace = TraceStore(db_path=cfg.trace_db_path)
    return clients, registry, trace


# ── agent run ─────────────────────────────────────────────────────────────────

@app.command()
def run(
    question: str = typer.Argument(..., help="Task / question to process"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Run a new task through the agent pipeline."""
    from agent.graph import run_task
    from agent.schemas import TaskRequest

    clients, registry, trace = _make_deps()
    task = TaskRequest(question=question)

    supervisor = clients["supervisor"]

    if not json_output:
        rprint(f"[bold cyan]▶ Task:[/bold cyan] {question}")
        rprint(f"[dim]run_id preview: {task.id[:8]}…[/dim]")
        rprint(f"[dim]models: {', '.join(f'{r}:{m}' for r, m in {c.role: c.model for c in clients.values()}.items())}[/dim]")
        if supervisor.is_fallback_mode():
            rprint("[yellow]⚠  Mode fallback déterministe (tests uniquement)[/yellow]")

    final = run_task(task=task, clients=clients, registry=registry, trace=trace)

    result = final.get("result")
    review = final.get("review")
    approval = final.get("approval")

    if json_output:
        out = {
            "run_id": final.get("run_id"),
            "answer": result.answer if result else None,
            "verdict": review.verdict if review else None,
            "approval_needed": final.get("approval_needed"),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    rprint(f"\n[bold green]✔ run_id:[/bold green] {final.get('run_id')}")

    if result:
        rprint("\n[bold]Réponse:[/bold]")
        rprint(result.answer)

    if review:
        verdict_color = "green" if review.verdict == "approved" else "yellow"
        rprint(f"\n[bold]Verdict:[/bold] [{verdict_color}]{review.verdict}[/{verdict_color}]")
        if review.notes:
            rprint(f"[dim]{review.notes}[/dim]")

    if approval:
        rprint(
            f"\n[bold red]⚠ Approbation requise[/bold red] — "
            f"outils: {', '.join(approval.high_risk_tools)}"
        )
        rprint(f"[dim]Approuver avec: agent approve {final.get('run_id')}[/dim]")


# ── agent runs list ───────────────────────────────────────────────────────────

@runs_app.command("list")
def runs_list() -> None:
    """List all past runs."""
    from agent.config import get_config
    from agent.trace import TraceStore

    cfg = get_config()
    trace = TraceStore(db_path=cfg.trace_db_path)
    rows = trace.list_runs()

    if not rows:
        rprint("[dim]No runs found.[/dim]")
        return

    table = Table(title="Agent Runs")
    table.add_column("run_id", style="cyan", no_wrap=True)
    table.add_column("status")
    table.add_column("created_at")
    for r in rows:
        rid = r["id"]
        status = r["status"]
        color = "green" if status == "completed" else "yellow" if "approval" in status else "red"
        table.add_row(rid, f"[{color}]{status}[/{color}]", r["created_at"][:19])

    rprint(table)


# ── agent runs show ───────────────────────────────────────────────────────────

@runs_app.command("show")
def runs_show(run_id: str = typer.Argument(..., help="Run ID to inspect")) -> None:
    """Show full JSON record for a run (task, spans, approval)."""
    from agent.config import get_config
    from agent.trace import TraceStore

    cfg = get_config()
    trace = TraceStore(db_path=cfg.trace_db_path)
    payload = trace.export_run_json(run_id)
    if payload is None:
        rprint(f"[red]Run not found:[/red] {run_id}")
        raise typer.Exit(1)
    print(payload)


# ── agent approve ─────────────────────────────────────────────────────────────

@app.command()
def approve(run_id: str = typer.Argument(..., help="Run ID to approve")) -> None:
    """Approve a pending high-risk run."""
    from agent.config import get_config
    from agent.trace import TraceStore

    cfg = get_config()
    trace = TraceStore(db_path=cfg.trace_db_path)
    ok = trace.approve_run(run_id)
    if ok:
        rprint(f"[green]✔ Run approved:[/green] {run_id}")
    else:
        rprint(f"[red]Cannot approve run:[/red] {run_id} (not found or not in approval_required status)")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()