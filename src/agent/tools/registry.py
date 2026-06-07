"""ToolRegistry — register, introspect, and execute tools with risk-level gating."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from agent.schemas import RiskLevel, ToolCall, ToolResult


@dataclass
class ToolDefinition:
    name: str
    description: str
    risk_level: RiskLevel
    fn: Callable[..., str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        description: str,
        fn: Callable[..., str],
        risk_level: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name, description=description, risk_level=risk_level, fn=fn
        )

    def tool(
        self,
        name: str,
        description: str,
        risk_level: RiskLevel = RiskLevel.LOW,
    ) -> Callable[[Callable[..., str]], Callable[..., str]]:
        """Decorator form: @registry.tool("name", "desc", RiskLevel.LOW)."""
        def decorator(fn: Callable[..., str]) -> Callable[..., str]:
            self.register_tool(name, description, fn, risk_level)
            return fn
        return decorator

    # ── Introspection ─────────────────────────────────────────────────────────

    def get_risk(self, tool_name: str) -> RiskLevel:
        return self._tools[tool_name].risk_level

    def list_tools(self) -> list[dict[str, str]]:
        return [
            {"name": t.name, "description": t.description, "risk_level": t.risk_level.value}
            for t in self._tools.values()
        ]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(self, call: ToolCall) -> ToolResult:
        if call.tool_name not in self._tools:
            return ToolResult(
                tool_name=call.tool_name,
                arguments=call.arguments,
                output="",
                error=f"Unknown tool: {call.tool_name!r}",
            )
        t0 = time.monotonic()
        tool = self._tools[call.tool_name]
        try:
            output = tool.fn(**call.arguments)
        except Exception as exc:
            return ToolResult(
                tool_name=call.tool_name,
                arguments=call.arguments,
                output="",
                error=str(exc),
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        return ToolResult(
            tool_name=call.tool_name,
            arguments=call.arguments,
            output=str(output),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    # ── Schema for LLM ────────────────────────────────────────────────────────

    def schema_for_llm(self) -> str:
        lines = ["Available tools:"]
        for t in self._tools.values():
            lines.append(f"  - {t.name} [{t.risk_level.value}]: {t.description}")
        return "\n".join(lines)
