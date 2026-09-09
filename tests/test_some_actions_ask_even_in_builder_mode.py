
from __future__ import annotations

from pathlib import Path

import pytest

from thomas.marketplace.policy.config import PolicyConfig
from thomas.marketplace.policy.policy import PolicyEngine
from thomas.marketplace.policy.types import PolicyContext, PolicyDecisionType


def _ctx(tool_name: str, args: dict[str, object], tmp_path: Path) -> PolicyContext:
    return PolicyContext(
        tool_name=tool_name,
        args=args,
        cwd=str(tmp_path),
        sandbox_root=str(tmp_path),
        iteration=1,
        conversation_summary="builder mode hard gates",
        runtime_root=str(tmp_path),
    )


def _builder_mode_engine() -> PolicyEngine:
    """Builder mode: act freely, do not stop to ask."""
    cfg = PolicyConfig()
    cfg.guardrails.no_human_mode = "allow"
    return PolicyEngine.from_config(cfg)


OUTBOUND_CASES = [
    pytest.param("git.push", {}, id="git-push-tool"),
    pytest.param("shell.exec", {"command": "git push origin main"}, id="git-push-via-shell"),
    pytest.param("shell.exec", {"command": "gh pr create --fill"}, id="open-a-pull-request"),
    pytest.param("shell.exec", {"command": "gh release create v2"}, id="cut-a-release"),
    pytest.param("email.send", {"to": "someone@example.com"}, id="send-email"),
    pytest.param("discord.send_message", {"text": "hi"}, id="send-discord-message"),
    pytest.param("channels.post", {"text": "hi"}, id="post-to-a-channel"),
    pytest.param("trading.place_order", {"symbol": "ACME"}, id="place-a-trade"),
    pytest.param("payments.checkout", {"amount": 100}, id="spend-money"),
]


@pytest.mark.parametrize(("tool_name", "args"), [(p.values[0], p.values[1]) for p in OUTBOUND_CASES], ids=[p.id for p in OUTBOUND_CASES])
def test_an_outbound_action_still_asks_with_builder_mode_on(
    tool_name: str, args: dict[str, object], tmp_path: Path
) -> None:
    decision = _builder_mode_engine().evaluate(_ctx(tool_name, args, tmp_path))

    assert decision.type == PolicyDecisionType.REQUIRE_APPROVAL, (
        f"{tool_name} was auto-approved in Builder mode; this action leaves the machine "
        "and must ask a human regardless of mode"
    )
    assert decision.meta.get("always_ask") is True


READ_CASES = [
    pytest.param("email.read", id="read-email"),
    pytest.param("email.list", id="list-email"),
    pytest.param("email.get", id="fetch-one-email"),
    pytest.param("discord.read_messages", id="read-discord"),
    pytest.param("channels.list", id="list-channels"),
    pytest.param("trading.get_quote", id="check-a-price"),
    pytest.param("payments.list_transactions", id="read-transactions"),
]


@pytest.mark.parametrize("tool_name", [p.values[0] for p in READ_CASES], ids=[p.id for p in READ_CASES])
def test_reading_from_a_service_is_not_sending_to_it(tool_name: str, tmp_path: Path) -> None:
    """Gating a namespace instead of an action broke reading your own mail.

    An earlier version of AlwaysAskOutboundRule matched the first dot-segment
    against names like "email" and "trading", so email.read and
    trading.get_quote asked for approval — and under a strict gatekeeper an
    approval request is converted into a refusal, which makes an inbound read
    impossible. Nothing here leaves the machine.
    """
    decision = _builder_mode_engine().evaluate(_ctx(tool_name, {}, tmp_path))

    assert decision.type != PolicyDecisionType.REQUIRE_APPROVAL, (
        f"{tool_name} reads data; it sends nothing and must not be gated as outbound"
    )


def test_ordinary_work_does_not_ask_in_builder_mode(tmp_path: Path) -> None:
    """Builder mode has to actually be quiet, or nobody will leave it on."""
    engine = _builder_mode_engine()

    for tool_name, args in (
        ("fs.write_file", {"path": str(tmp_path / "notes.txt"), "content": "hi"}),
        ("fs.read_file", {"path": str(tmp_path / "notes.txt")}),
        ("math.add", {"a": 1, "b": 2}),
        ("shell.exec", {"command": "pytest -q"}),
    ):
        decision = engine.evaluate(_ctx(tool_name, args, tmp_path))
        assert decision.type != PolicyDecisionType.REQUIRE_APPROVAL, (
            f"{tool_name} prompted in Builder mode; only outbound actions should"
        )


def test_the_hard_gates_are_not_reachable_by_an_allowlist(tmp_path: Path) -> None:
    """An allow_tools entry must not buy its way past an always-ask action."""
    cfg = PolicyConfig(allow_tools=["git.push"])
    cfg.guardrails.no_human_mode = "allow"

    decision = PolicyEngine.from_config(cfg).evaluate(_ctx("git.push", {}, tmp_path))

    assert decision.type == PolicyDecisionType.REQUIRE_APPROVAL


def test_ask_first_mode_is_unchanged_by_any_of_this(tmp_path: Path) -> None:
    """The strict mode people opt into must keep asking about everything it did."""
    cfg = PolicyConfig()  # no_human_mode defaults to "human"
    engine = PolicyEngine.from_config(cfg)

    outbound = engine.evaluate(_ctx("git.push", {}, tmp_path))
    shell = engine.evaluate(_ctx("shell.exec", {"command": "dir"}, tmp_path))

    assert outbound.type == PolicyDecisionType.REQUIRE_APPROVAL
    assert shell.type == PolicyDecisionType.REQUIRE_APPROVAL


def test_deny_mode_still_denies_an_outbound_action(tmp_path: Path) -> None:
    """always_ask lifts the auto-ALLOW only. Refusing outright is stricter, so it stands."""
    cfg = PolicyConfig()
    cfg.guardrails.no_human_mode = "deny"

    decision = PolicyEngine.from_config(cfg).evaluate(_ctx("git.push", {}, tmp_path))

    assert decision.type == PolicyDecisionType.DENY
