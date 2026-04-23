import json
from datetime import date

import pytest
import typer
from typer.testing import CliRunner


@pytest.mark.asyncio
async def test_parse_usage_cost_query_invalid_date_raises() -> None:
    from thomas.server.routes.gateway.p134_gateway_usage_cost_command import (
        GatewayUsageCostError,
        parse_usage_cost_query,
    )

    with pytest.raises(GatewayUsageCostError) as excinfo:
        parse_usage_cost_query({"start_date": "2026-13-01", "end_date": "2026-02-01"})

    err = excinfo.value
    assert err.code == "invalid_date"


@pytest.mark.asyncio
async def test_run_gateway_usage_cost_missing_config_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thomas.server.routes.gateway.p134_gateway_usage_cost_command import (
        GatewayUsageCostError,
        GatewayUsageCostQuery,
        run_gateway_usage_cost,
    )

    monkeypatch.delenv("THOMAS_GATEWAY_URL", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)

    query = GatewayUsageCostQuery(start_date=date(2026, 2, 1), end_date=date(2026, 2, 1))

    with pytest.raises(GatewayUsageCostError) as excinfo:
        await run_gateway_usage_cost(query=query, gateway_url=None, gateway_api_key=None)

    assert excinfo.value.code == "missing_gateway_url"


@pytest.mark.asyncio
async def test_run_gateway_usage_cost_external_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server.routes.gateway import p134_gateway_usage_cost_command as mod

    async def _boom(**kwargs):
        raise mod.aiohttp.ClientError("nope")

    monkeypatch.setenv("THOMAS_GATEWAY_URL", "https://example.test")
    monkeypatch.setenv("THOMAS_GATEWAY_API_KEY", "secret")
    monkeypatch.setattr(mod, "_fetch_gateway_usage_cost", _boom)

    query = mod.GatewayUsageCostQuery(start_date=date(2026, 2, 1), end_date=date(2026, 2, 1))
    with pytest.raises(mod.GatewayUsageCostError) as excinfo:
        await mod.run_gateway_usage_cost(query=query)

    assert excinfo.value.code == "gateway_unreachable"


@pytest.mark.asyncio
async def test_run_gateway_usage_cost_success_sums_breakdown(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server.routes.gateway import p134_gateway_usage_cost_command as mod

    async def _ok(**kwargs):
        return {
            "currency": "USD",
            "breakdown": [
                {
                    "date": "2026-02-01",
                    "requests": 2,
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "total_tokens": 30,
                    "cost_usd": 0.0123,
                },
                {
                    "date": "2026-02-02",
                    "requests": 1,
                    "input_tokens": 5,
                    "output_tokens": 5,
                    "total_tokens": 10,
                    "cost_usd": 0.004,
                },
            ],
        }

    monkeypatch.setenv("THOMAS_GATEWAY_URL", "https://example.test")
    monkeypatch.setenv("THOMAS_GATEWAY_API_KEY", "secret")
    monkeypatch.setattr(mod, "_fetch_gateway_usage_cost", _ok)

    query = mod.GatewayUsageCostQuery(start_date=date(2026, 2, 1), end_date=date(2026, 2, 2))
    report = await mod.run_gateway_usage_cost(query=query)

    assert report.currency == "USD"
    assert report.requests == 3
    assert report.input_tokens == 15
    assert report.output_tokens == 25
    assert report.total_tokens == 40
    assert abs(report.total_cost_usd - 0.0163) < 1e-9


def test_cli_usage_cost_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server.routes.gateway import p134_gateway_usage_cost_command as srv_mod
    from thomas.cli.commands.gateway import p134_gateway_usage_cost_command as cli_mod

    async def _ok(**kwargs):
        return {
            "currency": "USD",
            "total_cost_usd": 1.0,
            "requests": 1,
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 5,
            "breakdown": [],
        }

    monkeypatch.setenv("THOMAS_GATEWAY_URL", "https://example.test")
    monkeypatch.setenv("THOMAS_GATEWAY_API_KEY", "secret")
    monkeypatch.setattr(srv_mod, "_fetch_gateway_usage_cost", _ok)

    app = typer.Typer()
    cli_mod.register(app)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "usage-cost",
            "--start-date",
            date(2026, 2, 1).isoformat(),
            "--end-date",
            date(2026, 2, 1).isoformat(),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["total_cost_usd"] == 1.0
