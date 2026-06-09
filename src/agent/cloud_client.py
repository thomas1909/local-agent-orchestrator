"""CloudClient — OpenAI SDK + Instructor structured outputs with role-based cloud model routing.

All LLM calls go through cloud models (suffix :cloud or -cloud).
No local models, no silent fallback, no ollama Python client.

The deterministic fallback exists ONLY for unit tests (FORCE_FALLBACK=true).
In production, a cloud model failure raises CloudModelError — never silently degrades.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import TypeVar

import httpx
from pydantic import BaseModel

from agent.schemas import AgentResult, ExecutionPlan, ReviewResult, SubTask, TaskRequest, ToolCall

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ── Exception ──────────────────────────────────────────────────────────────────

class CloudModelError(RuntimeError):
    """Raised when a cloud model call fails in production (FORCE_FALLBACK=false)."""

    def __init__(self, role: str, model: str, base_url: str, detail: str) -> None:
        self.role = role
        self.model = model
        self.base_url = base_url
        self.detail = detail
        super().__init__(
            f"CloudModelError [{role}] model={model!r} base_url={base_url!r}: {detail}"
        )


# ── Cloud validation ────────────────────────────────────────────────────────────

_CLOUD_SUFFIXES = (":cloud", "-cloud")


def validate_cloud_model(model: str, role: str = "") -> None:
    """Raise ValueError if model name does not contain a cloud suffix."""
    if not any(s in model for s in _CLOUD_SUFFIXES):
        label = f" for role {role!r}" if role else ""
        raise ValueError(
            f"Model {model!r}{label} is not a cloud model. "
            f"Expected suffix one of {_CLOUD_SUFFIXES}. "
            "Set REQUIRE_CLOUD_MODELS=false or CLOUD_VALIDATION_DISABLED=true to bypass."
        )


# ── Role → model mapping ────────────────────────────────────────────────────────

ROLE_MODEL_MAP: dict[str, str] = {
    "supervisor": "SUPERVISOR_MODEL",
    "coder": "CODER_MODEL",
    "researcher": "RESEARCHER_MODEL",
    "reviewer": "REVIEWER_MODEL",
}


def resolve_model(role: str, models: dict[str, str]) -> str:
    """Return the model name for a given role from the models dict."""
    env_key = ROLE_MODEL_MAP.get(role)
    if env_key is None:
        raise ValueError(f"Unknown role {role!r}. Expected one of {list(ROLE_MODEL_MAP)}")
    model = models.get(role)
    if not model:
        raise ValueError(f"No model configured for role {role!r}")
    return model


# ── Deterministic fallback (tests only) ─────────────────────────────────────────

_FALLBACK_MARKER = "[Mode hors-ligne]"

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
    """Deterministic keyword routing for test-only fallback planner."""
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


# ── CloudClient ─────────────────────────────────────────────────────────────────

class CloudClient:
    """LLM client using OpenAI SDK + Instructor, backed by cloud models only.

    Each instance is bound to a role (supervisor/coder/researcher/reviewer) and
    resolves its model from the models dict at construction time.

    Parameters
    ----------
    role : str
        Agent role — determines which model is used.
    models : dict[str, str]
        Mapping role → cloud model name (e.g. {"supervisor": "glm-5.1:cloud"}).
    base_url : str
        OpenAI-compatible endpoint (e.g. http://localhost:11434/v1).
    force_fallback : bool
        When True, skip all LLM calls and use deterministic fallback (tests only).
    require_cloud : bool
        When True, validate that every model name contains :cloud or -cloud.
    api_key : str
        API key for the OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        role: str = "supervisor",
        models: dict[str, str] | None = None,
        base_url: str = "http://localhost:11434/v1",
        force_fallback: bool = False,
        require_cloud: bool = True,
        api_key: str = "ollama",
    ) -> None:
        self._role = role
        self._models = models or {"supervisor": "glm-5.1:cloud"}
        self._base_url = base_url.rstrip("/")
        self._force_fallback = force_fallback
        self._require_cloud = require_cloud
        self._api_key = api_key
        self._instructor_client = None

        # Resolve model for this role
        self._model = resolve_model(role, self._models)

        # Validate cloud suffix
        if self._require_cloud:
            validate_cloud_model(self._model, role)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def role(self) -> str:
        return self._role

    @property
    def model(self) -> str:
        return self._model

    def predict(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        task: TaskRequest | None = None,
    ) -> T:
        """Return a structured Pydantic response from the cloud model.

        If force_fallback is True, returns a deterministic stub (tests only).
        In production, a cloud model failure raises CloudModelError.
        """
        if self._force_fallback:
            return self._deterministic_fallback(response_model, task)

        if not self._is_available():
            raise CloudModelError(
                role=self._role,
                model=self._model,
                base_url=self._base_url,
                detail="Cloud endpoint is unreachable",
            )

        try:
            return self._instructor_predict(messages, response_model)
        except Exception as exc:
            logger.warning(
                "CloudModelError [%s] model=%s base_url=%s: %s",
                self._role, self._model, self._base_url, exc,
            )
            raise CloudModelError(
                role=self._role,
                model=self._model,
                base_url=self._base_url,
                detail=str(exc),
            ) from exc

    def is_fallback_mode(self) -> bool:
        """True when running in deterministic test mode (force_fallback=True)."""
        return self._force_fallback

    def cloud_models_status(self) -> dict[str, str]:
        """Return the full role→model mapping for the health endpoint."""
        return dict(self._models)

    # ── Instructor call (OpenAI SDK) ────────────────────────────────────────────

    def _get_client(self):
        if self._instructor_client is None:
            import instructor
            from openai import OpenAI

            raw = OpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
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
        """Check if the OpenAI-compatible endpoint is reachable."""
        try:
            # The health check goes to the native Ollama endpoint (without /v1)
            check_url = self._base_url.replace("/v1", "/api/tags") if "/v1" in self._base_url else self._base_url + "/api/tags"
            r = httpx.get(check_url, timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    # ── Deterministic fallback (tests only) ──────────────────────────────────────

    def _deterministic_fallback(self, response_model: type[T], task: TaskRequest | None) -> T:
        task_id = task.id if task else str(uuid.uuid4())
        question = task.question if task else ""

        if response_model is ExecutionPlan:
            return response_model(  # type: ignore[return-value]
                task_id=task_id,
                subtasks=[_route_subtask(question)],
                reasoning=f"{_FALLBACK_MARKER} Plan déterministe (mode test, cloud désactivé)",
            )

        if response_model is AgentResult:
            return response_model(  # type: ignore[return-value]
                task_id=task_id,
                answer=f"{_FALLBACK_MARKER} Mode test — cloud désactivé. Activez Ollama Cloud et relancez.",
            )

        if response_model is ReviewResult:
            return response_model(  # type: ignore[return-value]
                task_id=task_id,
                verdict="approved",
                notes=f"{_FALLBACK_MARKER} Revue automatique (mode test)",
            )

        # Generic fallback
        try:
            return response_model(task_id=task_id)  # type: ignore[call-arg,return-value]
        except Exception:
            return response_model()  # type: ignore[call-arg,return-value]


# ── Convenience factory ────────────────────────────────────────────────────────

def create_clients_from_config(
    models: dict[str, str],
    base_url: str = "http://localhost:11434/v1",
    force_fallback: bool = False,
    require_cloud: bool = True,
    api_key: str = "ollama",
) -> dict[str, CloudClient]:
    """Create a CloudClient for each role. Validates cloud suffixes upfront."""
    clients: dict[str, CloudClient] = {}
    for role in ROLE_MODEL_MAP:
        clients[role] = CloudClient(
            role=role,
            models=models,
            base_url=base_url,
            force_fallback=force_fallback,
            require_cloud=require_cloud,
            api_key=api_key,
        )
    return clients