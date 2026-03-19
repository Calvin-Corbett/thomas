from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import click
from click.testing import CliRunner

import thomas.cli.agents_runtime as agents_runtime
import thomas.cli.parity_commands as parity_commands
from thomas.cli.parity_commands import register_parity_commands
from thomas.cli.parity_compat import register_compat_commands


def _build_root_cli() -> click.Group:
    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        _ = ctx

    return root


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        embed=SimpleNamespace(
            provider="local",
            model="all-MiniLM-L6-v2",
            device="cpu",
            load_on_demand=True,
            batch_size=8,
        ),
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


def _parity_cli_context(tmp_path: Path) -> tuple[click.Group, CliRunner, SimpleNamespace]:
    root = _build_root_cli()
    register_parity_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)
    return root, runner, cfg


def _seed_legacy_memory_event(cfg: SimpleNamespace, *, text: str) -> None:
    from thomas.memory import MemoryEngine

    engine = MemoryEngine(cfg)
    engine.start()
    try:
        engine.add_event("thread-test", "user_message", text)
        engine.ingest_pending()
    finally:
        engine.close()


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


def test_agents_start_detached_records_gateway_state(tmp_path: Path, monkeypatch) -> None:
    root, runner, cfg = _parity_cli_context(tmp_path)

    monkeypatch.setattr(agents_runtime, "_resolve_bind_port", lambda host, port, auto_port: int(port))
    monkeypatch.setattr(agents_runtime, "_is_pid_running", lambda pid: int(pid) == 4242)
    call_state = {"count": 0}

    def _fake_probe_gateway(host: str, port: int, token: str = "") -> dict[str, object]:
        call_state["count"] += 1
        if call_state["count"] == 1:
            return {"healthy": False, "engines": {"ok": False, "payload": {}}}
        return {
            "healthy": True,
            "engines": {
                "ok": True,
                "payload": {"running": True, "engines": {"workspace_sync_engine": {"running": True}}},
            },
        }

    monkeypatch.setattr(
        agents_runtime,
        "_probe_gateway",
        _fake_probe_gateway,
    )
    monkeypatch.setattr(agents_runtime, "_gateway_spawn", lambda **_kwargs: SimpleNamespace(pid=4242))
    monkeypatch.setattr(agents_runtime.time, "sleep", lambda _seconds: None)

    res = runner.invoke(root, ["agents", "start", "--json"], obj={"config": cfg, "config_path": ""})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["mode"] == "gateway_detached"
    assert payload["pid"] == 4242

    state_path = tmp_path / ".thomas" / "cli" / "gateway_state.json"
    assert state_path.exists()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert int(saved["pid"]) == 4242


def test_agents_status_prefers_detached_runtime_when_gateway_running(tmp_path: Path, monkeypatch) -> None:
    root, runner, cfg = _parity_cli_context(tmp_path)
    state_path = tmp_path / ".thomas" / "cli" / "gateway_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8899, "log_file": str(tmp_path / "gateway.log")}),
        encoding="utf-8",
    )

    monkeypatch.setattr(agents_runtime, "_is_pid_running", lambda pid: int(pid) == 4242)
    monkeypatch.setattr(
        agents_runtime,
        "_probe_gateway",
        lambda host, port, token="": {
            "healthy": True,
            "engines": {
                "ok": True,
                "payload": {"running": True, "engines": {"workspace_sync_engine": {"running": True}}},
            },
        },
    )

    res = runner.invoke(root, ["agents", "status", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["running"] is True
    assert payload["source"] == "gateway_detached"
    assert "workspace_sync_engine" in payload["engines"]


def test_agents_start_detects_existing_external_gateway(tmp_path: Path, monkeypatch) -> None:
    root, runner, cfg = _parity_cli_context(tmp_path)

    monkeypatch.setattr(
        agents_runtime,
        "_probe_gateway",
        lambda host, port, token="": {
            "healthy": True,
            "engines": {"ok": True, "payload": {"running": True, "engines": {}}},
        },
    )

    res = runner.invoke(root, ["agents", "start", "--json"], obj={"config": cfg, "config_path": ""})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["already_running"] is True
    assert payload["external_runtime"] is True
    assert payload["pid"] == 0


def test_agents_stop_detached_kills_pid_and_clears_state(tmp_path: Path, monkeypatch) -> None:
    root, runner, cfg = _parity_cli_context(tmp_path)
    state_path = tmp_path / ".thomas" / "cli" / "gateway_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8899}), encoding="utf-8")

    state = {"running": True}

    def _fake_is_pid_running(pid: int) -> bool:
        return bool(int(pid) == 4242 and state["running"])

    def _fake_kill_pid(pid: int) -> bool:
        if int(pid) == 4242:
            state["running"] = False
            return True
        return False

    monkeypatch.setattr(agents_runtime, "_is_pid_running", _fake_is_pid_running)
    monkeypatch.setattr(agents_runtime, "_kill_pid", _fake_kill_pid)

    res = runner.invoke(root, ["agents", "stop", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["mode"] == "gateway_detached"
    assert payload["pid"] == 4242
    assert payload["killed"] is True
    assert not state_path.exists()


def test_agents_stop_reports_external_untracked_runtime(tmp_path: Path, monkeypatch) -> None:
    root, runner, cfg = _parity_cli_context(tmp_path)
    monkeypatch.setattr(
        agents_runtime,
        "_probe_gateway",
        lambda host, port, token="": {"healthy": True, "engines": {"ok": True, "payload": {}}},
    )

    res = runner.invoke(root, ["agents", "stop", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is False
    assert payload["mode"] == "gateway_detached"
    assert "external/untracked" in payload["error"]


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
    assert "<runtime_skills" in str(payload.get("context") or "")


def _block_memory_backend_imports(monkeypatch) -> None:  # noqa: ANN001
    import thomas.cli.parity_compat as parity_compat

    blocked = {
        "thomas.memory.search",
        "thomas.memory.listing",
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


def test_memory_search_run_mode_success_contract(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.parity_compat as parity_compat

    root, runner, cfg = _memory_cli_context(tmp_path)

    def _fake_search(_config, query: str, limit: int):  # noqa: ANN001
        return [{"id": "m1", "text": f"hit:{query}:{limit}"}]

    monkeypatch.setattr(
        parity_compat,
        "_resolve_memory_backend",
        lambda *_args, **_kwargs: (_fake_search, None),
    )

    res = runner.invoke(root, ["memory", "search", "needle", "--run", "--limit", "5", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    _assert_memory_payload(payload, action="search", mode="run", ok=True, executed=True)
    assert payload["query"] == "needle"
    assert payload["count"] == 1
    assert payload["results"][0]["id"] == "m1"


def test_memory_index_run_mode_success_contract(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.parity_compat as parity_compat

    root, runner, cfg = _memory_cli_context(tmp_path)

    def _fake_index(_config):  # noqa: ANN001
        return {"ok": True, "indexed": 42}

    monkeypatch.setattr(
        parity_compat,
        "_resolve_memory_backend",
        lambda *_args, **_kwargs: (_fake_index, None),
    )

    res = runner.invoke(root, ["memory", "index", "--run", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    _assert_memory_payload(payload, action="index", mode="run", ok=True, executed=True)
    assert payload["indexed"] == 42


def test_memory_run_mode_real_backends_execute(tmp_path: Path) -> None:
    root, runner, cfg = _memory_cli_context(tmp_path)
    _seed_legacy_memory_event(cfg, text="compat query needle alpha")

    search = runner.invoke(root, ["memory", "search", "needle", "--run", "--json"], obj={"config": cfg})
    assert search.exit_code == 0, search.output
    search_payload = json.loads(search.output)
    _assert_memory_payload(search_payload, action="search", mode="run", ok=True, executed=True)
    assert int(search_payload["count"]) >= 1

    listing = runner.invoke(root, ["memory", "list", "--run", "--json"], obj={"config": cfg})
    assert listing.exit_code == 0, listing.output
    listing_payload = json.loads(listing.output)
    _assert_memory_payload(listing_payload, action="list", mode="run", ok=True, executed=True)
    assert "snapshots" in listing_payload

    index = runner.invoke(root, ["memory", "index", "--run", "--json"], obj={"config": cfg})
    assert index.exit_code == 0, index.output
    index_payload = json.loads(index.output)
    _assert_memory_payload(index_payload, action="index", mode="run", ok=True, executed=True)
    assert "ingest" in index_payload

    compact = runner.invoke(root, ["memory", "compact", "--run", "--json"], obj={"config": cfg})
    assert compact.exit_code == 0, compact.output
    compact_payload = json.loads(compact.output)
    _assert_memory_payload(compact_payload, action="compact", mode="run", ok=True, executed=True)
    assert "global" in compact_payload


def test_gateway_run_json_suppresses_auto_port_banner(tmp_path: Path, monkeypatch) -> None:
    root, runner, cfg = _parity_cli_context(tmp_path)

    def _fake_resolve_bind_port(host: str, port: int, auto_port: bool, *, announce=None) -> int:
        assert callable(announce) is False
        return int(port) + 1

    monkeypatch.setattr(parity_commands, "_resolve_bind_port", _fake_resolve_bind_port)
    monkeypatch.setattr(parity_commands, "_load_gateway_state", lambda config: {})
    monkeypatch.setattr(parity_commands, "_is_pid_running", lambda pid: int(pid) == 4242)
    monkeypatch.setattr(parity_commands, "_gateway_spawn", lambda **_kwargs: SimpleNamespace(pid=4242))
    monkeypatch.setattr(parity_commands, "_probe_gateway", lambda host, port, token="": {"healthy": True})
    monkeypatch.setattr(parity_commands, "_save_gateway_state", lambda config, payload: None)
    monkeypatch.setattr(parity_commands.time, "sleep", lambda _seconds: None)

    res = runner.invoke(root, ["gateway", "run", "--json"], obj={"config": cfg, "config_path": ""})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["port"] == 8900
    assert "auto-selecting" not in res.output
