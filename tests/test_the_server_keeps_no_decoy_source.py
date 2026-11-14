"""Catch Python function definitions hidden inside server module string constants."""

from __future__ import annotations

import ast
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1] / "thomas" / "server"


def _module_string_assignments(path: Path) -> list[tuple[list[str], int, str]]:
    """Return module-level string assignments as (names, line, source)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments: list[tuple[list[str], int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = node.value
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
            targets = [node.target]
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        names = [name.id for target in targets for name in ast.walk(target) if isinstance(name, ast.Name)]
        assignments.append((names, node.lineno, value.value))
    return assignments


def _is_decoy_source(text: str) -> bool:
    """True if the string parses as Python containing a function definition."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))


def test_the_detector_tells_decoy_source_from_ordinary_text() -> None:
    decoy = 'async def api_chat(request):\n    return request\napp.router.add_post("/api/chat", api_chat)\n'
    assert _is_decoy_source(decoy)
    for ordinary in (
        "session is already processing another request",
        "SELECT id FROM sessions WHERE id = ?",
        "app[APP_SESSION_LOCKS] = OrderedDict()",
    ):
        assert not _is_decoy_source(ordinary)


def test_no_server_module_keeps_function_source_in_a_string() -> None:
    paths = sorted(_SERVER_ROOT.rglob("*.py"))
    assert len(paths) > 100, "the server scan must cover its Python modules"
    decoys = [
        f"{path.relative_to(_SERVER_ROOT.parent.parent).as_posix()}:{line} {name}"
        for path in paths
        for names, line, text in _module_string_assignments(path)
        if _is_decoy_source(text)
        for name in names
    ]
    assert not decoys, "These strings hold Python that never runs; test the real code instead:\n" + "\n".join(decoys)
