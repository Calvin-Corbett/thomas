from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.chat.memory_layers import MemoryCoordinator
from thomas.core.config import AppConfig, ModelConfig, ToolsConfig
from thomas.preferences.store import PreferencesPatch, PreferencesStore
from thomas.server.chat_runtime_policy import (
    ChatRuntimePolicyError,
    PolicyToolRegistryView,
    ToolRuntimePolicy,
    resolve_chat_runtime_policy,
)
from thomas.server.chat_tool_policy import _is_classified_tool
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _ProbeTool(Tool):
    def __init__(self, name: str) -> None:
        self.name = name
        self.category = name.split(".", 1)[0]
        self.description = "policy probe"
        self.parameters = {"type": "object", "properties": {}}
        self.calls: list[dict] = []

    async def execute(self, args: dict) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(ok=True, data="ok")


@pytest.fixture
def policy_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={
            "local": ModelConfig(
                name="local",
                provider="openai_compat",
                base_url="http://127.0.0.1:11434/v1",
                model="local-model",
            ),
            "remote": ModelConfig(
                name="remote",
                provider="openai_compat",
                base_url="https://api.example.com/v1",
                model="remote-model",
            ),
        },
        default_model="local",
        tools=ToolsConfig(sandbox_root=str(tmp_path)),
    )


def _save_preferences(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, patch: dict) -> None:
    db_path = tmp_path / "preferences.sqlite"
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))
    store = PreferencesStore(str(db_path))
    store.patch(PreferencesPatch.model_validate(patch), user_id="default", thread_id="session-1")


def test_cumulative_token_throttle_is_opt_in_and_legacy_defaults_migrate(tmp_path: Path) -> None:
    db_path = tmp_path / "preferences.sqlite"
    store = PreferencesStore(str(db_path))
    assert store.get().advanced.cost.throttle_on_budget is False

    legacy_patch = PreferencesPatch.model_validate(
        {
            "advanced": {
                "cost": {
                    "session_token_budget": 200_000,
                    "daily_token_budget": 2_000_000,
                    "throttle_on_budget": True,
                }
            }
        }
    )
    custom_patch = PreferencesPatch.model_validate(
        {
            "advanced": {
                "cost": {
                    "session_token_budget": 123_456,
                    "daily_token_budget": 2_000_000,
                    "throttle_on_budget": True,
                }
            }
        }
    )
    store.patch(legacy_patch, user_id="legacy")
    store.patch(custom_patch, user_id="custom")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM preferences_meta WHERE k = ?", ("token_throttle_opt_in_v019",))

    migrated = PreferencesStore(str(db_path))
    assert migrated.get(user_id="legacy").advanced.cost.throttle_on_budget is False
    assert migrated.get(user_id="custom").advanced.cost.throttle_on_budget is True

    migrated.patch(legacy_patch, user_id="legacy")
    assert PreferencesStore(str(db_path)).get(user_id="legacy").advanced.cost.throttle_on_budget is True


def test_token_throttle_migration_retries_malformed_rows_with_identity(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db_path = tmp_path / "preferences.sqlite"
    PreferencesStore(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM preferences_meta WHERE k = ?", ("token_throttle_opt_in_v019",))
        conn.execute(
            "INSERT OR REPLACE INTO preferences (user_id, data_json, updated_at) VALUES (?, ?, ?)",
            ("broken-profile", "{not-json", "2026-07-18T00:00:00+00:00"),
        )

    with caplog.at_level("WARNING"):
        PreferencesStore(str(db_path))

    assert "broken-profile" in caplog.text
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM preferences_meta WHERE k = ?",
                ("token_throttle_opt_in_v019",),
            ).fetchone()
            is None
        )
        conn.execute("DELETE FROM preferences WHERE user_id = ?", ("broken-profile",))

    PreferencesStore(str(db_path))
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM preferences_meta WHERE k = ?",
                ("token_throttle_opt_in_v019",),
            ).fetchone()
            is not None
        )


def test_resolver_applies_saved_model_runtime_memory_and_quality(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy_config: AppConfig,
) -> None:
    _save_preferences(
        monkeypatch,
        tmp_path,
        {
            "autonomy": {"default_level": "L4"},
            "profile": {"profile_type": "non_coder", "review_depth": "technical"},
            "advanced": {
                "model": {
                    "active_profile": "local",
                    "model_id": "saved-model",
                    "temperature": 1.2,
                    "top_p": 0.42,
                    "max_output_tokens": 1024,
                    "reasoning_effort": "high",
                    "frequency_penalty": 0.4,
                    "presence_penalty": 0.3,
                    "json_mode": True,
                    "deterministic_seed": 99,
                    "stop_sequences": "END\nDONE",
                },
                "tools": {"allow_shell": False, "allow_file_write": False, "max_parallel_tools": 2},
                "memory": {
                    "include_thread_memory": False,
                    "include_global_memory": True,
                    "include_profile_memory": False,
                    "pins_only": True,
                    "retrieval_top_k": 3,
                    "pinned_context": "Always return concise summaries.",
                },
                "cost": {
                    "max_retries": 4,
                    "retry_backoff_ms": 1200,
                    "model_failover_chain": "remote",
                },
                "runtime": {"default_mode": "thinking", "default_token_economy": "max"},
            },
        },
    )
    meta = SimpleNamespace(profile="", model_id=None, autonomy_level=2, system_prompt=None)
    policy = resolve_chat_runtime_policy(
        payload={},
        session_meta=meta,
        saved_meta=None,
        config=policy_config,
        session_id="session-1",
    )

    assert policy.profile == "local"
    assert policy.model_id == "saved-model"
    assert policy.autonomy_level == 4
    assert policy.mode == "thinking"
    assert policy.token_economy == "max"
    assert policy.model.temperature == pytest.approx(1.2)
    assert policy.model.top_p == pytest.approx(0.42)
    assert policy.model.max_output_tokens == 1024
    assert policy.model.max_retries == 5
    assert policy.model.retry_backoff_s == pytest.approx(1.2)
    assert policy.model.request_overrides == {
        "frequency_penalty": 0.4,
        "presence_penalty": 0.3,
        "json_mode": True,
        "seed": 99,
        "stop": ["END", "DONE"],
    }
    assert not policy.tools.allow_shell
    assert not policy.tools.allow_file_write
    assert policy.tools.max_parallel_tools == 2
    assert not policy.memory.include_thread
    assert not policy.memory.include_profile
    assert policy.memory.pins_only
    assert policy.memory.retrieval_top_k == 3
    assert "Always return concise summaries." in policy.instruction_context()
    assert policy.non_coder_profile
    assert policy.quality.enforce
    assert policy.quality.require_tests_for_code_edits


def test_local_only_rejects_remote_endpoint_and_request_cannot_widen_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy_config: AppConfig,
) -> None:
    _save_preferences(
        monkeypatch,
        tmp_path,
        {"advanced": {"privacy": {"local_only_mode": True}, "tools": {"allow_network": True}}},
    )
    meta = SimpleNamespace(profile="", model_id=None, autonomy_level=2, system_prompt=None)
    with pytest.raises(PermissionError, match="local_only_mode"):
        resolve_chat_runtime_policy(
            payload={"profile": "remote", "external_access": True},
            session_meta=meta,
            saved_meta=None,
            config=policy_config,
            session_id="session-1",
        )

    local = resolve_chat_runtime_policy(
        payload={"profile": "local", "external_access": True},
        session_meta=meta,
        saved_meta=None,
        config=policy_config,
        session_id="session-1",
    )
    assert local.local_only
    assert not local.tools.allow_network
    assert not local.tools.allow_browser
    assert not local.tools.allow_channels


def test_resolver_fails_closed_when_preferences_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    policy_config: AppConfig,
) -> None:
    class _UnavailablePreferencesStore:
        def __init__(self, _db_path: str) -> None:
            pass

        def get(self, *, user_id: str, thread_id: str) -> None:
            raise OSError(f"preferences unavailable for {user_id}/{thread_id}")

    monkeypatch.setattr("thomas.preferences.store.PreferencesStore", _UnavailablePreferencesStore)
    meta = SimpleNamespace(profile="", model_id=None, autonomy_level=2, system_prompt=None)

    with pytest.raises(ChatRuntimePolicyError, match="Saved chat safety preferences are unavailable"):
        resolve_chat_runtime_policy(
            payload={"profile": "local"},
            session_meta=meta,
            saved_meta=None,
            config=policy_config,
            session_id="session-1",
        )


def test_remote_endpoint_cannot_claim_local_provider_name() -> None:
    from thomas.server.chat_runtime_policy import model_endpoint_is_local

    assert not model_endpoint_is_local(SimpleNamespace(provider="ollama", base_url="https://remote.example.com/v1"))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["shell.exec", "functions.shell.exec", "mcp__shell.exec"])
async def test_command_approval_blocks_namespaced_shell_at_every_autonomy(name: str, tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_ProbeTool("shell.exec"))
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=True,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    result = await PolicyToolRegistryView(registry, policy, base_root=tmp_path).execute(
        name,
        {"command": "echo hi"},
    )
    assert not result.ok
    assert "require_command_approval" in str(result.error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("workspace/inside.txt", True),
        ("workspace/../outside.txt", False),
        ("workspace_evil/inside.txt", False),
        ("../outside.txt", False),
    ],
)
async def test_allowed_path_policy_resolves_traversal_and_prefix_collisions(
    path: str,
    allowed: bool,
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    probe = _ProbeTool("fs.read_file")
    registry.register(probe)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=False,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    result = await PolicyToolRegistryView(registry, policy, base_root=tmp_path).execute(
        "fs.read_file",
        {"path": path},
    )
    assert bool(result.ok) is allowed
    assert bool(probe.calls) is allowed


@pytest.mark.asyncio
async def test_allowed_path_policy_keeps_filesystem_tools_visible_until_execution(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_ProbeTool("fs.read_file"))
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=False,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert view.get("fs.read_file") is not None
    assert [tool.name for tool in view.list_tools()] == ["fs.read_file"]
    denied = await view.execute("fs.read_file", {"path": "outside.txt"})
    assert not denied.ok


@pytest.mark.asyncio
async def test_allowed_paths_scope_non_fs_local_path_tools_and_path_lists(tmp_path: Path) -> None:
    registry = ToolRegistry()
    tools = {
        name: _ProbeTool(name)
        for name in (
            "code.search",
            "library_list_entries",
            "notifications_list",
            "upgrade_get_paths",
            "git.commit",
        )
    }
    for tool in tools.values():
        registry.register(tool)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    cases = (
        ("code.search", {"path": "outside/code.py"}),
        ("library_list_entries", {"library_root": "outside/library"}),
        ("notifications_list", {"store_path": "outside/notifications.json"}),
        ("upgrade_get_paths", {"project_root": "outside/project"}),
        ("git.commit", {"message": "unsafe", "files": ["workspace/inside.py", "outside/code.py"]}),
    )
    for name, args in cases:
        result = await view.execute(name, args)
        assert not result.ok
        assert "allowed_paths" in str(result.error)
        assert not tools[name].calls

    allowed = await view.execute(
        "git.commit",
        {"message": "safe", "files": ["workspace/one.py", "workspace/two.py"]},
    )
    assert allowed.ok
    assert tools["git.commit"].calls
    assert (await view.execute("code.search", {"path": "workspace/src"})).ok

    implicit_repo_commit = await view.execute("git.commit", {"message": "unsafe", "all_staged": True})
    assert not implicit_repo_commit.ok
    assert "allowed_paths" in str(implicit_repo_commit.error)


@pytest.mark.asyncio
async def test_allowed_paths_do_not_treat_semantic_source_target_or_connector_ids_as_paths(tmp_path: Path) -> None:
    registry = ToolRegistry()
    tools = [_ProbeTool("data_load"), _ProbeTool("flow_design"), _ProbeTool("email.read")]
    for tool in tools:
        registry.register(tool)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert (await view.execute("data_load", {"source": "inline,csv,data"})).ok
    assert (await view.execute("flow_design", {"source": "node-a", "target": "node-b"})).ok
    assert (await view.execute("email.read", {"folder": "Inbox"})).ok


@pytest.mark.asyncio
async def test_allowed_paths_fail_closed_for_unclassified_tool_even_when_capabilities_are_enabled(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    probe = _ProbeTool("future.plugin.read_local")
    registry.register(probe)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert view.get(probe.name) is None
    result = await view.execute(probe.name, {"path": "workspace/readme.md"})
    assert not result.ok
    assert "allowed_paths" in str(result.error)
    assert not probe.calls


@pytest.mark.asyncio
async def test_actual_registry_local_path_tools_are_stopped_before_out_of_scope_execution(
    policy_config: AppConfig,
    tmp_path: Path,
) -> None:
    from thomas.server.app_helpers import _build_tools

    registry = _build_tools(policy_config)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)
    cases = (
        ("code.search", {"pattern": "secret", "path": "outside"}),
        ("library_list_entries", {"library_root": "outside"}),
        ("notifications_list", {"store_path": "outside/notifications.json"}),
        ("upgrade_get_paths", {"project_root": "outside"}),
        ("git.commit", {"message": "unsafe", "files": ["workspace/ok.py", "outside/no.py"]}),
    )

    for name, args in cases:
        assert registry.get(name) is not None
        result = await view.execute(name, args)
        assert not result.ok
        assert "allowed_paths" in str(result.error)


def test_channel_policy_hides_email_connectors(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_ProbeTool("email.send"))
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=False,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )

    assert PolicyToolRegistryView(registry, policy, base_root=tmp_path).get("email.send") is None


@pytest.mark.asyncio
async def test_restrictive_policy_blocks_ssh_exec_and_diff_write(tmp_path: Path) -> None:
    registry = ToolRegistry()
    ssh = _ProbeTool("ssh.exec")
    diff = _ProbeTool("diff.create")
    registry.register(ssh)
    registry.register(diff)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=False,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=True,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=("rm -rf",),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert not (await view.execute("ssh.exec", {"command": "whoami"})).ok
    assert not (await view.execute("diff.create", {"path": "workspace/a.txt"})).ok
    assert not ssh.calls
    assert not diff.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "denial"),
    [
        ("create_skill", "allow_file_write"),
        ("eng.web_extract", "allow_network"),
        ("policy_create_config", "allow_file_write"),
        ("upgrade_sync_blue_to_green", "allow_shell"),
        ("channel_management", "allow_file_write"),
    ],
)
async def test_restrictive_policy_hides_and_rejects_unprefixed_capabilities(
    name: str,
    denial: str,
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    probe = _ProbeTool(name)
    registry.register(probe)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=False,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert view.get(name) is None
    assert name not in {tool.name for tool in view.list_tools()}
    result = await view.execute(name, {})
    assert not result.ok
    assert denial in str(result.error)
    assert not probe.calls


@pytest.mark.asyncio
async def test_restrictive_policy_fails_closed_for_future_unclassified_tool(tmp_path: Path) -> None:
    registry = ToolRegistry()
    probe = _ProbeTool("future.plugin.action")
    registry.register(probe)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert view.get(probe.name) is None
    result = await view.execute(probe.name, {})
    assert not result.ok
    assert "unclassified" in str(result.error)
    assert not probe.calls


def test_registered_core_tools_have_explicit_policy_classification(
    policy_config: AppConfig,
    tmp_path: Path,
) -> None:
    """Thomas's own core tool surface is classified; every other tool fails closed.

    Measured on dev 2026-07-31. ``_build_tools`` registers 566 tools: 30 core
    ones it registers itself (filesystem, shell, git, code search, diff, ssh,
    browser, web research, runtime skills) plus 536 from
    ``register_all_optional_tools`` -- the marketplace domain modules.

    This test used to assert ``unclassified == []`` across all 566 and was red
    from the commit that introduced it (a5324a3b, the 0.19.0 squash): 426
    unclassified, 424 of them marketplace domain tools (``audio_mixer``,
    ``bioinformatics_blast``, ``crm.create_contact``, ...) that the hand-curated
    catalog in ``chat_tool_policy_model.py`` has never enumerated. A permanently
    red assertion guards nothing, and enumerating 536 domain tools by name is not
    what that catalog is for.

    Being absent from the catalog is never a permission hole: ``_tool_denial``
    denies an unclassified tool the moment ANY capability is off, so a stranger
    is strictly the most restrictive case -- which the two tests above
    (``..._fails_closed_for_future_unclassified_tool`` and
    ``test_allowed_paths_fail_closed_for_unclassified_tool_...``) pin for a
    single probe. The cost of being unclassified is over-blocking. So the
    contract measured here is the one the test name always claimed -- the CORE
    surface must be classified explicitly -- plus the stranger rule applied to
    the whole real registry rather than one probe.

    Core unclassified before this change: ``['skills.list', 'skills.use']``
    (2 of 30). After: 0 of 30. Both only read local skill files;
    ``thomas/marketplace/specialists/reasoning.py`` already lists them under
    "Read-only filesystem tools ... NEVER write/shell", so they are
    ``_SAFE_READ_TOOLS``. Strangers still hidden under one disabled capability:
    424 of 424.
    """
    from thomas.server.app_helpers import _build_tools
    from thomas.server.tool_extensions import register_all_optional_tools

    optional_registry = ToolRegistry()
    register_all_optional_tools(optional_registry)
    optional_names = {tool.name for tool in optional_registry.list_tools()}

    registry = _build_tools(policy_config)
    registered = [tool.name for tool in registry.list_tools()]
    core_names = [name for name in registered if name not in optional_names]

    # Never let the core surface pass by being empty: fs/shell/git/code/diff/web
    # alone are more than 20 tools, so a vacuous subtraction fails here first.
    assert len(core_names) > 20, core_names
    assert [name for name in core_names if not _is_classified_tool(name)] == []

    # Everything the catalog does not name must actually fail closed, not merely
    # be undescribed. One disabled capability has to hide all of them.
    network_off = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=False,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, network_off, base_root=tmp_path)
    strangers = [name for name in registered if not _is_classified_tool(name)]
    assert strangers, "no unclassified tools left -- rewrite this half of the test"
    assert [name for name in strangers if view.get(name) is not None] == []


@pytest.mark.asyncio
async def test_the_skill_tools_stay_available_when_only_network_is_switched_off(
    policy_config: AppConfig,
    tmp_path: Path,
) -> None:
    """Turning off network must not take local skill discovery with it.

    ``skills.list`` and ``skills.use`` read skill files off the local disk and
    return their text; they reach no network and execute nothing. They were
    missing from the policy catalog, so ``_tool_denial`` treated them as
    unclassified and denied them as soon as any capability was disabled.

    Measured on dev 2026-07-31 with the real ``_build_tools`` registry and the
    policy ``resolve_chat_runtime_policy`` produces for local-only mode
    (network/browser/channels off, everything else on):

        before  skills.list visible=False  skills.use visible=False
                error: "allow_network policy denied unclassified tool capability"
        after   skills.list visible=True   skills.use visible=True

    Controls, unchanged in both runs: ``fs.read_file`` and ``code.search`` stayed
    visible (so the run can show success), and ``web.search`` stayed hidden (so
    ``allow_network`` still bites). Model-owned skill selection -- the whole
    point of 69bbbab0 -- was dead in privacy mode until this landed.
    """
    from thomas.server.app_helpers import _build_tools

    registry = _build_tools(policy_config)
    local_only = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, local_only, base_root=tmp_path)

    for name in ("skills.list", "skills.use", "fs.read_file", "code.search"):
        assert registry.get(name) is not None, f"{name} is not registered at all"
        assert view.get(name) is not None, f"{name} was hidden by an unrelated capability"

    # Control: the policy still bites where the capability really applies.
    assert registry.get("web.search") is not None
    assert view.get("web.search") is None

    result = await view.execute("skills.list", {})
    assert result.ok, result.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy_overrides", "denial"),
    [
        ({"allow_file_write": False}, "allow_file_write"),
        ({"allow_network": False}, "allow_network"),
    ],
)
async def test_shell_cannot_bypass_file_or_network_policy(
    policy_overrides: dict[str, bool],
    denial: str,
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    shell = _ProbeTool("shell.exec")
    registry.register(shell)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, replace(policy, **policy_overrides), base_root=tmp_path)

    assert view.get("shell.exec") is None
    result = await view.execute("shell.exec", {"command": "echo unsafe"})
    assert not result.ok
    assert denial in str(result.error)
    assert not shell.calls


@pytest.mark.asyncio
async def test_action_aware_ssh_policy_blocks_file_mutation_and_path_escape(tmp_path: Path) -> None:
    registry = ToolRegistry()
    ssh = _ProbeTool("ssh.exec")
    registry.register(ssh)
    read_only = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=False,
        allow_network=True,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    assert not (
        await PolicyToolRegistryView(registry, read_only, base_root=tmp_path).execute(
            "ssh.exec", {"action": "download", "local_path": "outside.txt"}
        )
    ).ok

    allowlisted = replace(read_only, allow_file_write=True, allowed_paths=("workspace",))
    view = PolicyToolRegistryView(registry, allowlisted, base_root=tmp_path)
    assert not (await view.execute("ssh.exec", {"action": "upload", "local_path": "outside.txt"})).ok
    assert (await view.execute("ssh.exec", {"action": "upload", "local_path": "workspace/inside.txt"})).ok
    assert not (
        await view.execute(
            "ssh.exec",
            {
                "action": "upload",
                "local_path": "workspace/inside.txt",
                "key_path": "../outside/id_ed25519",
            },
        )
    ).ok


@pytest.mark.asyncio
async def test_diff_policy_keeps_preview_readable_and_scopes_write_targets(tmp_path: Path) -> None:
    registry = ToolRegistry()
    preview = _ProbeTool("diff.preview")
    create = _ProbeTool("diff.create")
    patch = _ProbeTool("diff.apply_patch")
    for tool in (preview, create, patch):
        registry.register(tool)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=True,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert view.get("diff.preview") is not None
    assert not (await view.execute("diff.create", {"file": "outside.py"})).ok
    assert (await view.execute("diff.create", {"file": "workspace/inside.py"})).ok
    assert not (
        await view.execute(
            "diff.apply_patch",
            {"patch": "--- a/outside.py\n+++ b/outside.py\n@@ -1 +1 @@\n-a\n+b\n"},
        )
    ).ok
    assert (
        await view.execute(
            "diff.apply_patch",
            {"patch": "--- a/workspace/a.py\n+++ b/workspace/a.py\n@@ -1 +1 @@\n-a\n+b\n"},
        )
    ).ok


@pytest.mark.asyncio
async def test_blocked_command_policy_disables_shell_instead_of_parsing_obfuscation(tmp_path: Path) -> None:
    registry = ToolRegistry()
    shell = _ProbeTool("shell.exec")
    registry.register(shell)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=("curl",),
    )

    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)
    assert view.get("shell.exec") is None
    assert not (await view.execute("shell.exec", {"command": 'c""url https://example.com'})).ok
    assert not shell.calls


@pytest.mark.asyncio
async def test_memory_policy_does_not_query_disabled_scopes() -> None:
    class _Memory:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def retrieve(self, **kwargs):  # noqa: ANN003
            self.calls.append(dict(kwargs))
            return "secret memory"

    memory = _Memory()
    policy = SimpleNamespace(
        include_thread=False,
        include_global=True,
        include_profile=False,
        pins_only=False,
        context_budget=1200,
    )
    coordinator = MemoryCoordinator(memory, "session-1", policy=policy)
    conversation = SimpleNamespace(last_user_message=lambda: "hello", last_assistant_message=lambda: "")
    context = await coordinator.refresh(prompt="hello", conversation=conversation, iteration=0)
    assert not memory.calls
    assert not context.episodic
    assert not context.semantic
