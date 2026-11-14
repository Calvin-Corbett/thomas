"""An extraction refactor must not read as newly-introduced exception debt.

The ratchet forgives a pure rename (R100), but an EXTRACTION is not a rename to
git: a new module holding a subset of another file is an add, so every broad
handler inside it was reported as newly written. That blind spot has already bent
two refactors in this repo:

- the worker.py split narrowed three `except Exception:` handlers purely to get
  past the gate, and the CHANGELOG records the correction: "the commit's own
  move-only, no logic edits description overstated it";
- another agent left `_from_iso` behind rather than move it, writing "its broad
  handler would be flagged as new in the new module and narrowing it would be a
  substantive change I did not make".

Both times the gate pushed a refactor toward a change nobody wanted. Phase 0a of
the Praxis plan is nothing but extractions, so this had to be fixed before it
distorted a third one.

The discrimination matters as much as the forgiveness: a handler whose BODY
changed on the way across is not a move, and must still be flagged.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "exception_handler_gate", _REPO / "scripts/forge/gates/exception_handler_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _load()

ORIGINAL = """
def resolve():
    try:
        do_work()
    except Exception as e:  # REVIEWED: optional, non-fatal
        log.warning("Runtime skills resolution failed: %s", e)
        payload["error"] = f"{type(e).__name__}: {e}"
"""

# The same handler after extraction: new module, renamed alias, reworded comment.
MOVED = """
def resolve():
    try:
        do_work()
    except Exception as exc:  # REVIEWED: plugin failures are non-fatal
        log.warning("Runtime skills resolution failed: %s", exc)
        payload["error"] = f"{type(exc).__name__}: {exc}"
"""

# Same shape, but the body gained a statement. Not a move.
MODIFIED = """
def resolve():
    try:
        do_work()
    except Exception as exc:
        log.warning("Runtime skills resolution failed: %s", exc)
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return None
"""


def _only_handler(source: str) -> ast.ExceptHandler:
    return next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ExceptHandler))


def test_renaming_the_bound_exception_does_not_change_the_signature() -> None:
    """`except Exception as e` -> `as exc` is what every extraction does."""
    assert gate._handler_signature(_only_handler(ORIGINAL)) == gate._handler_signature(_only_handler(MOVED))


def test_a_reworded_comment_does_not_change_the_signature() -> None:
    """Comments are not in the AST; this pins that the fingerprint ignores them."""
    assert "REVIEWED: optional, non-fatal" in ORIGINAL
    assert "REVIEWED: plugin failures are non-fatal" in MOVED

    assert gate._handler_signature(_only_handler(ORIGINAL)) == gate._handler_signature(_only_handler(MOVED))


def test_an_added_statement_does_change_the_signature() -> None:
    """A handler that gained behaviour on the way across is not a move."""
    assert gate._handler_signature(_only_handler(ORIGINAL)) != gate._handler_signature(_only_handler(MODIFIED))


def test_a_different_caught_type_does_change_the_signature() -> None:
    narrowed = MOVED.replace("except Exception as exc", "except ValueError as exc")

    assert gate._handler_signature(_only_handler(MOVED)) != gate._handler_signature(_only_handler(narrowed))


def test_the_removal_budget_forgives_a_move_exactly_once() -> None:
    """Two copies where one was deleted is a duplication: only one is forgiven."""
    removed = gate._broad_handler_signatures(ORIGINAL) - gate._broad_handler_signatures("")
    signature = gate._handler_signature(_only_handler(MOVED))

    assert removed[signature] == 1

    removed[signature] -= 1
    assert removed[signature] == 0, "the second copy has no budget left and stays flagged"


def test_signatures_are_found_by_line_for_the_flagging_path() -> None:
    by_line = gate._broad_handlers_by_line(MOVED)

    assert len(by_line) == 1
    line, signature = next(iter(by_line.items()))
    assert MOVED.splitlines()[line - 1].strip().startswith("except Exception as exc")
    assert signature == gate._handler_signature(_only_handler(MOVED))


def test_a_narrow_handler_is_not_tracked_at_all() -> None:
    """Only BROAD handlers carry signatures; the rest are none of this gate's business."""
    narrow = "try:\n    x()\nexcept ValueError as exc:\n    log.warning('%s', exc)\n"

    assert gate._broad_handler_signatures(narrow) == gate.Counter()
    assert gate._broad_handlers_by_line(narrow) == {}


def test_unparseable_source_is_not_treated_as_empty_evidence() -> None:
    """A syntax error must not silently grant or spend move budget."""
    assert gate._broad_handler_signatures("def broken(:\n") == gate.Counter()
    assert gate._broad_handlers_by_line("def broken(:\n") == {}
