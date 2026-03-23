import json

import pytest
import typer
from typer.testing import CliRunner

import thomas.cli.commands.channel_ops as channel_ops_pkg
from thomas.cli.commands.channel_ops import p089_channel_throttling_policy as cli_op
from thomas.marketplace.channels.p089_channel_throttling_policy import (
    ChannelThrottleError,
    ChannelThrottlePolicy,
    InMemoryThrottleStateStore,
    JsonFileThrottleStateStore,
    ThrottleCheckRequest,
    ThrottlePolicyConfig,
    parse_throttle_policy_config,
)


def test_token_bucket_allows_burst_then_throttles_and_recovers() -> None:
    store = InMemoryThrottleStateStore()
    policy = ChannelThrottlePolicy(ThrottlePolicyConfig(rate_per_second=1.0, burst=2), store=store)

    d1 = policy.evaluate(ThrottleCheckRequest(bucket_key="telegram:chat", cost=1.0, now=0.0))
    assert d1.allowed is True
    assert d1.retry_after_seconds == 0.0
    assert d1.state.tokens == pytest.approx(1.0)

    d2 = policy.evaluate(ThrottleCheckRequest(bucket_key="telegram:chat", cost=1.0, now=0.0))
    assert d2.allowed is True
    assert d2.state.tokens == pytest.approx(0.0)

    d3 = policy.evaluate(ThrottleCheckRequest(bucket_key="telegram:chat", cost=1.0, now=0.0))
    assert d3.allowed is False
    assert d3.retry_after_seconds == pytest.approx(1.0)

    d4 = policy.evaluate(ThrottleCheckRequest(bucket_key="telegram:chat", cost=1.0, now=1.0))
    assert d4.allowed is True


def test_parse_config_accepts_per_minute_rates() -> None:
    cfg = parse_throttle_policy_config({"messages_per_minute": 60, "burst": 3})
    assert cfg.rate_per_second == pytest.approx(1.0)
    assert cfg.burst == 3


def test_missing_config_is_deterministic() -> None:
    with pytest.raises(ChannelThrottleError) as exc:
        parse_throttle_policy_config({"rate_per_second": 1.0})
    assert exc.value.code == "missing_config"


def test_state_file_invalid_json_errors(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("not json", encoding="utf-8")

    store = JsonFileThrottleStateStore(state_path)
    with pytest.raises(ChannelThrottleError) as exc:
        store.load("bucket")
    assert exc.value.code in ("state_read_failed", "state_lock_failed")


def _build_root_channels_app() -> tuple[typer.Typer, typer.Typer]:
    root = typer.Typer(add_completion=False)
    channels = typer.Typer(add_completion=False)
    root.add_typer(channels, name="channels")
    return root, channels


def _build_test_app_register_direct() -> typer.Typer:
    root, channels = _build_root_channels_app()
    cli_op.register(channels)
    return root


def _build_test_app_register_pkg() -> typer.Typer:
    root, channels = _build_root_channels_app()
    channel_ops_pkg.register(channels)
    return root


def test_cli_json_success() -> None:
    runner = CliRunner()
    app = _build_test_app_register_direct()

    result = runner.invoke(
        app,
        [
            "channels",
            cli_op.COMMAND_NAME,
            "--channel",
            "telegram",
            "--burst",
            "2",
            "--rate-per-second",
            "1",
            "--cost",
            "1",
            "--now",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["decision"]["allowed"] is True
    assert payload["decision"]["schema_version"] == 1


def test_cli_json_failure_missing_config() -> None:
    runner = CliRunner()
    app = _build_test_app_register_direct()

    result = runner.invoke(
        app,
        [
            "channels",
            cli_op.COMMAND_NAME,
            "--channel",
            "telegram",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"


def test_cli_state_file_persists_across_invocations(tmp_path) -> None:
    runner = CliRunner()
    app = _build_test_app_register_direct()
    state_file = tmp_path / "throttle_state.json"

    for _ in range(2):
        r = runner.invoke(
            app,
            [
                "channels",
                cli_op.COMMAND_NAME,
                "--channel",
                "telegram",
                "--bucket-key",
                "telegram:chat:1",
                "--burst",
                "2",
                "--rate-per-second",
                "1",
                "--now",
                "0",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["decision"]["allowed"] is True

    r3 = runner.invoke(
        app,
        [
            "channels",
            cli_op.COMMAND_NAME,
            "--channel",
            "telegram",
            "--bucket-key",
            "telegram:chat:1",
            "--burst",
            "2",
            "--rate-per-second",
            "1",
            "--now",
            "0",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert r3.exit_code == 0, r3.output
    assert json.loads(r3.output)["decision"]["allowed"] is False


def test_channel_ops_package_registers_command() -> None:
    runner = CliRunner()
    app = _build_test_app_register_pkg()

    result = runner.invoke(
        app,
        [
            "channels",
            cli_op.COMMAND_NAME,
            "--channel",
            "telegram",
            "--burst",
            "1",
            "--rate-per-second",
            "1",
            "--now",
            "0",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
