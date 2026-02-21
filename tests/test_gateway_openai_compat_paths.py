from __future__ import annotations

from thomas.cli.commands.gateway.openai_compat_paths import (
    OPENAI_CHAT_COMPLETIONS_PATH,
    OPENAI_RESPONSES_PATH,
    route_manifest,
)


def test_route_manifest_exposes_openai_compat_paths() -> None:
    manifest = route_manifest()
    assert manifest["openai_chat_completions"] == OPENAI_CHAT_COMPLETIONS_PATH
    assert manifest["openai_responses"] == OPENAI_RESPONSES_PATH
