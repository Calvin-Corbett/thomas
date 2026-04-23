from __future__ import annotations

import json
from io import StringIO


def test_p148_rejects_empty_model():
    from thomas.server.routes.gateway.p148_compat_model_capability_resolver import (
        resolve_compat_model_capabilities,
    )

    out = resolve_compat_model_capabilities({"model": ""}).to_dict()
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_input"


def test_p148_resolves_basic_openai_like_model():
    from thomas.server.routes.gateway.p148_compat_model_capability_resolver import (
        resolve_compat_model_capabilities,
    )

    out = resolve_compat_model_capabilities({"model": "gpt-4.1-mini"}).to_dict()
    assert out["ok"] is True
    caps = out["capabilities"]
    assert caps["model"] == "gpt-4.1-mini"
    assert caps["supports_chat_completions"] is True
    assert caps["supports_responses_api"] is True
    assert caps["supports_streaming"] is True
    assert caps["supports_function_tools"] is True
    assert caps["supports_json_schema_response_format"] is True


def test_p148_cli_json_output_smoke():
    from thomas.cli.commands.gateway.p148_compat_model_capability_resolver import (
        P148CompatModelCapabilityResolverArgs,
        run,
    )

    buf = StringIO()
    code = run(P148CompatModelCapabilityResolverArgs(model="gpt-4.1-mini", json_output=True), stdout=buf)
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is True
    assert payload["capabilities"]["model"] == "gpt-4.1-mini"


def test_p148_invalid_caps_config_is_deterministic(monkeypatch):
    from thomas.server.routes.gateway.p148_compat_model_capability_resolver import (
        resolve_compat_model_capabilities,
    )

    monkeypatch.setenv("THOMAS_COMPAT_MODEL_CAPS_JSON", "{not valid json")
    out = resolve_compat_model_capabilities({"model": "gpt-4.1-mini"}).to_dict()
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_config"
