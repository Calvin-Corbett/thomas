"""A policy value the operator clearly meant must not disable every tool.

`PolicyConfig` fails closed on malformed input: any validation error puts
`DenyInvalidConfigRule` first in the chain, and that rule denies *every* tool
call, not just approval-gated ones. That posture is correct for input nobody
can interpret (``no_human_mode = 7``), and the tests in
``test_policy_allowlist_precedence.py`` pin it.

It is wrong for input that is unambiguous and merely spelled differently.
``no_human_mode = "Deny"`` names an existing mode. ``approval_timeout_s = 60.0``
is sixty seconds. Rejecting either revokes ``fs.read`` and every other tool,
and the reported reason is "policy configuration is invalid", which does not
point at the capital D.

Scope of the claim, because an earlier draft of this docstring got it wrong:
this is NOT a defect any release shipped. At the last commit there is no
``validation_errors`` field and no ``DenyInvalidConfigRule`` at all, and the
parser there already lowercased the mode and ran ``int()`` over the timeout, so
both spellings worked. The strict validation and this repair are two halves of
one unreleased change; no existing policy file was ever affected. Saying
otherwise invented a user-facing harm that never happened.

The line these tests draw: reject what cannot be interpreted, accept what can.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.marketplace.policy.config import PolicyConfig, load_policy_config
from thomas.marketplace.policy.policy import PolicyEngine
from thomas.marketplace.policy.types import PolicyContext, PolicyDecisionType


@pytest.fixture(autouse=True)
def _clear_policy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "THOMAS_GUARDRAILS",
        "THOMAS_GUARDRAILS_TIMEOUT_S",
        "THOMAS_NO_HUMAN_MODE",
        "THOMAS_GUARDRAILS_NO_HUMAN_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def _context(tool_name: str, sandbox_root: Path) -> PolicyContext:
    return PolicyContext(
        tool_name=tool_name,
        args={},
        cwd=str(sandbox_root),
        sandbox_root=str(sandbox_root),
        iteration=1,
        conversation_summary="policy spelling regression",
        runtime_root=str(sandbox_root),
    )


def _write_policy(tmp_path: Path, filename: str, policy_text: str) -> PolicyConfig:
    config_dir = tmp_path / ".thomas"
    config_dir.mkdir()
    (config_dir / filename).write_text(policy_text, encoding="utf-8")
    return load_policy_config(str(tmp_path))


@pytest.mark.parametrize(
    ("filename", "policy_text", "expected_mode"),
    [
        pytest.param("policy.toml", '[guardrails]\nno_human_mode = "Deny"\n', "deny", id="toml-capitalized-deny"),
        pytest.param("policy.toml", '[guardrails]\nno_human_mode = "ALLOW"\n', "allow", id="toml-shouted-allow"),
        pytest.param("policy.toml", '[guardrails]\nno_human_mode = " human "\n', "human", id="toml-padded-human"),
        pytest.param("policy.json", '{"guardrails": {"no_human_mode": "Deny"}}', "deny", id="json-capitalized-deny"),
    ],
)
def test_a_mode_named_in_another_case_is_honoured_not_treated_as_invalid(
    filename: str, policy_text: str, expected_mode: str, tmp_path: Path
) -> None:
    """"Deny" names a real mode. Honour it instead of revoking every tool."""
    cfg = _write_policy(tmp_path, filename, policy_text)

    assert cfg.validation_errors == []
    assert cfg.guardrails.no_human_mode == expected_mode

    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", tmp_path))
    assert decision.type == PolicyDecisionType.ALLOW
    assert decision.meta.get("rule_id") != "deny_invalid_config"


@pytest.mark.parametrize(
    ("filename", "policy_text", "expected_timeout"),
    [
        pytest.param("policy.toml", "[guardrails]\napproval_timeout_s = 60.0\n", 60, id="toml-integral-float"),
        pytest.param("policy.json", '{"guardrails": {"approval_timeout_s": 90.0}}', 90, id="json-integral-float"),
        pytest.param("policy.json", '{"guardrails": {"approval_timeout_s": "45"}}', 45, id="json-numeric-string"),
    ],
)
def test_a_whole_number_timeout_survives_its_json_or_toml_spelling(
    filename: str, policy_text: str, expected_timeout: int, tmp_path: Path
) -> None:
    """60.0 is sixty seconds. Losing every tool over the decimal point is a bug."""
    cfg = _write_policy(tmp_path, filename, policy_text)

    assert cfg.validation_errors == []
    assert cfg.guardrails.approval_timeout_s == expected_timeout

    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", tmp_path))
    assert decision.type == PolicyDecisionType.ALLOW
    assert decision.meta.get("rule_id") != "deny_invalid_config"


def test_an_operator_asking_for_deny_mode_keeps_the_tools_that_mode_allows(tmp_path: Path) -> None:
    """no_human_mode="Deny" must mean deny-mode, not deny-everything.

    The two outcomes differ where it counts: deny-mode converts approval
    prompts into denials but leaves unrestricted tools working, while an
    invalid-config denial takes `math.add` down with it.
    """
    cfg = _write_policy(tmp_path, "policy.toml", '[guardrails]\nno_human_mode = "Deny"\n')
    engine = PolicyEngine.from_config(cfg)

    unrestricted = engine.evaluate(_context("math.add", tmp_path))
    assert unrestricted.type == PolicyDecisionType.ALLOW

    gated = engine.evaluate(
        PolicyContext(
            tool_name="shell.exec",
            args={"command": "dir"},
            cwd=str(tmp_path),
            sandbox_root=str(tmp_path),
            iteration=1,
            conversation_summary="policy spelling regression",
            runtime_root=str(tmp_path),
        )
    )
    assert gated.type == PolicyDecisionType.DENY
    assert gated.meta.get("rule_id") != "deny_invalid_config"


@pytest.mark.parametrize(
    ("mapping", "expected_enabled", "expected_timeout"),
    [
        pytest.param({"guardrails": {"enabled": 0}}, False, 60, id="off-as-zero"),
        pytest.param({"guardrails": {"enabled": 1}}, True, 60, id="on-as-one"),
        pytest.param({"guardrails": {"enabled": "false"}}, False, 60, id="off-as-string"),
        pytest.param({"guardrails": None}, True, 60, id="empty-guardrails-section"),
        pytest.param({"guardrails": {"approval_timeout_s": 0}}, True, 0, id="do-not-wait"),
    ],
)
def test_switching_guardrails_off_does_not_switch_every_tool_off(
    mapping: dict[str, object], expected_enabled: bool, expected_timeout: int, tmp_path: Path
) -> None:
    """`enabled = 0` is valid TOML for "turn guardrails off".

    Reading it as a config error was the worst available outcome: the error
    reaches DenyInvalidConfigRule, which denies EVERY tool, while `enabled`
    stayed True — so the one thing that did not turn off was guardrails. Zero
    seconds is likewise a choice ("do not wait"), not a parse failure, and an
    explicit empty guardrails section reads the same as an absent one.
    """
    cfg = PolicyConfig.from_mapping(mapping)

    assert cfg.validation_errors == []
    assert cfg.guardrails.enabled is expected_enabled
    assert cfg.guardrails.approval_timeout_s == expected_timeout

    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", tmp_path))
    assert decision.meta.get("rule_id") != "deny_invalid_config"


@pytest.mark.parametrize(
    ("mapping", "field_name"),
    [
        pytest.param({"guardrails": {"enabled": 7}}, "guardrails.enabled", id="enabled-as-seven"),
        pytest.param({"guardrails": {"no_human_mode": "sometimes"}}, "guardrails.no_human_mode", id="unknown-mode"),
        pytest.param({"guardrails": {"no_human_mode": 7}}, "guardrails.no_human_mode", id="integer-mode"),
        pytest.param({"guardrails": {"no_human_mode": True}}, "guardrails.no_human_mode", id="boolean-mode"),
        pytest.param({"guardrails": {"approval_timeout_s": 2.5}}, "guardrails.approval_timeout_s", id="fraction"),
        pytest.param({"guardrails": {"approval_timeout_s": True}}, "guardrails.approval_timeout_s", id="boolean"),
        pytest.param({"guardrails": {"approval_timeout_s": -7}}, "guardrails.approval_timeout_s", id="negative"),
        pytest.param({"guardrails": {"approval_timeout_s": "soon"}}, "guardrails.approval_timeout_s", id="word"),
        pytest.param({"guardrails": {"approval_timeout_s": ""}}, "guardrails.approval_timeout_s", id="empty-string"),
    ],
)
def test_input_that_cannot_be_interpreted_still_denies_every_tool(
    mapping: dict[str, object], field_name: str, tmp_path: Path
) -> None:
    """The fail-closed posture stays: this widens spelling, not meaning."""
    cfg = PolicyConfig.from_mapping(mapping)
    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", tmp_path))

    assert any(field_name in error for error in cfg.validation_errors)
    assert decision.type == PolicyDecisionType.DENY
    assert decision.meta.get("rule_id") == "deny_invalid_config"
