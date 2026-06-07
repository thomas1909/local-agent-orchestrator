"""OllamaClient with instructor structured outputs + deterministic offline fallback."""
from __future__ import annotations

import uuid
from typing import TypeVar

import httpx
from pydantic import BaseModel

from agent.schemas import AgentResult, ExecutionPlan, ReviewResult, SubTask, TaskRequest, ToolCall

T = TypeVar("T", bound=BaseModel)

_FALLBACK_MARKER = "[Mode hors-ligne]"


class OllamaClient:
    """Thin wrapper around instructor+ollama with a deterministic fallback.

    Set force_fallback=True (or FORCE_FALLBACK=true in .env) to bypass Ollama
    entirely — used in tests and offline development.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:1.7b-q4_K_M",
        force_fallback: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._force_fallback = force_fallback
        self._instructor_client = None

    # ── Public API ────────────────────────────────────────────────────────────

    def predict(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        task: TaskRequest | None = None,
    ) -> T:
        """Return a structured Pydantic response.

        Falls back to a deterministic stub when force_fallback is set or Ollama
        is unreachable — allowing the full graph to run without any LLM quota.
        """
        if self._force_fallback or not self._is_available():
            return self._deterministic_fallback(response_model, task)
        try:
            return self._instructor_predict(messages, response_model)
        except Exception:
            return self._deterministic_fallback(response_model, task)

    def is_fallback_mode(self) -> bool:
        return self._force_fallback or not self._is_available()

    # ── Instructor call ───────────────────────────────────────────────────────

    def _get_client(self):
        if self._instructor_client is None:
            import instructor
            from ollama import Client as OllamaBaseClient

            raw = OllamaBaseClient(host=self._base_url)
            self._instructor_client = instructor.from_ollama(
                raw, mode=instructor.Mode.JSON
            )
        return self._instructor_client

    def _instructor_predict(self, messages: list[dict[str, str]], response_model: type[T]) -> T:
        client = self._get_client()
        return client.chat.completions.create(
            model=self._model,
            messages=messages,
            response_model=response_model,
            max_retries=2,
        )

    # ── Availability check ────────────────────────────────────────────────────

    def _is_available(self) -> bool:
        try:
            r = httpx.get(f"{self._base_url}/api/tags", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    # ── Deterministic fallback ────────────────────────────────────────────────

    def _deterministic_fallback(self, response_model: type[T], task: TaskRequest | None) -> T:
        task_id = task.id if task else str(uuid.uuid4())
        question = task.question if task else ""

        if response_model is ExecutionPlan:
            return response_model(  # type: ignore[return-value]
                task_id=task_id,
                subtasks=[
                    SubTask(
                        description=f"Rechercher une réponse via RAG: {question[:80]}",
                        tool_calls=[
                            ToolCall(
                                tool_name="rag_fiscal",
                                arguments={"question": question},
                            )
                        ],
                    )
                ],
                reasoning=f"{_FALLBACK_MARKER} Plan déterministe (Ollama indisponible)",
            )

        if response_model is AgentResult:
            return response_model(  # type: ignore[return-value]
                task_id=task_id,
                answer=f"{_FALLBACK_MARKER} Ollama indisponible. Démarrez Ollama et relancez.",
            )

        if response_model is ReviewResult:
            return response_model(  # type: ignore[return-value]
                task_id=task_id,
                verdict="approved",
                notes=f"{_FALLBACK_MARKER} Revue automatique (Ollama indisponible)",
            )

        # Generic fallback: try to construct with minimal required fields
        try:
            return response_model(task_id=task_id)  # type: ignore[call-arg,return-value]
        except Exception:
            return response_model()  # type: ignore[call-arg,return-value]
