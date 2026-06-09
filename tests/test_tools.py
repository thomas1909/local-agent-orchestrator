"""Tests: tool permissions (risk_level) + tool call logging (inputs/outputs/latency)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent.schemas import RiskLevel, ToolCall
from agent.tools.builtins import (
    _safe_eval,
    calculator,
    delete_file,
    edit_file,
    execute_bash,
    list_files,
    read_file,
    search_text,
)
from agent.tools.registry import ToolRegistry

# ── Helpers ───────────────────────────────────────────────────────────────────

def _simple_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register_tool("low_tool", "A low-risk tool", lambda: "ok", RiskLevel.LOW)
    r.register_tool("medium_tool", "A medium-risk tool", lambda: "ok", RiskLevel.MEDIUM)
    r.register_tool("high_tool", "A HIGH-risk tool", lambda: "danger", RiskLevel.HIGH)
    return r


# ── Permissions / risk_level ──────────────────────────────────────────────────

def test_tool_risk_levels_are_assigned():
    r = _simple_registry()
    assert r.get_risk("low_tool") == RiskLevel.LOW
    assert r.get_risk("medium_tool") == RiskLevel.MEDIUM
    assert r.get_risk("high_tool") == RiskLevel.HIGH


def test_default_registry_risk_levels(default_registry):
    assert default_registry.get_risk("list_files") == RiskLevel.LOW
    assert default_registry.get_risk("read_file") == RiskLevel.LOW
    assert default_registry.get_risk("search_text") == RiskLevel.LOW
    assert default_registry.get_risk("calculator") == RiskLevel.LOW
    assert default_registry.get_risk("edit_file") == RiskLevel.LOW
    assert default_registry.get_risk("rag_fiscal") == RiskLevel.MEDIUM
    assert default_registry.get_risk("execute_bash") == RiskLevel.HIGH
    assert default_registry.get_risk("delete_file") == RiskLevel.HIGH


def test_unknown_tool_has_no_risk():
    r = ToolRegistry()
    with pytest.raises(KeyError):
        r.get_risk("ghost_tool")


def test_has_tool():
    r = _simple_registry()
    assert r.has_tool("low_tool")
    assert not r.has_tool("nonexistent")


def test_list_tools_returns_all(default_registry):
    names = {t["name"] for t in default_registry.list_tools()}
    assert names == {
        "list_files", "read_file", "search_text", "calculator",
        "rag_fiscal", "edit_file", "execute_bash", "delete_file",
    }


# ── Tool call logging (inputs / outputs / latency) ────────────────────────────

def test_execute_captures_inputs_and_output():
    r = ToolRegistry()
    r.register_tool("echo", "echo", lambda msg: f"echo:{msg}", RiskLevel.LOW)

    call = ToolCall(tool_name="echo", arguments={"msg": "hello"})
    result = r.execute(call)

    assert result.tool_name == "echo"
    assert result.arguments == {"msg": "hello"}
    assert result.output == "echo:hello"
    assert result.error is None


def test_execute_captures_latency():
    r = ToolRegistry()
    r.register_tool("slow", "slow", lambda: "done", RiskLevel.LOW)

    result = r.execute(ToolCall(tool_name="slow"))
    assert result.latency_ms >= 0


def test_execute_captures_error():
    def _boom():
        raise RuntimeError("exploded")

    r = ToolRegistry()
    r.register_tool("boom", "boom", _boom, RiskLevel.LOW)

    result = r.execute(ToolCall(tool_name="boom"))
    assert result.error == "exploded"
    assert result.output == ""
    assert result.latency_ms >= 0


def test_execute_unknown_tool_returns_error():
    r = ToolRegistry()
    result = r.execute(ToolCall(tool_name="ghost"))
    assert result.error is not None
    assert "ghost" in result.error


# ── Built-in tool correctness ─────────────────────────────────────────────────

def test_calculator_basic():
    assert calculator("2 + 2") == "4"
    assert calculator("10 / 4") == "2.5"
    assert calculator("2 ** 8") == "256"


def test_calculator_no_eval_injection():
    result = calculator("__import__('os').system('echo pwned')")
    assert "Erreur" in result


def test_safe_eval_raises_on_function_call():
    with pytest.raises(ValueError):
        _safe_eval("abs(-1)")


def test_list_files_missing_path():
    result = list_files("/nonexistent_path_xyz_123")
    assert "not found" in result


def test_list_files_on_dir():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "a.txt").write_text("x")
        Path(tmp, "b.txt").write_text("y")
        result = list_files(tmp)
        assert "a.txt" in result
        assert "b.txt" in result


def test_read_file_missing():
    result = read_file("/nonexistent_xyz_abc.txt")
    assert "not found" in result.lower()


def test_read_file_content():
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("bonjour")
        name = f.name
    assert read_file(name) == "bonjour"


def test_search_text_found():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "f.txt").write_text("Le plafond est de 1807 euros\nAutre ligne")
        result = search_text("plafond", tmp)
        assert "plafond" in result.lower()
        assert "f.txt" in result


def test_search_text_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "f.txt").write_text("rien ici")
        result = search_text("zzz_missing", tmp)
        assert "No matches" in result


# ── HIGH-risk demo tool (sandboxed) ───────────────────────────────────────────

def test_delete_file_is_sandboxed():
    """delete_file must never touch the disk — even a real path is left intact."""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("keep me")
        name = f.name
    result = delete_file(name)
    assert "simulée" in result.lower()
    assert Path(name).exists(), "delete_file must NOT actually remove the file"
    assert read_file(name) == "keep me"


# ── edit_file (LOW risk) ──────────────────────────────────────────────────────

def test_edit_file_creates_new_file():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, "new.txt")
        result = edit_file(str(target), "bonjour")
        assert "Fichier écrit" in result
        assert target.read_text() == "bonjour"


def test_edit_file_overwrites_existing():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, "existing.txt")
        target.write_text("old content", encoding="utf-8")
        result = edit_file(str(target), "new content")
        assert "Fichier écrit" in result
        assert target.read_text() == "new content"


def test_edit_file_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, "sub", "dir", "deep.txt")
        result = edit_file(str(target), "deep write")
        assert "Fichier écrit" in result
        assert target.read_text() == "deep write"


def test_edit_file_reports_character_count():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, "count.txt")
        content = "a" * 42
        result = edit_file(str(target), content)
        assert "42 caractères" in result


# ── execute_bash (HIGH risk, sandboxed) ────────────────────────────────────────

def test_execute_bash_is_sandboxed():
    """execute_bash must never run a real command — returns simulated output."""
    result = execute_bash("rm -rf /", timeout=5)
    assert "simulé" in result.lower()
    assert "rm -rf /" in result
    assert "timeout=5s" in result


def test_execute_bash_risk_is_high(default_registry):
    assert default_registry.get_risk("execute_bash") == RiskLevel.HIGH


def test_edit_file_risk_is_low(default_registry):
    assert default_registry.get_risk("edit_file") == RiskLevel.LOW
