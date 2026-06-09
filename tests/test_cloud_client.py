"""Tests: CloudClient — cloud validation, role routing, deterministic fallback (tests only)."""
from __future__ import annotations

import pytest

from agent.cloud_client import (
    CloudClient,
    CloudModelError,
    _FALLBACK_MARKER,
    _route_subtask,
    create_clients_from_config,
    validate_cloud_model,
)
from agent.config import AgentConfig
from agent.schemas import AgentResult, ExecutionPlan, ReviewResult, TaskRequest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def task() -> TaskRequest:
    return TaskRequest(question="Combien font 2+2?")


@pytest.fixture
def cloud_models() -> dict[str, str]:
    return {
        "supervisor": "glm-5.1:cloud",
        "coder": "qwen3-coder:480b-cloud",
        "researcher": "minimax-m3:cloud",
        "reviewer": "glm-5.1:cloud",
    }


def _client(**overrides) -> CloudClient:
    """Build a CloudClient in fallback mode for tests."""
    defaults = dict(
        role="supervisor",
        models={
            "supervisor": "glm-5.1:cloud",
            "coder": "qwen3-coder:480b-cloud",
            "researcher": "minimax-m3:cloud",
            "reviewer": "glm-5.1:cloud",
        },
        base_url="http://localhost:11434/v1",
        force_fallback=True,
        require_cloud=False,  # tests bypass validation
        api_key="ollama",
    )
    defaults.update(overrides)
    return CloudClient(**defaults)


# ── Cloud validation ─────────────────────────────────────────────────────────

class TestCloudValidation:
    def test_cloud_model_with_colon_suffix_accepted(self):
        validate_cloud_model("glm-5.1:cloud")  # no error

    def test_cloud_model_with_dash_suffix_accepted(self):
        validate_cloud_model("qwen3-coder-480b-cloud")  # no error

    def test_local_model_rejected(self):
        with pytest.raises(ValueError, match="not a cloud model"):
            validate_cloud_model("qwen3:1.7b-q4_K_M")

    def test_local_model_rejected_with_role_info(self):
        with pytest.raises(ValueError, match="supervisor"):
            validate_cloud_model("qwen3:1.7b-q4_K_M", role="supervisor")

    def test_plain_model_name_rejected(self):
        with pytest.raises(ValueError):
            validate_cloud_model("gpt-4")


class TestCloudClientRoleRouting:
    def test_supervisor_uses_supervisor_model(self, cloud_models):
        client = CloudClient(role="supervisor", models=cloud_models, force_fallback=True, require_cloud=False)
        assert client.model == "glm-5.1:cloud"
        assert client.role == "supervisor"

    def test_coder_uses_coder_model(self, cloud_models):
        client = CloudClient(role="coder", models=cloud_models, force_fallback=True, require_cloud=False)
        assert client.model == "qwen3-coder:480b-cloud"

    def test_researcher_uses_researcher_model(self, cloud_models):
        client = CloudClient(role="researcher", models=cloud_models, force_fallback=True, require_cloud=False)
        assert client.model == "minimax-m3:cloud"

    def test_reviewer_uses_reviewer_model(self, cloud_models):
        client = CloudClient(role="reviewer", models=cloud_models, force_fallback=True, require_cloud=False)
        assert client.model == "glm-5.1:cloud"

    def test_unknown_role_raises(self, cloud_models):
        with pytest.raises(ValueError, match="Unknown role"):
            CloudClient(role="planner", models=cloud_models, force_fallback=True, require_cloud=False)

    def test_missing_role_model_raises(self):
        with pytest.raises(ValueError, match="No model configured"):
            CloudClient(role="supervisor", models={"coder": "qwen3-coder:480b-cloud"}, force_fallback=True, require_cloud=False)


class TestCloudClientConstructionValidation:
    def test_cloud_model_accepted_when_required(self, cloud_models):
        client = CloudClient(
            role="supervisor", models=cloud_models,
            force_fallback=True, require_cloud=True,
        )
        assert client.model == "glm-5.1:cloud"

    def test_local_model_rejected_at_construction(self):
        with pytest.raises(ValueError, match="not a cloud model"):
            CloudClient(
                role="supervisor",
                models={"supervisor": "qwen3:1.7b-q4_K_M"},
                force_fallback=True,
                require_cloud=True,
            )

    def test_local_model_accepted_when_validation_disabled(self):
        client = CloudClient(
            role="supervisor",
            models={"supervisor": "qwen3:1.7b-q4_K_M"},
            force_fallback=True,
            require_cloud=False,
        )
        assert client.model == "qwen3:1.7b-q4_K_M"


# ── Deterministic fallback (tests only) ───────────────────────────────────────

class TestFallback:
    def test_fallback_returns_execution_plan(self, task):
        client = _client()
        plan = client.predict([], ExecutionPlan, task=task)
        assert isinstance(plan, ExecutionPlan)
        assert plan.task_id == task.id
        assert len(plan.subtasks) >= 1
        assert _FALLBACK_MARKER in plan.reasoning

    def test_fallback_plan_contains_rag_tool(self):
        client = _client()
        task = TaskRequest(question="Quel est le plafond du quotient familial ?")
        plan = client.predict([], ExecutionPlan, task=task)
        all_tools = [
            call.tool_name
            for subtask in plan.subtasks
            for call in subtask.tool_calls
        ]
        assert "rag_fiscal" in all_tools

    def test_fallback_plan_passes_question(self):
        client = _client()
        task = TaskRequest(question="Quel est le plafond du quotient familial ?")
        plan = client.predict([], ExecutionPlan, task=task)
        args = plan.subtasks[0].tool_calls[0].arguments
        assert args.get("question") == task.question

    def test_fallback_returns_agent_result(self, task):
        client = _client()
        result = client.predict([], AgentResult, task=task)
        assert isinstance(result, AgentResult)
        assert _FALLBACK_MARKER in result.answer

    def test_fallback_returns_review_result(self, task):
        client = _client()
        review = client.predict([], ReviewResult, task=task)
        assert isinstance(review, ReviewResult)
        assert _FALLBACK_MARKER in review.notes

    def test_fallback_plan_routes_bash_keywords(self):
        client = _client()
        task = TaskRequest(question="Fais un ls -la dans le dossier /tmp/")
        plan = client.predict([], ExecutionPlan, task=task)
        tools = [c.tool_name for s in plan.subtasks for c in s.tool_calls]
        assert "execute_bash" in tools

    def test_fallback_plan_routes_edit_keywords(self):
        client = _client()
        task = TaskRequest(question="Crée un fichier hello.txt contenant 'Bonjour'")
        plan = client.predict([], ExecutionPlan, task=task)
        tools = [c.tool_name for s in plan.subtasks for c in s.tool_calls]
        assert "edit_file" in tools

    def test_fallback_plan_routes_delete_keywords(self):
        client = _client()
        task = TaskRequest(question="Supprime le fichier rapport.txt")
        plan = client.predict([], ExecutionPlan, task=task)
        tools = [c.tool_name for s in plan.subtasks for c in s.tool_calls]
        assert "delete_file" in tools


class TestNoSilentFallbackInProduction:
    def test_predict_raises_cloud_error_when_unavailable(self, task):
        """When FORCE_FALLBACK=false and endpoint is unreachable, predict must raise CloudModelError."""
        client = CloudClient(
            role="supervisor",
            models={"supervisor": "glm-5.1:cloud"},
            base_url="http://127.0.0.1:19999/v1",  # unreachable
            force_fallback=False,
            require_cloud=False,
        )
        with pytest.raises(CloudModelError) as exc_info:
            client.predict([], ExecutionPlan, task=task)
        assert exc_info.value.role == "supervisor"
        assert exc_info.value.model == "glm-5.1:cloud"


class TestCreateClientsFromConfig:
    def test_creates_all_roles(self, cloud_models):
        clients = create_clients_from_config(
            models=cloud_models,
            force_fallback=True,
            require_cloud=False,
        )
        assert set(clients.keys()) == {"supervisor", "coder", "researcher", "reviewer"}

    def test_validates_cloud_models_by_default(self):
        with pytest.raises(ValueError, match="not a cloud model"):
            create_clients_from_config(
                models={"supervisor": "local-model"},
                require_cloud=True,
            )

    def test_skips_validation_when_disabled(self):
        clients = create_clients_from_config(
            models={
                "supervisor": "local-model",
                "coder": "local-model",
                "researcher": "local-model",
                "reviewer": "local-model",
            },
            force_fallback=True,
            require_cloud=False,
        )
        assert clients["supervisor"].model == "local-model"


class TestAgentConfig:
    def test_config_loads_env_vars(self):
        cfg = AgentConfig(
            supervisor_model="glm-5.1:cloud",
            coder_model="qwen3-coder:480b-cloud",
            researcher_model="minimax-m3:cloud",
            reviewer_model="glm-5.1:cloud",
        )
        assert cfg.models_by_role == {
            "supervisor": "glm-5.1:cloud",
            "coder": "qwen3-coder:480b-cloud",
            "researcher": "minimax-m3:cloud",
            "reviewer": "glm-5.1:cloud",
        }

    def test_should_validate_cloud_by_default(self):
        cfg = AgentConfig()
        assert cfg.should_validate_cloud is True

    def test_should_validate_cloud_disabled(self):
        cfg = AgentConfig(cloud_validation_disabled=True)
        assert cfg.should_validate_cloud is False

    def test_default_models_are_cloud(self):
        cfg = AgentConfig()
        for role, model in cfg.models_by_role.items():
            assert ":cloud" in model or "-cloud" in model, f"{role}: {model}"