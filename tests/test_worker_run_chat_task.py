from __future__ import annotations

from types import SimpleNamespace

import scripts.worker_run_chat_task as mod

from thomas.core import task_bot_runtime
from thomas.core.events import AgentEvent
from thomas.skills import create_skill_draft, promote_skill_draft, review_skill_draft


class _LLMStub:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.args = args
        self.kwargs = kwargs

    async def close(self) -> None:
        return None


class _ToolSpecialistStub:
    def __init__(self, config, llm, tools) -> None:  # noqa: ANN001
        self.config = config
        self.llm = llm
        self.tools = tools

    async def execute(self, contract, token, prompt, conversation_context, memory_context):  # noqa: ANN001
        _ = (contract, token, conversation_context)
        assert "--- Background Execution Guidance ---" in memory_context
        assert "Desktop" in prompt
        yield {"type": "tool_start", "name": "direct.write_file", "id": "direct.write_file"}
        yield {"type": "tool_result", "name": "direct.write_file", "id": "direct.write_file", "ok": True, "result": "OK"}
        yield {"type": "text", "text": "D:\\Desktop\\dispatch-proof.txt\nDISPATCH_OK"}
        yield {"type": "done", "content": "D:\\Desktop\\dispatch-proof.txt\nDISPATCH_OK"}


class _SkillAwareToolSpecialistStub:
    def __init__(self, config, llm, tools) -> None:  # noqa: ANN001
        self.config = config
        self.llm = llm
        self.tools = tools

    async def execute(self, contract, token, prompt, conversation_context, memory_context):  # noqa: ANN001
        _ = (contract, token, conversation_context)
        assert "--- Background Execution Guidance ---" in memory_context
        assert "calendar-reminder-native" in memory_context
        assert "--- Runtime Skills ---" in memory_context
        assert "Set a recurring weekday 9:00 AM reminder" in prompt
        yield {"type": "text", "text": "OK"}
        yield {"type": "done", "content": "OK"}


class _ArtifactOverrideToolSpecialistStub:
    def __init__(self, config, llm, tools) -> None:  # noqa: ANN001
        self.config = config
        self.llm = llm
        self.tools = tools

    async def execute(self, contract, token, prompt, conversation_context, memory_context):  # noqa: ANN001
        _ = (contract, token, conversation_context, memory_context)
        assert "Administrative task policy for this task: capability_class=artifact_only." in prompt
        assert token.allowed_actions == {"read", "write"}
        assert "task08_plugin_inventory.json" in prompt
        yield {"type": "text", "text": "task08_plugin_inventory.json was written."}
        yield {"type": "done", "content": "task08_plugin_inventory.json was written."}


class _SessionStoreStub:
    def __init__(self, path) -> None:  # noqa: ANN001
        self.path = path

    async def load(self, session_id):  # noqa: ANN001
        _ = session_id
        return None


def test_worker_run_chat_task_preserves_full_prompt_and_final_output(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "load_config", lambda: SimpleNamespace(
        default_model="local",
        models={"local": SimpleNamespace(name="local", model="dummy")},
        memory=SimpleNamespace(root_path=tmp_path),
        get_model=lambda profile: SimpleNamespace(name=profile, model="dummy"),
    ))
    monkeypatch.setattr(mod, "LLMClient", _LLMStub)
    monkeypatch.setattr(mod, "ToolSpecialist", _ToolSpecialistStub)
    monkeypatch.setattr(mod, "SessionStore", _SessionStoreStub)
    monkeypatch.setattr(mod, "_build_tools", lambda cfg: [])

    task_bot_runtime.create_execution(
        session_id="sess-chat-worker",
        summary="Use your tools to create the file D:\\Desktop\\dispatch-proof.txt...",
        request_text=(
            "Use your tools to create the file D:\\Desktop\\dispatch-proof.txt "
            "containing exactly DISPATCH_OK, then answer with only the full file path on one line "
            "and the file contents on the next line."
        ),
        task_id="chat-dispatch-worker",
        actor="thomas",
        repo_root=tmp_path,
    )

    rc = mod.run(["--task-id", "chat-dispatch-worker", "--worker-agent", "thomas-chat-worker"])
    payload = task_bot_runtime.find_by_task_id("chat-dispatch-worker", repo_root=tmp_path)

    assert rc == 0
    assert "dispatch-proof.txt" in capsys.readouterr().out
    assert payload is not None
    assert payload["claimed_owner"] == "thomas-chat-worker"
    assert payload["progress_summary"] == "D:\\Desktop\\dispatch-proof.txt\nDISPATCH_OK"


def test_worker_run_chat_task_guarded_loop_engine_uses_agent_loop(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    config = SimpleNamespace(
        default_model="local",
        models={"local": SimpleNamespace(name="local", model="dummy")},
        memory=SimpleNamespace(root_path=tmp_path),
        get_model=lambda profile: SimpleNamespace(name=profile, model="dummy"),
    )
    monkeypatch.setattr(mod, "load_config", lambda: config)
    monkeypatch.setattr(mod, "LLMClient", _LLMStub)
    monkeypatch.setattr(mod, "SessionStore", _SessionStoreStub)
    monkeypatch.setattr(mod, "_build_tools", lambda cfg: SimpleNamespace(list_tools=lambda: []))
    guarded_runner = object()
    monkeypatch.setattr(mod, "_build_guarded_runner", lambda config, tools: guarded_runner)

    seen: dict[str, object] = {}

    class _AgentLoopStub:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            seen["guarded_tool_runner"] = kwargs.get("guarded_tool_runner")
            seen["autonomy_level"] = kwargs.get("autonomy_level")
            seen["conversation"] = kwargs.get("conversation")

        async def run(self, prompt, **kwargs):  # noqa: ANN001
            seen["prompt"] = prompt
            seen["run_kwargs"] = dict(kwargs)
            yield AgentEvent.text_delta("GUARDED_OK")
            yield AgentEvent.agent_done("GUARDED_OK", iterations=1, tool_calls=0)

    monkeypatch.setattr(mod, "AgentLoop", _AgentLoopStub)

    task_bot_runtime.create_execution(
        session_id="sess-guarded-loop",
        summary="Edit src/app.js to print GUARDED_OK.",
        request_text="Edit src/app.js to print GUARDED_OK.",
        task_id="chat-dispatch-worker-guarded",
        actor="thomas",
        repo_root=tmp_path,
    )

    rc = mod.run(
        [
            "--task-id",
            "chat-dispatch-worker-guarded",
            "--worker-agent",
            "thomas-chat-worker",
            "--engine",
            "guarded_loop",
        ]
    )
    payload = task_bot_runtime.find_by_task_id("chat-dispatch-worker-guarded", repo_root=tmp_path)

    assert rc == 0
    assert capsys.readouterr().out.strip().endswith("GUARDED_OK")
    assert seen["guarded_tool_runner"] is guarded_runner
    assert seen["autonomy_level"] == 4
    assert "Background Execution Guidance" in str(seen["prompt"])
    assert "Edit src/app.js to print GUARDED_OK." in str(seen["prompt"])
    assert payload is not None
    assert payload["claimed_owner"] == "thomas-chat-worker"
    assert payload["progress_summary"] == "GUARDED_OK"


def test_worker_run_chat_task_injects_promoted_runtime_skill_context(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    config = SimpleNamespace(
        default_model="local",
        models={"local": SimpleNamespace(name="local", model="dummy")},
        memory=SimpleNamespace(root_path=tmp_path),
        get_model=lambda profile: SimpleNamespace(name=profile, model="dummy"),
    )
    monkeypatch.setattr(mod, "load_config", lambda: config)
    monkeypatch.setattr(mod, "LLMClient", _LLMStub)
    monkeypatch.setattr(mod, "ToolSpecialist", _SkillAwareToolSpecialistStub)
    monkeypatch.setattr(mod, "SessionStore", _SessionStoreStub)
    monkeypatch.setattr(mod, "_build_tools", lambda cfg: [])

    source_dir = tmp_path / "external" / "calendar-reminder"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "SKILL.md").write_text(
        "---\n"
        "name: calendar-reminder\n"
        "description: External reminder workflow.\n"
        "---\n\n"
        "# calendar reminder\n\n"
        "- Create recurring reminder tasks.\n",
        encoding="utf-8",
    )
    manifest = create_skill_draft(config, source=str(source_dir), name="calendar-reminder-native")
    draft_id = str(manifest["draft_id"])
    review_skill_draft(config, draft_id=draft_id)
    promote_skill_draft(config, draft_id=draft_id, target="user", cwd=tmp_path)

    task_bot_runtime.create_execution(
        session_id="sess-skill-worker",
        summary="Set a recurring weekday 9:00 AM reminder named Demo Reminder.",
        request_text="Set a recurring weekday 9:00 AM reminder named Demo Reminder that says Take meds.",
        task_id="chat-dispatch-worker-skill",
        actor="thomas",
        repo_root=tmp_path,
    )

    rc = mod.run(["--task-id", "chat-dispatch-worker-skill", "--worker-agent", "thomas-chat-worker"])
    payload = task_bot_runtime.find_by_task_id("chat-dispatch-worker-skill", repo_root=tmp_path)

    assert rc == 0
    assert capsys.readouterr().out.strip().endswith("OK")
    assert payload is not None
    assert payload["progress_summary"] == "OK"
def test_background_execution_guidance_waives_dirty_guard_for_repo_artifact_tasks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to read pyproject.toml and write "
        "runtime/agentic_bench/product50-api-test/thomas_os/task02_pyproject_metadata.json "
        "with JSON keys project_name and project_version."
    )
    policy = mod._legacy_task_execution_policy(prompt)

    guidance = mod._background_execution_guidance(prompt, policy=policy)

    assert "pre-approved to bypass dirty-worktree startup checks" in guidance
    assert "Do not ask the user for a dirty-worktree waiver" in guidance
    assert "Task capability class: artifact_only" in guidance
    assert str((tmp_path / "pyproject.toml").resolve()) not in guidance
def test_background_execution_guidance_does_not_waive_dirty_guard_for_repo_edits(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to read thomas/server/routes/chat_v2.py and then edit that file "
        "to add a new route."
    )

    guidance = mod._background_execution_guidance(prompt, policy=mod._legacy_task_execution_policy(prompt))

    assert "pre-approved to bypass dirty-worktree startup checks" not in guidance


def test_background_execution_guidance_waives_dirty_guard_for_folder_inventory_artifact_tasks(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to inspect the plugins folder and write "
        "runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json "
        "with JSON keys plugin_count and plugin_files."
    )

    guidance = mod._background_execution_guidance(prompt, policy=mod._legacy_task_execution_policy(prompt))

    assert "pre-approved to bypass dirty-worktree startup checks" in guidance


def test_worker_run_chat_task_prefixes_artifact_override_for_benchmark_outputs(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(
        mod,
        "load_config",
        lambda: SimpleNamespace(
            default_model="local",
            models={"local": SimpleNamespace(name="local", model="dummy")},
            memory=SimpleNamespace(root_path=tmp_path),
            get_model=lambda profile: SimpleNamespace(name=profile, model="dummy"),
        ),
    )
    monkeypatch.setattr(mod, "LLMClient", _LLMStub)
    monkeypatch.setattr(mod, "ToolSpecialist", _ArtifactOverrideToolSpecialistStub)
    monkeypatch.setattr(mod, "SessionStore", _SessionStoreStub)
    monkeypatch.setattr(mod, "_build_tools", lambda cfg: [])

    task_bot_runtime.create_execution(
        session_id="sess-artifact-override",
        summary="Inspect plugins folder and write benchmark artifact.",
        request_text=(
            "Use your tools to inspect the plugins folder and write "
            "runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json "
            "with JSON keys plugin_count and plugin_files. Return one line confirming "
            "task08_plugin_inventory.json was written."
        ),
        task_id="chat-dispatch-worker-artifact-override",
        actor="thomas",
        task_policy={
            "capability_class": "artifact_only",
            "allowed_write_roots": [
                "runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json"
            ],
        },
        repo_root=tmp_path,
    )

    rc = mod.run(["--task-id", "chat-dispatch-worker-artifact-override", "--worker-agent", "thomas-chat-worker"])
    payload = task_bot_runtime.find_by_task_id("chat-dispatch-worker-artifact-override", repo_root=tmp_path)

    assert rc == 0
    assert capsys.readouterr().out.strip().endswith("task08_plugin_inventory.json was written.")
    assert payload is not None
    assert payload["progress_summary"] == "task08_plugin_inventory.json was written."


def test_background_execution_guidance_waives_dirty_guard_for_benchmark_script_tasks(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to create a Python script at "
        "runtime/agentic_bench/product50-api-test/thomas_os/task42_plugin_manifest.py "
        "that prints a JSON object with keys plugin_count and plugin_files for the plugins folder."
    )

    guidance = mod._background_execution_guidance(prompt, policy=mod._legacy_task_execution_policy(prompt))

    assert "pre-approved to bypass dirty-worktree startup checks" in guidance


def test_resolve_task_execution_policy_prefers_task_record_policy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to inspect the plugins folder and write "
        "runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json."
    )
    record = {
        "task_policy": {
            "capability_class": "artifact_only",
            "allowed_write_roots": ["runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json"],
        }
    }

    policy = mod._resolve_task_execution_policy(record, prompt)

    assert policy.capability_class == "artifact_only"
    assert policy.policy_source == "task_record"
    assert policy.allowed_actions == ("read", "write")


def test_production_task_policy_does_not_fall_back_to_artifact_waiver(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to inspect the plugins folder and write "
        "runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json "
        "with JSON keys plugin_count and plugin_files."
    )

    policy = mod._resolve_task_execution_policy({"execution_intent": "production_task"}, prompt)

    assert policy.capability_class == "repo_edit_private_checkpointable"
    assert policy.dirty_worktree_waiver is False


def test_task_policy_mismatch_blocks_artifact_policy_that_requests_source_edit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    prompt = (
        "Use your tools to edit thomas/server/routes/chat_v2.py and write "
        "runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json."
    )
    policy = mod._policy_from_capability_class(
        "artifact_only",
        allowed_write_roots=("runtime/agentic_bench/product50-api-test/thomas_os/task08_plugin_inventory.json",),
        policy_source="task_record",
    )

    reason = mod._task_policy_mismatch_reason(prompt, policy)

    assert "cannot request repo source edits" in reason
