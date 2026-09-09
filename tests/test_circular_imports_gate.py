"""The circular-import gate must read imports, not mentions.

A regex over the raw source once added every quoted string beginning
"thomas." to the import set. It could not tell a module name from an import,
so `if "thomas.server" in str(row.get("command"))` -- a substring test against
a process command line in thomas/core/agent_presence.py -- was reported as
thomas.core importing thomas.server. That is a forbidden pair, so the gate
refused every change to that file, returning the same verdict before and after
any edit. A gate that cannot tell an edit from no edit is not measuring the edit.

These tests pin both halves: every real import form is still caught, and a name
appearing only inside a string is not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_GATE = _ROOT / "scripts" / "forge" / "gates" / "circular_imports_gate.py"
_spec = importlib.util.spec_from_file_location("circular_imports_gate_under_test", _GATE)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
extract = _mod._extract_thomas_imports


def test_every_real_import_form_is_still_caught() -> None:
    """Removing the regex must not blind the gate to an actual import."""
    assert extract("from thomas.server import app") == {"thomas.server"}
    assert extract("from thomas.server.routes import work") == {"thomas.server"}
    assert extract("import thomas.server") == {"thomas.server"}
    assert extract("import thomas.server.routes as r") == {"thomas.server"}
    assert extract('import importlib\nimportlib.import_module("thomas.server")') == {"thomas.server"}
    assert extract('from importlib import import_module\nimport_module("thomas.server")') == {"thomas.server"}
    # Deferred inside a function, and guarded by TYPE_CHECKING, both still count.
    assert extract("def f():\n    from thomas.server import app\n") == {"thomas.server"}
    assert extract("if TYPE_CHECKING:\n    from thomas.server import app\n") == {"thomas.server"}


def test_a_module_named_only_inside_a_string_is_not_an_import() -> None:
    """The real line from agent_presence.py that made the file uneditable."""
    assert extract('if "thomas.server" in str(row.get("command")):\n    pass\n') == set()
    assert extract('CMD = "-m thomas.server"\n') == set()
    assert extract('LABELS = {"thomas.server": "web"}\n') == set()
    assert extract('print(f"starting thomas.server now")\n') == set()


def test_the_file_that_exposed_this_is_clean() -> None:
    """thomas/core/agent_presence.py imports no server module by any route."""
    src = (_ROOT / "thomas" / "core" / "agent_presence.py").read_text(encoding="utf-8")
    assert "thomas.server" not in extract(src)


def test_unparseable_source_does_not_raise() -> None:
    """A file that cannot be parsed is caught by the syntax checks that run
    before this gate, not judged by it; this pins only that it does not blow up."""
    assert extract("def broken(:\n") == set()
