"""OllamaClient with instructor structured outputs (OpenAI SDK) + deterministic offline fallback."""
from __future__ import annotations

import re
import uuid
from typing import TypeVar

import httpx
from pydantic import BaseModel

from agent.schemas import AgentResult, ExecutionPlan, ReviewResult, SubTask, TaskRequest, ToolCall

T = TypeVar("T", bound=BaseModel)

_FALLBACK_MARKER = "[Mode hors-ligne]"

# Two numbers joined by at least one arithmetic operator (× / x / ÷ accepted).
_MATH_RE = re.compile(r"-?\d+(?:[.,]\d+)?(?:\s*[-+*/×x÷]\s*-?\d+(?:[.,]\d+)?)+")
_BASH_KEYWORDS = (
    "ls", "cat", "grep", "find", "pwd", "echo", "curl", "wget",
    "bash", "shell", "commande", "exécute", "exécuter", "terminal",
    "run command", "execute command",
)
_DELETE_KEYWORDS = (
    "supprime", "supprimer", "efface", "effacer", "delete", "remove",
)
_EDIT_KEYWORDS = (
    "crée", "créer", "écrit", "écrire", "écris", "enregistre", "enregistrer",
    "sauve", "sauver", "sauvegarder", "write", "create file", "save",
)


def _route_subtask(question: str) -> SubTask:
    """Deterministic keyword routing for the offline planner.

    edit → edit_file (LOW) · bash → execute_bash (HIGH) · delete → delete_file (HIGH) · math → calculator · else → rag_fiscal.
    """
    q = question.lower()
    if any(k in q for k in _EDIT_KEYWORDS):
        path_m = re.search(r"[\w./\\-]+\.\w+", question)
        path = path_m.group(0) if path_m else "output.txt"
        content_m = re.search(r"""['"\u00ab](.+?)['"\u00bb]""", question)
        content = content_m.group(1) if content_m else ""
        return SubTask(
            description=f"Écriture de fichier: {path}",
            tool_calls=[ToolCall(tool_name="edit_file", arguments={"path": path, "content": content})],
        )
    if any(k in q for k in _BASH_KEYWORDS):
        return SubTask(
            description=f"Exécution de commande shell: {question[:80]}",
            tool_calls=[ToolCall(tool_name="execute_bash", arguments={"command": question, "timeout": 30})],
        )
    if any(k in q for k in _DELETE_KEYWORDS):
        m = re.search(r"[\w./\\-]+\.\w+", question)
        path = m.group(0) if m else "rapport.txt"
        return SubTask(
            description=f"Action à risque élevé demandée: {question[:80]}",
            tool_calls=[ToolCall(tool_name="delete_file", arguments={"path": path})],
        )
    m = _MATH_RE.search(question)
    if m:
        expr = m.group(0)
        for src, dst in (("×", "*"), ("x", "*"), ("÷", "/"), (",", ".")):
            expr = expr.replace(src, dst)
        expr = re.sub(r"\s+", "", expr)
        return SubTask(
            description=f"Calculer: {expr}",
            tool_calls=[ToolCall(tool_name="calculator", arguments={"expression": expr})],
        )
    return SubTask(
        description=f"Rechercher une réponse via RAG: {question[:80]}",
        tool_calls=[ToolCall(tool_name="rag_fiscal", arguments={"question": question})],
    )


class OllamaClient:
    """Thin wrapper around instructor+OpenAI SDK pointing at Ollama's v1 API.

    Uses the OpenAI-compatible endpoint (http://localhost:11434/v1) which is
    natively supported by Ollama and works reliably with instructor.

    Set force_fallback=True (or FORCE_FALLBACK=true in .env) to bypass Ollama
    entirely — used in tests and offline development.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:1.7b-q4_K_M",
        force_fallback: bool = False,
    ) -> None:
        # Strip trailing slash and append /v1 for the OpenAI-compatible endpoint
        self._base_url = base_url.rstrip("/") + "/v1"
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

    # ── Instructor call (OpenAI SDK) ────────────────────────────────────────────

    def _get_client(self):
        if self._instructor_client is None:
            import instructor
            from openai import OpenAI

            raw = OpenAI(
                base_url=self._base_url,
                api_key="ollama",
            )
            self._instructor_client = instructor.from_openai(raw)
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
        """Check if Ollama is reachable by hitting the /api/tags endpoint."""
        try:
            # Remove /v1 suffix to reach the native Ollama endpoint
            check_url = self._base_url.rsplit("/v1", 1)[0] + "/api/tags"
            r = httpx.get(check_url, timeout=2.0)
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
                subtasks=[_route_subtask(question)],
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