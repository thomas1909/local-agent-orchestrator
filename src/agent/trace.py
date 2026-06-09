"""TraceStore — SQLite-backed spans with parent/child hierarchy."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from agent.schemas import (
    AgentResult,
    ApprovalRequest,
    ExecutionPlan,
    ReviewResult,
    RunRecord,
    TaskRequest,
    TraceSpan,
)


class TraceStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id          TEXT PRIMARY KEY,
                task_json   TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                approval_json TEXT,
                plan_json   TEXT,
                result_json TEXT,
                review_json TEXT,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS spans (
                id          TEXT PRIMARY KEY,
                run_id      TEXT NOT NULL,
                parent_id   TEXT,
                name        TEXT NOT NULL,
                data_json   TEXT NOT NULL DEFAULT '{}',
                started_at  TEXT NOT NULL,
                ended_at    TEXT,
                duration_ms INTEGER,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
        """)
        # Migrate older DBs that predate the plan/result/review columns.
        existing = {r["name"] for r in self._conn.execute("PRAGMA table_info(runs)")}
        for col in ("plan_json", "result_json", "review_json"):
            if col not in existing:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
        self._conn.commit()

    # ── Runs ──────────────────────────────────────────────────────────────────

    def new_run(self, task: TaskRequest) -> str:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO runs (id, task_json, status, created_at) VALUES (?, ?, 'running', ?)",
            (run_id, task.model_dump_json(), now),
        )
        self._conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        self._conn.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
        self._conn.commit()

    def save_approval(self, approval: ApprovalRequest) -> None:
        self._conn.execute(
            "UPDATE runs SET status='approval_required', approval_json=? WHERE id=?",
            (approval.model_dump_json(), approval.run_id),
        )
        self._conn.commit()

    def approve_run(self, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT approval_json, status FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return False
        if row["status"] != "approval_required":
            return False
        data = json.loads(row["approval_json"])
        data["status"] = "approved"
        self._conn.execute(
            "UPDATE runs SET status='completed', approval_json=? WHERE id=?",
            (json.dumps(data), run_id),
        )
        self._conn.commit()
        return True

    def save_plan(self, run_id: str, plan: ExecutionPlan) -> None:
        self._conn.execute(
            "UPDATE runs SET plan_json=? WHERE id=?", (plan.model_dump_json(), run_id)
        )
        self._conn.commit()

    def save_result(self, run_id: str, result: AgentResult) -> None:
        self._conn.execute(
            "UPDATE runs SET result_json=? WHERE id=?", (result.model_dump_json(), run_id)
        )
        self._conn.commit()

    def save_review(self, run_id: str, review: ReviewResult) -> None:
        self._conn.execute(
            "UPDATE runs SET review_json=? WHERE id=?", (review.model_dump_json(), run_id)
        )
        self._conn.commit()

    def set_run_status(self, run_id: str, status: str) -> None:
        """Generic status update; alias for finish_run with any status."""
        self._conn.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
        self._conn.commit()

    def get_run_status(self, run_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        return row["status"] if row else None

    def get_run_task(self, run_id: str) -> TaskRequest | None:
        row = self._conn.execute(
            "SELECT task_json FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return TaskRequest.model_validate_json(row["task_json"])

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, status, created_at, task_json FROM runs ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            try:
                task = TaskRequest.model_validate_json(r["task_json"])
                question = task.question
            except Exception:
                question = ""
            result.append({
                "id": r["id"],
                "status": r["status"],
                "created_at": r["created_at"],
                "question": question,
            })
        return result

    # ── Spans ─────────────────────────────────────────────────────────────────

    def start_span(
        self,
        run_id: str,
        name: str,
        parent_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        span_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO spans (id, run_id, parent_id, name, data_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (span_id, run_id, parent_id, name, json.dumps(data or {}), now),
        )
        self._conn.commit()
        return span_id

    def end_span(self, span_id: str, data: dict[str, Any] | None = None) -> None:
        row = self._conn.execute(
            "SELECT started_at FROM spans WHERE id=?", (span_id,)
        ).fetchone()
        now = datetime.now(UTC)
        duration_ms: int | None = None
        if row:
            started = datetime.fromisoformat(row["started_at"])
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            duration_ms = int((now - started).total_seconds() * 1000)
        self._conn.execute(
            "UPDATE spans SET ended_at=?, duration_ms=?, data_json=? WHERE id=?",
            (now.isoformat(), duration_ms, json.dumps(data or {}), span_id),
        )
        self._conn.commit()

    def get_spans(self, run_id: str) -> list[TraceSpan]:
        rows = self._conn.execute(
            "SELECT * FROM spans WHERE run_id=? ORDER BY started_at", (run_id,)
        ).fetchall()
        spans = []
        for r in rows:
            spans.append(
                TraceSpan(
                    id=r["id"],
                    run_id=r["run_id"],
                    parent_id=r["parent_id"],
                    name=r["name"],
                    data=json.loads(r["data_json"]),
                    started_at=datetime.fromisoformat(r["started_at"]),
                    ended_at=datetime.fromisoformat(r["ended_at"]) if r["ended_at"] else None,
                    duration_ms=r["duration_ms"],
                )
            )
        return spans

    # ── Export ────────────────────────────────────────────────────────────────

    def export_run(self, run_id: str) -> RunRecord | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        task = TaskRequest.model_validate_json(row["task_json"])
        approval = (
            ApprovalRequest.model_validate_json(row["approval_json"])
            if row["approval_json"]
            else None
        )
        keys = row.keys()
        plan = (
            ExecutionPlan.model_validate_json(row["plan_json"])
            if "plan_json" in keys and row["plan_json"]
            else None
        )
        result = (
            AgentResult.model_validate_json(row["result_json"])
            if "result_json" in keys and row["result_json"]
            else None
        )
        review = (
            ReviewResult.model_validate_json(row["review_json"])
            if "review_json" in keys and row["review_json"]
            else None
        )
        spans = self.get_spans(run_id)
        return RunRecord(
            id=run_id,
            task=task,
            plan=plan,
            result=result,
            review=review,
            approval=approval,
            spans=spans,
            status=row["status"],
        )

    def get_run_detail(self, run_id: str) -> dict | None:
        """Return a JSON-friendly dict for the API endpoint."""
        record = self.export_run(run_id)
        if record is None:
            return None
        d = record.model_dump()
        # Ensure task is a dict (for API JSON response)
        if isinstance(d.get("task"), dict):
            d["task"] = d["task"]
        return d

    def export_run_json(self, run_id: str) -> str | None:
        record = self.export_run(run_id)
        if record is None:
            return None
        return record.model_dump_json(indent=2)

    def close(self) -> None:
        self._conn.close()

    # ── Context manager ───────────────────────────────────────────────────────

    def span(
        self,
        run_id: str,
        name: str,
        parent_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> _SpanCtx:
        return _SpanCtx(self, run_id, name, parent_id, data)


class _SpanCtx:
    def __init__(
        self,
        store: TraceStore,
        run_id: str,
        name: str,
        parent_id: str | None,
        data: dict[str, Any] | None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._name = name
        self._parent_id = parent_id
        self._data = data
        self.span_id: str = ""
        self._t0: float = 0.0

    def __enter__(self) -> _SpanCtx:
        self.span_id = self._store.start_span(
            self._run_id, self._name, self._parent_id, self._data
        )
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        self._store.end_span(self.span_id)
