from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import click
from click.testing import CliRunner

from thomas.cli.parity_compat import register_compat_commands


def _build_root_cli() -> click.Group:
    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        _ = ctx

    return root


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        memory=SimpleNamespace(root_path=tmp_path),
        server=SimpleNamespace(access_mode="local", api_token=""),
        tools=SimpleNamespace(allow_shell=False, sandbox_path=tmp_path, max_file_size=5_000_000),
        models={"local": {"model": "dummy"}},
        default_model="local",
    )


def _memory_cli_context(tmp_path: Path) -> tuple[click.Group, CliRunner, SimpleNamespace]:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)
    return root, runner, cfg


def _assert_memory_payload(
    payload: dict[str, object],
    *,
    action: str,
    mode: str,
    ok: bool,
    executed: bool,
) -> None:
    assert payload["ok"] is ok
    assert payload["command"] == "memory"
    assert payload["action"] == action
    assert payload["mode"] == mode
    assert payload["executed"] is executed


def test_plugins_command_module_importable() -> None:
    from thomas.cli.commands.plugins import p113_plugin_tool_provider_injection as mod

    assert hasattr(mod, "COMMAND_NAME")
    assert mod.COMMAND_NAME == "p113-tool-provider-injection"


def test_claude_style_alias_commands_are_registered() -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    for name in ("plugin", "mcp", "install", "setup-token"):
        assert name in root.commands


def test_install_compat_json_contract(tmp_path: Path) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    res = runner.invoke(root, ["install", "--compat-json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["command"] == "install"
    assert payload["compatibility"] == "mapped"
    assert "setup" in payload["equivalents"]


def test_mcp_registry_add_get_remove_roundtrip(tmp_path: Path) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    res_add = runner.invoke(
        root,
        ["mcp", "add", "demo", "--command", "uvx", "--arg", "mcp-server-time", "--json"],
        obj={"config": cfg},
    )
    assert res_add.exit_code == 0, res_add.output
    add_payload = json.loads(res_add.output)
    assert add_payload["ok"] is True
    assert add_payload["server"]["name"] == "demo"
    assert add_payload["server"]["transport"] == "stdio"

    res_get = runner.invoke(root, ["mcp", "get", "demo", "--json"], obj={"config": cfg})
    assert res_get.exit_code == 0, res_get.output
    get_payload = json.loads(res_get.output)
    assert get_payload["name"] == "demo"
    assert get_payload["command"] == "uvx"

    res_remove = runner.invoke(root, ["mcp", "remove", "demo", "--json"], obj={"config": cfg})
    assert res_remove.exit_code == 0, res_remove.output
    remove_payload = json.loads(res_remove.output)
    assert remove_payload["ok"] is True


def test_setup_token_persists_masked_metadata_only(tmp_path: Path, monkeypatch) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    token = "sk-ant-abcdef1234567890"
    res = runner.invoke(
        root,
        ["setup-token", "--provider", "anthropic", "--token", token, "--json"],
        obj={"config": cfg},
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["provider"] == "anthropic"
    assert payload["env_key"] == "ANTHROPIC_API_KEY"

    state_path = Path(str(payload["state_file"]))
    assert state_path.exists()
    raw = state_path.read_text(encoding="utf-8")
    assert token not in raw
    saved = json.loads(raw)
    row = saved["tokens"]["anthropic"]
    assert row["token_sha256"]
    assert "..." in row["token_masked"]


def test_skills_pin_show_unpin_and_analytics(tmp_path: Path, monkeypatch) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    codex_home = tmp_path / "codex-home"
    skill_name = "__unit_test_skill_alpha__"
    skill_dir = codex_home / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Unit Test Skill\nSkill for parity CLI tests.\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    sync = runner.invoke(root, ["skills", "sync", "--json"], obj={"config": cfg})
    assert sync.exit_code == 0, sync.output
    sync_payload = json.loads(sync.output)
    assert int(sync_payload["count"]) >= 1

    pin = runner.invoke(root, ["skills", "pin", skill_name, "--json"], obj={"config": cfg})
    assert pin.exit_code == 0, pin.output
    pin_payload = json.loads(pin.output)
    assert pin_payload["ok"] is True

    show = runner.invoke(root, ["skills", "show", skill_name, "--json"], obj={"config": cfg})
    assert show.exit_code == 0, show.output
    show_payload = json.loads(show.output)
    assert int(show_payload["match_count"]) >= 1
    assert any(bool(row.get("pinned")) for row in show_payload["entries"])

    analytics = runner.invoke(root, ["skills", "analytics", "--json"], obj={"config": cfg})
    assert analytics.exit_code == 0, analytics.output
    analytics_payload = json.loads(analytics.output)
    assert analytics_payload["ok"] is True
    assert int(analytics_payload["total_skills"]) >= 1
    assert int(analytics_payload["total_runs"]) >= 1

    unpin = runner.invoke(root, ["skills", "unpin", skill_name, "--json"], obj={"config": cfg})
    assert unpin.exit_code == 0, unpin.output
    unpin_payload = json.loads(unpin.output)
    assert unpin_payload["ok"] is True


def test_skills_conflicts_and_check_report_duplicates(tmp_path: Path, monkeypatch) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    codex_home = tmp_path / "codex-home"
    conflict_name = "__unit_test_skill_conflict__"
    first = codex_home / "skills" / "team_a" / conflict_name
    second = codex_home / "skills" / "team_b" / conflict_name
    first.mkdir(parents=True, exist_ok=True)
    second.mkdir(parents=True, exist_ok=True)
    (first / "SKILL.md").write_text("# Team A\nConflict test.\n", encoding="utf-8")
    (second / "SKILL.md").write_text("# Team B\nConflict test.\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    conflicts = runner.invoke(root, ["skills", "conflicts", "--json"], obj={"config": cfg})
    assert conflicts.exit_code == 0, conflicts.output
    conflict_payload = json.loads(conflicts.output)
    names = {str(item.get("name") or "") for item in conflict_payload.get("conflicts", [])}
    assert conflict_name.lower() in names

    check = runner.invoke(root, ["skills", "check", "--json"], obj={"config": cfg})
    assert check.exit_code == 1, check.output
    check_payload = json.loads(check.output)
    assert check_payload["ok"] is False
    codes = {str(item.get("code") or "") for item in check_payload.get("issues", [])}
    assert "name_conflict" in codes


def test_skills_resolve_returns_runtime_selection(tmp_path: Path, monkeypatch) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    home_root = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    home_root.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)
    skill_name = "__unit_test_skill_runtime_resolve__"
    skill_dir = codex_home / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Runtime Resolve\n- Apply this skill when requested.\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)

    prompt = f"please use ${skill_name} on this turn"
    resolved = runner.invoke(root, ["skills", "resolve", "--prompt", prompt, "--json"], obj={"config": cfg})
    assert resolved.exit_code == 0, resolved.output
    payload = json.loads(resolved.output)
    assert int(payload.get("selected_count", 0) or 0) >= 1
    selected_names = {str(row.get("name") or "") for row in payload.get("selected") or []}
    assert skill_name in selected_names
    assert "--- Runtime Skills ---" in str(payload.get("context") or "")


def _block_memory_backend_imports(monkeypatch) -> None:  # noqa: ANN001
    import thomas.cli.parity_compat as parity_compat

    blocked = {
        "thomas.memory.search",
        "thomas.memory.indexer",
        "thomas.memory.compaction",
    }
    original_import_module = parity_compat.importlib.import_module

    def _patched_import_module(name: str, package: str | None = None):  # noqa: ANN001
        if name in blocked:
            raise ModuleNotFoundError(f"blocked import for parity memory test: {name}", name=name)
        return original_import_module(name, package)

    monkeypatch.setattr(parity_compat.importlib, "import_module", _patched_import_module)


def test_memory_help_lists_stable_operational_actions(tmp_path: Path) -> None:
    root, runner, cfg = _memory_cli_context(tmp_path)

    res = runner.invoke(root, ["memory", "--help"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    for action in ("status", "list", "search", "index", "compact"):
        assert action in res.output


def test_memory_status_json_remains_operational(tmp_path: Path) -> None:
    root, runner, cfg = _memory_cli_context(tmp_path)

    res = runner.invoke(root, ["memory", "status", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["root"].endswith(".thomas")
    assert "chat_files" in payload


def test_memory_operational_actions_default_to_describe_mode(tmp_path: Path) -> None:
    root, runner, cfg = _memory_cli_context(tmp_path)

    cases = (
        (["memory", "search", "test", "--json"], "search"),
        (["memory", "list", "--json"], "list"),
        (["memory", "index", "--json"], "index"),
        (["memory", "compact", "--json"], "compact"),
    )
    for argv, action in cases:
        res = runner.invoke(root, argv, obj={"config": cfg})
        assert res.exit_code == 0, res.output
        payload = json.loads(res.output)
        _assert_memory_payload(payload, action=action, mode="describe", ok=False, executed=False)
        assert "run_hint" in payload


def test_memory_operational_actions_run_mode_fail_structured_non_zero(tmp_path: Path, monkeypatch) -> None:
    _block_memory_backend_imports(monkeypatch)
    root, runner, cfg = _memory_cli_context(tmp_path)

    cases = (
        (["memory", "search", "test", "--run", "--json"], "search"),
        (["memory", "list", "--run", "--json"], "list"),
        (["memory", "index", "--run", "--json"], "index"),
        (["memory", "compact", "--run", "--json"], "compact"),
    )
    for argv, action in cases:
        res = runner.invoke(root, argv, obj={"config": cfg})
        assert res.exit_code == 2, res.output
        payload = json.loads(res.output)
        _assert_memory_payload(payload, action=action, mode="run", ok=False, executed=False)
        error = payload["error"]
        assert error["category"] == "not_implemented"
        assert error["code"] == "memory_operation_not_implemented"
        assert "no executable backend implementation" in error["message"]
        assert "hint" in error


def test_memory_search_run_mode_distinguishes_nested_import_failure(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.parity_compat as parity_compat

    root, runner, cfg = _memory_cli_context(tmp_path)
    original_import_module = parity_compat.importlib.import_module

    def _patched_import_module(name: str, package: str | None = None):  # noqa: ANN001
        if name == "thomas.memory.search":
            raise ModuleNotFoundError("No module named 'missing_dependency'", name="missing_dependency")
        return original_import_module(name, package)

    monkeypatch.setattr(parity_compat.importlib, "import_module", _patched_import_module)

    res = runner.invoke(root, ["memory", "search", "test", "--run", "--json"], obj={"config": cfg})
    assert res.exit_code == 1, res.output
    payload = json.loads(res.output)
    _assert_memory_payload(payload, action="search", mode="run", ok=False, executed=False)
    error = payload["error"]
    assert error["category"] == "runtime_error"
    assert error["code"] == "memory_operation_failed"
