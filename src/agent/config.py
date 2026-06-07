from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b-q4_K_M"
    rag_api_url: str = "http://127.0.0.1:8000"
    trace_db_path: str = "data/traces.db"
    force_fallback: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_config: AgentConfig | None = None


def get_config() -> AgentConfig:
    global _config
    if _config is None:
        _config = AgentConfig()
    return _config
