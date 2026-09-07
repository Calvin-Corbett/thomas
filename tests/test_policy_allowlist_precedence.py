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


def _context(
    tool_name: str,
    args: dict[str, object],
    *,
    sandbox_root: Path,
    runtime_root: Path | None = None,
) -> PolicyContext:
    return PolicyContext(
        tool_name=tool_name,
        args=args,
        cwd=str(sandbox_root),
        sandbox_root=str(sandbox_root),
        iteration=1,
        conversation_summary="allowlist precedence regression",
        runtime_root=str(runtime_root or sandbox_root),
    )


def _write_policy(tmp_path: Path, filename: str, policy_text: str) -> PolicyConfig:
    config_dir = tmp_path / ".thomas"
    config_dir.mkdir()
    (config_dir / filename).write_text(policy_text, encoding="utf-8")
    return load_policy_config(str(tmp_path))


@pytest.mark.parametrize(
    ("case_name", "expected_type", "expected_rule"),
    [
        pytest.param("shell_approval", PolicyDecisionType.REQUIRE_APPROVAL, "approve_shell_exec", id="shell-approval"),
        pytest.param("explicit_deny", PolicyDecisionType.DENY, "deny_tools", id="explicit-deny"),
        pytest.param("group_name_deny", PolicyDecisionType.DENY, "deny_tool_groups", id="group-name-deny"),
        pytest.param("group_category_deny", PolicyDecisionType.DENY, "deny_tool_groups", id="group-category-deny"),
        pytest.param(
            "configured_approval",
            PolicyDecisionType.REQUIRE_APPROVAL,
            "config_tools_require_approval",
            id="configured-approval",
        ),
        pytest.param("secret_path", PolicyDecisionType.DENY, "deny_secret_reads", id="secret-path"),
        pytest.param(
            "outside_write", PolicyDecisionType.REQUIRE_APPROVAL, "approve_write_outside_sandbox", id="outside-write"
        ),
        pytest.param("git_push", PolicyDecisionType.REQUIRE_APPROVAL, "approve_git_push", id="git-push"),
    ],
)
def test_allowlist_never_overrides_deny_or_approval_rules(
    case_name: str,
    expected_type: PolicyDecisionType,
    expected_rule: str,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    protected = tmp_path / "protected"
    tool_name = "math.add"
    args: dict[str, object] = {}
    tool_categories: dict[str, str] = {}
    cfg = PolicyConfig()

    if case_name == "shell_approval":
        tool_name, args = "shell.exec", {"command": "dir"}
    elif case_name == "explicit_deny":
        cfg.deny_tools = [tool_name]
    elif case_name == "group_name_deny":
        tool_name, args, cfg.deny_groups = "shell.exec", {"command": "dir"}, ["shell"]
    elif case_name == "group_category_deny":
        tool_name, cfg.deny_groups = "custom.browser", ["browser"]
        tool_categories = {tool_name: "browser"}
    elif case_name == "configured_approval":
        cfg.guardrails.tools_require_approval = [tool_name]
    elif case_name == "secret_path":
        tool_name, cfg.deny_roots = "fs.read_file", [str(protected)]
        args = {"path": str(protected / "token.txt")}
    elif case_name == "outside_write":
        tool_name = "fs.write_file"
        args = {"path": str(tmp_path / "outside.txt"), "content": "data"}
    elif case_name == "git_push":
        tool_name = "git.push"

    cfg.allow_tools = [tool_name]
    decision = PolicyEngine.from_config(cfg, tool_categories=tool_categories).evaluate(
        _context(tool_name, args, sandbox_root=sandbox)
    )
    assert decision.type == expected_type
    assert decision.meta.get("rule_id") == expected_rule


def test_allowlist_still_labels_an_unrestricted_tool_as_allowed(tmp_path: Path) -> None:
    cfg = PolicyConfig(allow_tools=["math.add"])
    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", {"a": 1, "b": 2}, sandbox_root=tmp_path))
    assert decision.type == PolicyDecisionType.ALLOW
    assert decision.meta.get("rule_id") == "allow_tools"


def test_policy_toml_allowlist_cannot_override_configured_approval(tmp_path: Path) -> None:
    cfg = _write_policy(
        tmp_path,
        "policy.toml",
        'allow_tools = ["math.add"]\n\n[guardrails]\ntools_require_approval = ["math.add"]\n',
    )
    decision = PolicyEngine.from_config(cfg).evaluate(
        _context("math.add", {"a": 1, "b": 2}, sandbox_root=tmp_path, runtime_root=tmp_path)
    )
    assert decision.type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.meta.get("rule_id") == "config_tools_require_approval"


def test_scalar_deny_tools_from_toml_remains_an_exact_deny(tmp_path: Path) -> None:
    cfg = _write_policy(tmp_path, "policy.toml", 'allow_tools = ["math.add"]\ndeny_tools = "math.add"\n')
    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", {}, sandbox_root=tmp_path))
    assert cfg.deny_tools == ["math.add"]
    assert decision.type == PolicyDecisionType.DENY
    assert decision.meta.get("rule_id") == "deny_tools"


def test_scalar_configured_approval_from_toml_remains_an_exact_gate(tmp_path: Path) -> None:
    cfg = _write_policy(
        tmp_path,
        "policy.toml",
        'allow_tools = ["math.add"]\n\n[guardrails]\ntools_require_approval = "math.add"\n',
    )
    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", {}, sandbox_root=tmp_path))
    assert cfg.guardrails.tools_require_approval == ["math.add"]
    assert decision.type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.meta.get("rule_id") == "config_tools_require_approval"


@pytest.mark.parametrize(
    ("mapping", "field_name"),
    [
        pytest.param({"allow_tools": True}, "allow_tools", id="boolean-allow-tools"),
        pytest.param({"deny_tools": 7}, "deny_tools", id="integer-deny-tools"),
        pytest.param({"deny_tools": ["math.add", 7]}, "deny_tools", id="mixed-deny-tools"),
        pytest.param({"deny_groups": {"shell": True}}, "deny_groups", id="mapping-deny-groups"),
        pytest.param(
            {"guardrails": {"tools_require_approval": False}},
            "guardrails.tools_require_approval",
            id="boolean-approval-tools",
        ),
        pytest.param({"guardrails": "human"}, "guardrails", id="scalar-guardrails-section"),
    ],
)
def test_policy_mapping_records_malformed_types_and_denies_all_tools(
    mapping: dict[str, object], field_name: str, tmp_path: Path
) -> None:
    cfg = PolicyConfig.from_mapping(mapping)
    decision = PolicyEngine.from_config(cfg).evaluate(_context("math.add", {}, sandbox_root=tmp_path))
    assert any(field_name in error for error in cfg.validation_errors)
    assert decision.type == PolicyDecisionType.DENY
    assert decision.meta.get("rule_id") == "deny_invalid_config"


@pytest.mark.parametrize(
    "malformed_policy",
    [
        pytest.param('allow_tools = ["math.add"]\ndeny_tools = ["math.add", 7]\n', id="mixed-deny-list"),
        pytest.param(
            'allow_tools = ["math.add"]\n\n[guardrails]\ntools_require_approval = false\n', id="boolean-approval-list"
        ),
    ],
)
def test_malformed_valid_toml_loads_into_an_unconditional_deny(malformed_policy: str, tmp_path: Path) -> None:
    cfg = _write_policy(tmp_path, "policy.toml", malformed_policy)
    decision = PolicyEngine.from_config(cfg).evaluate(
        _context("math.add", {}, sandbox_root=tmp_path, runtime_root=tmp_path)
    )
    assert cfg.validation_errors
    assert decision.type == PolicyDecisionType.DENY
    assert decision.meta.get("rule_id") == "deny_invalid_config"


@pytest.mark.parametrize(
    ("filename", "policy_text", "invalid_field", "expected_mode", "expected_timeout"),
    [
        pytest.param(
            "policy.toml",
            "[guardrails]\nno_human_mode = 7\n",
            "guardrails.no_human_mode",
            "human",
            60,
            id="toml-mode-integer",
        ),
        pytest.param(
            "policy.toml",
            "[guardrails]\nno_human_mode = true\n",
            "guardrails.no_human_mode",
            "human",
            60,
            id="toml-mode-boolean",
        ),
        pytest.param(
            "policy.toml",
            '[guardrails]\nno_human_mode = "sometimes"\n',
            "guardrails.no_human_mode",
            "human",
            60,
            id="toml-mode-unknown-string",
        ),
        pytest.param(
            "policy.json",
            '{"guardrails": {"no_human_mode": {}}}',
            "guardrails.no_human_mode",
            "human",
            60,
            id="json-mode-object",
        ),
        pytest.param(
            "policy.toml",
            "[guardrails]\napproval_timeout_s = 2.5\n",
            "guardrails.approval_timeout_s",
            "human",
            60,
            id="toml-timeout-fraction",
        ),
        pytest.param(
            "policy.toml",
            '[guardrails]\nno_human_mode = "allow"\napproval_timeout_s = -7\n',
            "guardrails.approval_timeout_s",
            "allow",
            60,
            id="toml-timeout-negative-no-human-allow",
        ),
        pytest.param(
            "policy.json",
            '{"guardrails": {"approval_timeout_s": true}}',
            "guardrails.approval_timeout_s",
            "human",
            60,
            id="json-timeout-boolean",
        ),
    ],
)
def test_malformed_guardrail_values_from_real_policy_files_deny_all_tools(
    filename: str,
    policy_text: str,
    invalid_field: str,
    expected_mode: str,
    expected_timeout: int,
    tmp_path: Path,
) -> None:
    cfg = _write_policy(tmp_path, filename, policy_text)
    decision = PolicyEngine.from_config(cfg).evaluate(
        _context("math.add", {}, sandbox_root=tmp_path, runtime_root=tmp_path)
    )
    assert any(invalid_field in error for error in cfg.validation_errors)
    assert cfg.guardrails.no_human_mode == expected_mode
    assert cfg.guardrails.approval_timeout_s == expected_timeout
    assert decision.type == PolicyDecisionType.DENY
    assert decision.meta.get("rule_id") == "deny_invalid_config"
