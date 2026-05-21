from __future__ import annotations

import ast
from pathlib import Path

CLI_MAIN_PATH = Path(__file__).resolve().parents[1] / "thomas" / "cli" / "main.py"


def _load_cli_main_tree() -> ast.Module:
    source = CLI_MAIN_PATH.read_text(encoding="utf-8-sig")
    return ast.parse(source, filename=str(CLI_MAIN_PATH))


def _iter_function_defs(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _is_models_command_decorator(decorator: ast.expr) -> bool:
    target: ast.expr
    if isinstance(decorator, ast.Call):
        target = decorator.func
    else:
        target = decorator
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "models"
        and target.attr == "command"
    )


def _models_command_callbacks(tree: ast.Module) -> set[str]:
    callbacks: set[str] = set()
    for fn in _iter_function_defs(tree):
        if any(_is_models_command_decorator(deco) for deco in fn.decorator_list):
            callbacks.add(fn.name)
    return callbacks


def _find_function(tree: ast.Module, fn_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for fn in _iter_function_defs(tree):
        if fn.name == fn_name:
            return fn
    return None


def _called_symbol_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    called: set[str] = set()
    for stmt in fn.body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    return called


def test_models_scan_uses_shared_helper_and_avoids_models_callback_calls() -> None:
    tree = _load_cli_main_tree()
    models_callbacks = _models_command_callbacks(tree)
    assert "models_scan" in models_callbacks, (
        "Guard precondition failed: models_scan is no longer registered as a @models.command callback. "
        "Update this test if models CLI registration changed."
    )

    scan_fn = _find_function(tree, "models_scan")
    assert scan_fn is not None, "Could not find models_scan in thomas/cli/main.py."

    called_names = _called_symbol_names(scan_fn)
    assert "_run_models_discover" in called_names, (
        "models_scan must delegate to _run_models_discover(...), the shared discovery helper."
    )

    disallowed_callbacks = (models_callbacks - {"models_scan"}) | {"models_discover"}
    direct_callback_calls = sorted(name for name in called_names if name in disallowed_callbacks)
    assert not direct_callback_calls, (
        "models_scan must not directly call another @models.command callback. "
        f"Found direct callback call(s): {', '.join(direct_callback_calls)}. "
        "Route through _run_models_discover(...) instead."
    )
