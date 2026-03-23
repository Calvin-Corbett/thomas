import json

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.channel_ops import p085_channel_list_enriched_output as cli_mod
from thomas.marketplace.channels.p085_channel_list_enriched_output import (
    ChannelListEnrichedOutputError,
    ChannelListEnrichedRequest,
    channel_list_enriched_output,
)


class StubIntegration:
    def __init__(self, channels):
        self._channels = list(channels)

    def list_channels(self, limit=100, offset=0):
        # apply simplistic paging; treat limit==0 as no limit
        if limit == 0 or limit is None:
            limit = len(self._channels)
        return self._channels[offset : offset + limit]


def test_core_success_enrich_and_sorting():
    client = StubIntegration(
        channels=[
            {"id": 2, "title": "Zeta", "type": "group", "username": "zeta"},
            {"id": 1, "title": "alpha", "type": "dm", "username": None},
        ]
    )

    req = ChannelListEnrichedRequest(integration="telegram", limit=100, offset=0)
    resp = channel_list_enriched_output(req, integration_client=client)

    assert resp.count == 2
    # Sorted by name case-insensitively
    assert [c.name for c in resp.channels] == ["alpha", "Zeta"]
    assert resp.channels[0].platform == "telegram"
    assert resp.channels[0].id == "1"


def test_core_unknown_id_gets_deterministic_fallback():
    client = StubIntegration(channels=[{"title": "A"}, {"title": "B"}])
    resp = channel_list_enriched_output(ChannelListEnrichedRequest(integration="telegram"), integration_client=client)
    assert resp.channels[0].id.startswith("unknown:")
    assert resp.count == 2


def test_core_invalid_input_limit():
    with pytest.raises(ChannelListEnrichedOutputError) as excinfo:
        channel_list_enriched_output(ChannelListEnrichedRequest(limit=-1), integration_client=StubIntegration([]))
    assert excinfo.value.code == "invalid_input"


def test_core_missing_config_when_no_ctx_or_client():
    with pytest.raises(ChannelListEnrichedOutputError) as excinfo:
        channel_list_enriched_output(ChannelListEnrichedRequest())
    assert excinfo.value.code == "missing_config"


def test_core_external_failure_is_wrapped_deterministically():
    class Boom:
        def list_channels(self, *a, **k):
            raise RuntimeError("nope")

    with pytest.raises(ChannelListEnrichedOutputError) as excinfo:
        channel_list_enriched_output(ChannelListEnrichedRequest(integration="telegram"), integration_client=Boom())
    assert excinfo.value.code == "external_failure"
    assert "Failed to list channels" in excinfo.value.message


def test_cli_json_success_schema():
    runner = CliRunner()

    client = StubIntegration(channels=[{"id": 1, "title": "A"}])
    result = runner.invoke(
        cli_mod.app,
        ["--json"],
        obj={"integrations": {"telegram": client}},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert payload["channels"][0]["name"] == "A"


def test_cli_json_failure_schema_missing_config():
    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "missing_config"
