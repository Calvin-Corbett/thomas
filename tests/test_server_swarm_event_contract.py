"""RETIRED 2026-07-28: pins that the legacy V1 chat engine stays unwired.

What used to be here: one test that sabotaged Chat V2 registration with
``RuntimeError("legacy-chat-required")`` and asserted the run_id/seq/usage
contract of the ndjson stream a legacy V1 ``/api/chat`` would have produced. It
had been failing with 404, because no such route is ever registered.

The removal of that fallback was deliberate, and this file now proves it rather
than contradicting it. ``register_chat_routes`` still exists for isolated
compatibility apps, but nothing in ``thomas/`` calls it, and the production
server documents that it passes ``register_primary_chat=False``. If someone
wires it back into the live app, ``/api/chat`` would gain a second, shadowed
handler running a parallel agent engine -- these assertions fail first.

Both checks used to be line-oriented text scans: a commented-out
``# register_chat_routes(app)`` would have FAILED the first one, and
``register_chat_routes (app)`` would have passed it. They read the syntax
tree with ``ast`` now -- a call is a Call node, not a spelling.

See ``tests/test_server_chat_endpoint_registration.py`` for what the live
endpoint actually guarantees, in both the healthy and the failed direction.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_THOMAS_ROOT = Path(__file__).resolve().parents[1] / "thomas"


def _python_sources() -> list[Path]:
    return sorted(p for p in _THOMAS_ROOT.rglob("*.py") if p.is_file())


def _called_name(node: ast.Call) -> str | None:
    """The bare name being called, for ``f()`` and for ``mod.f()`` alike."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _calls_in(path: Path) -> list[ast.Call]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (SyntaxError, ValueError):
        return []
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


class TestLegacyPrimaryChatStaysRetired(unittest.TestCase):
    def test_nothing_in_thomas_calls_register_chat_routes(self):
        callers: list[str] = []
        for path in _python_sources():
            for call in _calls_in(path):
                if _called_name(call) == "register_chat_routes":
                    rel = path.relative_to(_THOMAS_ROOT.parent).as_posix()
                    callers.append(f"{rel}:{call.lineno}")
        self.assertEqual(
            callers,
            [],
            "the legacy V1 chat engine must stay unwired; Chat V2 owns POST /api/chat",
        )

    def test_chat_v2_registration_is_the_only_live_api_chat_registrar(self):
        registrars: list[str] = []
        for path in _python_sources():
            for call in _calls_in(path):
                if _called_name(call) != "add_post" or not call.args:
                    continue
                target = call.args[0]
                if isinstance(target, ast.Constant) and target.value == "/api/chat":
                    registrars.append(path.relative_to(_THOMAS_ROOT.parent).as_posix())
        # chat_v2_registration.py registers it for real, and
        # app_routes_init.py claims it with the 503 sentinel when V2 fails.
        # The legacy handler that once held a third line is deleted.
        #
        # chat_aiohttp.py used to appear in this list as well: it carried the
        # "/api/chat" text inside the _SOURCE_COMPAT_API_CHAT documentation
        # string literal, matching the old text scan without registering
        # anything. Reading calls rather than lines is why a documentation
        # string can no longer put a file on this list at all.
        self.assertEqual(
            sorted(set(registrars)),
            [
                "thomas/server/app_routes_init.py",
                "thomas/server/routes/chat_v2_registration.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
