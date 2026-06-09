"""Cloud-only agent configuration — multi-model role routing."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    """All runtime knobs are read from environment variables or a .env file.

    Every model must be a cloud model (suffix :cloud or -cloud) when
    REQUIRE_CLOUD_MODELS is true (the default).  Set FORCE_FALLBACK=true
    only for unit tests — in production, a cloud model failure raises
    CloudModelError, never silently degrades.
    """

    # ── Cloud endpoint ────────────────────────────────────────────────────────
    cloud_base_url: str = "http://localhost:11434/v1"
    cloud_api_key: str = "ollama"

    # ── Role-based cloud models ───────────────────────────────────────────────
    supervisor_model: str = "glm-5.1:cloud"
    coder_model: str = "qwen3-coder:480b-cloud"
    researcher_model: str = "minimax-m3:cloud"
    reviewer_model: str = "glm-5.1:cloud"

    # ── Validation ────────────────────────────────────────────────────────────
    require_cloud_models: bool = True
    cloud_validation_disabled: bool = False

    # ── Test-only fallback ────────────────────────────────────────────────────
    force_fallback: bool = False

    # ── Services ──────────────────────────────────────────────────────────────
    rag_api_url: str = "http://127.0.0.1:8000"
    trace_db_path: str = "data/traces.db"
    agent_port: int = 8100

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def models_by_role(self) -> dict[str, str]:
        """Return {role: model_name} for all four agent roles."""
        return {
            "supervisor": self.supervisor_model,
            "coder": self.coder_model,
            "researcher": self.researcher_model,
            "reviewer": self.reviewer_model,
        }

    @property
    def should_validate_cloud(self) -> bool:
        """True when cloud model suffix validation is active."""
        return self.require_cloud_models and not self.cloud_validation_disabled


_config: AgentConfig | None = None


def get_config() -> AgentConfig:
    global _config
    if _config is None:
        _config = AgentConfig()
    return _config