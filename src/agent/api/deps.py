"""FastAPI dependency injection — shared singletons."""
from __future__ import annotations

from agent.cloud_client import CloudClient
from agent.config import get_config
from agent.tools.builtins import build_default_registry
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

_registry: ToolRegistry | None = None
_trace: TraceStore | None = None
_clients: dict[str, CloudClient] | None = None


def get_clients() -> dict[str, CloudClient]:
    """Return cloud clients (created once at app startup via init_clients)."""
    if _clients is None:
        raise RuntimeError("CloudClients not initialized — app lifespan error")
    return _clients


def get_llm() -> CloudClient:
    """Return the supervisor client (backward compat for tests)."""
    return get_clients()["supervisor"]


def get_all_clients() -> dict[str, CloudClient]:
    """Return all role-based cloud clients."""
    return get_clients()


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        cfg = get_config()
        _registry = build_default_registry(rag_api_url=cfg.rag_api_url)
    return _registry


def get_trace() -> TraceStore:
    global _trace
    if _trace is None:
        cfg = get_config()
        _trace = TraceStore(db_path=cfg.trace_db_path)
    return _trace


def init_clients() -> dict[str, CloudClient]:
    """Initialize cloud clients at app startup. Called by FastAPI lifespan.
    
    Idempotent: if _clients is already set (e.g. by tests), return it as-is.
    """
    global _clients
    if _clients is not None:
        return _clients
    from agent.cloud_client import create_clients_from_config
    cfg = get_config()
    _clients = create_clients_from_config(
        models=cfg.models_by_role,
        base_url=cfg.cloud_base_url,
        force_fallback=cfg.force_fallback,
        require_cloud=cfg.should_validate_cloud,
        api_key=cfg.cloud_api_key,
    )
    return _clients


def reset_deps() -> None:
    """Reset all singletons — for testing."""
    global _registry, _trace, _clients
    _registry = None
    _trace = None
    _clients = None