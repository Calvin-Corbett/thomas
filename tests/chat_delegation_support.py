"""Shared fixtures and stubs for the chat_delegation test modules.

These lived at the top of ``test_chat_delegation.py`` until that file passed the
1200-line hard limit and had to be split. Keeping them in one place means the
isolation fixture below cannot drift between the halves -- which matters,
because without it these tests write into the owner's real data directory.
"""

from __future__ import annotations

import pytest

from thomas.core import project_root as _project_root
from thomas.forge.anvil import forge_code_projects as _forge_code_projects


@pytest.fixture(autouse=True)
def _isolate_thomas_home(tmp_path_factory, monkeypatch):  # noqa: ANN001, ANN201
    """Keep the projects these tests mint out of the real ~/.thomas.

    A dispatched coding task now opens a Build session, which means it mints a
    real project folder and runs git in it. Without this, running these tests
    leaves a folder per coding test in the owner's own data directory and a
    bound row per test in their Build sidebar -- measured: four of them.

    Redirecting the project folder alone is not enough. ``bind_conversation``
    writes into the CATALOG root's registry, which defaults to the real Thomas
    checkout, so the folders landed in a temp dir while the rows binding them
    landed in the owner's registry -- and once pytest reaped the temp dir those
    rows pointed at nothing. Both roots have to move together.
    """
    home = tmp_path_factory.mktemp("thomas-home")
    catalog = tmp_path_factory.mktemp("thomas-catalog")
    monkeypatch.setattr(_forge_code_projects, "thomas_owned_root", lambda: home)
    monkeypatch.setattr(_project_root, "code_checkout", lambda: catalog)


class _BotStub:
    def __init__(self, bot_id: str = "nova", name: str = "Nova") -> None:
        self.id = bot_id
        self.name = name

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


def _model_runtime_event(*, model: str = "test-model") -> dict[str, object]:
    return {
        "type": "model_runtime",
        "runtime": {
            "requested": {"profile": "test", "model": model, "api_key": "sk-never-persist"},
            "active": {
                "profile": "test",
                "provider": "test-provider",
                "model": model,
                "base_url": "https://user:pass@example.test/private?token=secret",
            },
            "failover_enabled": False,
            "failover_used": False,
            "attempts": [
                {
                    "profile": "test",
                    "provider": "test-provider",
                    "model": model,
                    "status": "success",
                    "error": "raw provider error must not persist",
                }
            ],
        },
    }
