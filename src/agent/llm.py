"""Backward-compatibility re-exports — CloudClient replaces OllamaClient.

All new code should import from agent.cloud_client directly.
This module re-exports CloudClient as OllamaClient so that any lingering
import paths still resolve.
"""
from agent.cloud_client import (  # noqa: F401
    CloudClient,
    CloudModelError,
    _FALLBACK_MARKER,
    create_clients_from_config,
    validate_cloud_model,
)

# Backward-compat alias for tests that import OllamaClient
OllamaClient = CloudClient