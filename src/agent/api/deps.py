"""Lazy singleton dependencies — overridable via app.dependency_overrides in tests."""
from __future__ import annotations

import os

from agent.config import get_config
from agent.llm import OllamaClient
from agent.tools.builtins import build_default_registry
from agent.tools.registry import ToolRegistry
from agent.trace import TraceStore

_llm: OllamaClient | None = None
_registry: ToolRegistry | None = None
_trace: TraceStore | None = None


def get_llm() -> OllamaClient:
    global _llm
    if _llm is None:
        cfg = get_config()
        _llm = OllamaClient(
            base_url=cfg.ollama_base_url,
            model=cfg.ollama_model,
            force_fallback=cfg.force_fallback,
        )
    return _llm


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
        os.makedirs(os.path.dirname(cfg.trace_db_path) or "data", exist_ok=True)
        _trace = TraceStore(db_path=cfg.trace_db_path)
    return _trace


def reset_deps() -> None:
    """Reset all singletons — call between tests to get a clean state."""
    global _llm, _registry, _trace
    _llm = None
    _registry = None
    _trace = None
