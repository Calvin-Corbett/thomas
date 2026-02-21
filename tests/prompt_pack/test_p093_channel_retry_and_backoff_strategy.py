import argparse
import json

import pytest

from thomas.channels.p093_channel_retry_and_backoff_strategy import (
    ChannelRetryConfigError,
    ChannelRetryExecutionError,
    RetryPolicy,
    build_retry_plan,
    call_with_retry,
    call_with_retry_or_raise,
)


def test_build_retry_plan_is_exponential_without_jitter() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        base_delay_s=1.0,
        backoff_factor=2.0,
        max_delay_s=60.0,
    )
    plan = build_retry_plan(policy)

    assert [s.delay_s for s in plan.steps] == [1.0, 2.0, 4.0]
    assert plan.total_delay_s == 7.0


def test_build_retry_plan_respects_max_delay() -> None:
    policy = RetryPolicy(
        max_attempts=5,
        base_delay_s=5.0,
        backoff_factor=3.0,
        max_delay_s=10.0,
    )
    plan = build_retry_plan(policy)

    assert [s.delay_s for s in plan.steps] == [5.0, 10.0, 10.0, 10.0]


def test_jitter_requires_seed_for_determinism() -> None:
    with pytest.raises(ChannelRetryConfigError) as excinfo:
        RetryPolicy(max_attempts=3, base_delay_s=1.0, jitter=0.2, jitter_seed=None)

    assert excinfo.value.code == "missing_jitter_seed"


def test_call_with_retry_succeeds_after_transient_failures() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def op() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    policy = RetryPolicy(
        max_attempts=5,
        base_delay_s=1.0,
        backoff_factor=2.0,
        max_delay_s=60.0,
    )

    outcome = call_with_retry(op, policy=policy, sleep=fake_sleep)
    assert outcome.ok is True
    assert outcome.attempts == 3
    assert outcome.value == "ok"

    # After attempt 1 failure -> 1s, after attempt 2 failure -> 2s
    assert slept == [1.0, 2.0]


def test_call_with_retry_or_raise_exhausts_attempts() -> None:
    def op() -> None:
        raise TimeoutError("nope")

    def fake_sleep(_: float) -> None:
        return

    policy = RetryPolicy(max_attempts=3, base_delay_s=0.5, backoff_factor=2.0, max_delay_s=60.0)

    with pytest.raises(ChannelRetryExecutionError) as excinfo:
        call_with_retry_or_raise(op, policy=policy, sleep=fake_sleep)

    err = excinfo.value
    assert err.code == "retry_exhausted"
    assert err.attempts == 3
    assert err.last_error_type == "TimeoutError"


def test_call_with_retry_or_raise_non_retryable_failure() -> None:
    def op() -> None:
        raise ValueError("bad")

    policy = RetryPolicy(max_attempts=5, base_delay_s=1.0)

    with pytest.raises(ChannelRetryExecutionError) as excinfo:
        call_with_retry_or_raise(op, policy=policy, sleep=lambda _: None)

    assert excinfo.value.code == "non_retryable_failure"
    assert excinfo.value.attempts == 1


def test_cli_register_and_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    from thomas.cli.commands.channel_ops import p093_channel_retry_and_backoff_strategy as cli_op

    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="cmd")

    channels_parser = subparsers.add_parser("channels")
    channels_sub = channels_parser.add_subparsers(dest="channels_cmd")

    cli_op.register(channels_sub)

    args = parser.parse_args(
        [
            "channels",
            cli_op.COMMAND_NAME,
            "--attempts",
            "4",
            "--base-delay",
            "1",
            "--factor",
            "2",
            "--max-delay",
            "60",
            "--json",
        ]
    )

    handler = getattr(args, "func", None) or getattr(args, "handler", None)
    assert callable(handler)

    handler(args)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert payload["ok"] is True
    assert payload["plan"]["total_delay_s"] == pytest.approx(7.0)


def test_cli_missing_config_file_json_is_deterministic(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    from thomas.cli.commands.channel_ops import p093_channel_retry_and_backoff_strategy as cli_op

    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="cmd")

    channels_parser = subparsers.add_parser("channels")
    channels_sub = channels_parser.add_subparsers(dest="channels_cmd")

    cli_op.register(channels_sub)

    missing = tmp_path / "missing.json"

    args = parser.parse_args(["channels", cli_op.COMMAND_NAME, "--config", str(missing), "--json"])

    handler = getattr(args, "func", None) or getattr(args, "handler", None)
    assert callable(handler)

    with pytest.raises(SystemExit) as excinfo:
        handler(args)

    assert excinfo.value.code == 2

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_not_found"
