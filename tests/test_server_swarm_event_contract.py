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

See ``tests/test_server_chat_endpoint_registration.py`` for what the live
endpoint actually guarantees, in both the healthy and the failed direction.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_THOMAS_ROOT = Path(__file__).resolve().parents[1] / "thomas"


def _python_sources() -> list[Path]:
    return sorted(p for p in _THOMAS_ROOT.rglob("*.py") if p.is_file())


class TestLegacyPrimaryChatStaysRetired(unittest.TestCase):
    def test_nothing_in_thomas_calls_register_chat_routes(self):
        callers: list[str] = []
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="replace")
            if "register_chat_routes(" not in text:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if "register_chat_routes(" not in stripped:
                    continue
                # The definition itself and the shim's re-export are expected.
                if stripped.startswith(("def ", "from ", "import ")):
                    continue
                callers.append(f"{path.relative_to(_THOMAS_ROOT.parent)}: {stripped}")
        self.assertEqual(
            callers,
            [],
            "the legacy V1 chat engine must stay unwired; Chat V2 owns POST /api/chat",
        )

    def test_chat_v2_registration_is_the_only_live_api_chat_registrar(self):
        registrars: list[str] = []
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if 'add_post("/api/chat"' not in stripped and "add_post('/api/chat'" not in stripped:
                    continue
                registrars.append(str(path.relative_to(_THOMAS_ROOT.parent)).replace("\\", "/"))
        # chat_v2_registration.py registers it for real. chat_aiohttp_handlers.py
        # has the guarded legacy line that no caller reaches, chat_aiohttp.py
        # carries it inside a documentation string literal, and
        # app_routes_init.py claims it with the 503 sentinel when V2 fails.
        self.assertEqual(
            sorted(set(registrars)),
            [
                "thomas/server/app_routes_init.py",
                "thomas/server/routes/chat_aiohttp.py",
                "thomas/server/routes/chat_aiohttp_handlers.py",
                "thomas/server/routes/chat_v2_registration.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
