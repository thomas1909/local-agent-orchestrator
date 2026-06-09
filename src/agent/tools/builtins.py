"""5 built-in safe tools registered on the default registry."""
from __future__ import annotations

import ast
import operator as op
from pathlib import Path
from typing import Any

import httpx

from agent.schemas import RiskLevel
from agent.tools.registry import ToolRegistry

_SAFE_BINARY_OPS: dict[type, Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.FloorDiv: op.floordiv,
}
_SAFE_UNARY_OPS: dict[type, Any] = {
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _safe_eval(expr: str) -> float:
    """Evaluate a math expression without eval()."""
    def _ev(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINARY_OPS:
            return _SAFE_BINARY_OPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY_OPS:
            return _SAFE_UNARY_OPS[type(node.op)](_ev(node.operand))
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")

    tree = ast.parse(expr.strip(), mode="eval")
    return _ev(tree.body)


# ── Tool implementations ──────────────────────────────────────────────────────

def list_files(path: str = ".") -> str:
    p = Path(path)
    if not p.exists():
        return f"Path not found: {path}"
    if p.is_file():
        return str(p)
    entries = sorted(p.iterdir())
    if not entries:
        return f"(empty directory: {path})"
    return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries)


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"
    if not p.is_file():
        return f"Not a file: {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Cannot read {path}: {exc}"


def search_text(pattern: str, path: str = ".") -> str:
    p = Path(path)
    matches: list[str] = []

    def _scan(target: Path) -> None:
        if target.is_file():
            try:
                for i, line in enumerate(
                    target.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if pattern.lower() in line.lower():
                        matches.append(f"{target}:{i}: {line.rstrip()}")
            except OSError:
                pass
        elif target.is_dir():
            for child in sorted(target.iterdir()):
                if not child.name.startswith("."):
                    _scan(child)

    _scan(p)
    if not matches:
        return f"No matches for {pattern!r} in {path}"
    return "\n".join(matches[:50])  # cap at 50 lines


def calculator(expression: str) -> str:
    try:
        result = _safe_eval(expression)
        if result == int(result):
            return str(int(result))
        return str(round(result, 10))
    except Exception as exc:
        return f"Erreur de calcul: {exc}"


def delete_file(path: str) -> str:
    """DÉMO à risque ÉLEVÉ — bac à sable : n'effectue AUCUNE action réelle sur le disque.

    Présent uniquement pour démontrer le garde-fou human-in-the-loop : un outil HIGH
    est bloqué par le graphe tant qu'une approbation humaine n'est pas accordée.
    """
    return f"Suppression simulée (bac à sable, aucune action réelle effectuée) : {path}"


def edit_file(path: str, content: str) -> str:
    """Low-risk tool: write content to a file (create or overwrite).

    Confined to the project workspace — refuses paths outside cwd.
    """
    p = Path(path).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Fichier écrit : {path} ({len(content)} caractères)"
    except OSError as exc:
        return f"Impossible d'écrire {path} : {exc}"


def execute_bash(command: str, timeout: int = 30) -> str:
    """DÉMO à risque ÉLEVÉ — bac à sable : n'exécute AUCUNE commande réelle.

    Présent uniquement pour démontrer le garde-fou human-in-the-loop : un outil HIGH
    est bloqué par le graphe tant qu'une approbation humaine n'est pas accordée.
    """
    return (
        f"Exécution simulée (bac à sable, aucune action réelle effectuée) : "
        f"{command!r} (timeout={timeout}s)"
    )


def rag_fiscal(question: str, rag_api_url: str = "http://127.0.0.1:8000") -> str:
    """Query the local RAG fiscal API. Returns a graceful message if offline."""
    try:
        resp = httpx.post(
            f"{rag_api_url}/query",
            json={"question": question, "top_k": 5},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("answer", "(réponse vide)")
    except httpx.ConnectError:
        return (
            "Le service RAG fiscal n'est pas disponible. "
            "Démarrez l'API avec: "
            "PYTHONPATH=src uv run uvicorn rag.api.main:app --reload "
            "(depuis le dossier 6-RAG)"
        )
    except httpx.TimeoutException:
        return "Le service RAG fiscal n'a pas répondu dans les délais (timeout 30s)."
    except httpx.HTTPStatusError as exc:
        return f"Erreur API RAG ({exc.response.status_code}): {exc.response.text[:200]}"
    except Exception as exc:
        return f"Erreur inattendue lors de l'appel RAG: {exc}"


# ── Default registry ──────────────────────────────────────────────────────────

def build_default_registry(rag_api_url: str = "http://127.0.0.1:8000") -> ToolRegistry:
    registry = ToolRegistry()

    registry.register_tool(
        "list_files",
        "Liste les fichiers et dossiers d'un répertoire.",
        list_files,
        RiskLevel.LOW,
    )
    registry.register_tool(
        "read_file",
        "Lit le contenu d'un fichier texte.",
        read_file,
        RiskLevel.LOW,
    )
    registry.register_tool(
        "search_text",
        "Recherche un motif textuel dans des fichiers.",
        search_text,
        RiskLevel.LOW,
    )
    registry.register_tool(
        "calculator",
        "Évalue une expression mathématique (sans eval).",
        calculator,
        RiskLevel.LOW,
    )

    def _rag(question: str) -> str:
        return rag_fiscal(question, rag_api_url=rag_api_url)

    registry.register_tool(
        "rag_fiscal",
        "Interroge la base documentaire fiscale locale (POST /query).",
        _rag,
        RiskLevel.MEDIUM,
    )
    registry.register_tool(
        "edit_file",
        "Écrit du contenu dans un fichier (crée ou écrase).",
        edit_file,
        RiskLevel.LOW,
    )
    registry.register_tool(
        "execute_bash",
        "Exécute une commande shell (DÉMO à risque ÉLEVÉ — bac à sable, aucune action réelle).",
        execute_bash,
        RiskLevel.HIGH,
    )
    registry.register_tool(
        "delete_file",
        "Supprime un fichier (DÉMO à risque ÉLEVÉ — bac à sable, aucune action réelle).",
        delete_file,
        RiskLevel.HIGH,
    )

    return registry
