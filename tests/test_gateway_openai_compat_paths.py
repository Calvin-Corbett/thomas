from __future__ import annotations

from thomas.cli.commands.gateway.openai_compat_paths import (
    OPENAI_CHAT_COMPLETIONS_PATH as CLI_OPENAI_CHAT_COMPLETIONS_PATH,
)
from thomas.cli.commands.gateway.openai_compat_paths import (
    OPENAI_RESPONSES_PATH as CLI_OPENAI_RESPONSES_PATH,
)
from thomas.cli.commands.gateway.openai_compat_paths import (
    route_manifest as cli_route_manifest,
)
from thomas.server.routes.gateway.openai_compat_paths import (
    OPENAI_CHAT_COMPLETIONS_PATH as SERVER_OPENAI_CHAT_COMPLETIONS_PATH,
)
from thomas.server.routes.gateway.openai_compat_paths import (
    OPENAI_RESPONSES_PATH as SERVER_OPENAI_RESPONSES_PATH,
)
from thomas.server.routes.gateway.openai_compat_paths import (
    route_manifest as server_route_manifest,
)


def test_route_manifest_exposes_openai_compat_paths() -> None:
    cli_manifest = cli_route_manifest()
    server_manifest = server_route_manifest()

    assert CLI_OPENAI_CHAT_COMPLETIONS_PATH == SERVER_OPENAI_CHAT_COMPLETIONS_PATH
    assert CLI_OPENAI_RESPONSES_PATH == SERVER_OPENAI_RESPONSES_PATH
    assert cli_manifest["openai_chat_completions"] == CLI_OPENAI_CHAT_COMPLETIONS_PATH
    assert cli_manifest["openai_responses"] == CLI_OPENAI_RESPONSES_PATH
    assert server_manifest["openai_chat_completions"] == SERVER_OPENAI_CHAT_COMPLETIONS_PATH
    assert server_manifest["openai_responses"] == SERVER_OPENAI_RESPONSES_PATH
