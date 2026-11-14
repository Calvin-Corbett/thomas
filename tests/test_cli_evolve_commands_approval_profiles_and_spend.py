"""Evolve's approvals, model profiles, spend and secret routing, tool policy, and when verification is skipped.

Split from test_cli_evolve_commands.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner

from evolve_supervisor import evaluate_spend_governor
from tests._cli_evolve_fakes import _FakeVerifierPanelResult, _seed_repo
from thomas.cli import _commands_base as cli_commands_base
from thomas.cli.commands.evolve import evolve
from thomas.core.config import load_config
from thomas.forge.anvil import evolve as evolve_runtime
from thomas.forge.anvil.doppelganger import (
    get_paths,
)


def test_auto_promote_calls_blue_only_supervisor_before_copying(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    supervisor_calls: list[dict[str, object]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "7.7.7"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def reject_candidate(paths, expected_delta, session_payload, *, candidate_dirname="promote-candidate"):
        supervisor_calls.append(
            {
                "candidate_dirname": candidate_dirname,
                "changed_files": list(expected_delta.get("changed_files") or []),
                "promotable": bool(session_payload.get("promotable")),
            }
        )
        return {
            "ok": False,
            "risk_floor": "critical",
            "delta": {"changed_files": list(expected_delta.get("changed_files") or [])},
            "findings": [{"code": "forced_reject", "severity": "reject", "path": "thomas/__init__.py"}],
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "_evaluate_promotion_candidate", reject_candidate)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove auto promote uses the blue supervisor",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert supervisor_calls == [
        {
            "candidate_dirname": "promote-candidate-auto",
            "changed_files": ["thomas/__init__.py"],
            "promotable": True,
        }
    ]
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["supervisor_verdict"]["ok"] is False
    assert any("forced_reject" in item for item in session["session_rejections"])
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_auto_promote_holds_non_python_delta_for_human_approval(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "README.md").write_text("blue docs\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.8.0"\n', encoding="utf-8")
            Path(cwd, "README.md").write_text("green docs\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Change Python and docs together",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["supervisor_verdict"]["ok"] is True
    assert session["supervisor_verdict"]["risk_floor"] == "critical"
    assert any("critical risk floor" in item for item in session["session_rejections"])
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "blue docs\n"


def test_manual_promote_requires_explicit_critical_risk_ack(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def critical_candidate(paths, expected_delta, session_payload, *, candidate_dirname="promote-candidate"):
        _ = paths, session_payload, candidate_dirname
        return {
            "ok": True,
            "risk_floor": "critical",
            "delta": {"changed_files": list(expected_delta.get("changed_files") or [])},
            "findings": [],
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "_evaluate_promotion_candidate", critical_candidate)
    monkeypatch.setattr(
        evolve_runtime,
        "run_verifier_panel",
        lambda session_payload, *, supervisor_verdict, quorum=4: _FakeVerifierPanelResult(
            ok=True,
            pass_count=5,
            quorum=quorum,
        ),
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prepare Python change for manual approval",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    runner = CliRunner()

    bare = runner.invoke(evolve, ["promote", session["session_id"], "--repo-root", str(tmp_path), "--json"])

    assert bare.exit_code != 0
    assert bare.exception is not None
    assert "critical risk floor" in str(bare.exception)
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'

    approved = runner.invoke(
        evolve,
        [
            "promote",
            session["session_id"],
            "--repo-root",
            str(tmp_path),
            "--approve-critical-risk",
            "--json",
        ],
    )

    assert approved.exit_code == 0, approved.output
    approved_payload = json.loads(approved.output)
    approved_session = approved_payload["session"]
    assert approved_session["status"] == "promoted"
    assert approved_session["supervisor_verdict"]["risk_floor"] == "critical"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.9.0"'


def test_manual_promote_rejects_non_python_delta_without_dedicated_verifier(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "README.md").write_text("blue docs\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
            Path(cwd, "README.md").write_text("green docs\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def safe_candidate(paths, expected_delta, session_payload, *, candidate_dirname="promote-candidate"):
        _ = paths, session_payload, candidate_dirname
        return {
            "ok": True,
            "risk_floor": "low",
            "delta": {"changed_files": list(expected_delta.get("changed_files") or [])},
            "findings": [],
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "_evaluate_promotion_candidate", safe_candidate)
    monkeypatch.setattr(
        evolve_runtime,
        "run_verifier_panel",
        lambda session_payload, *, supervisor_verdict, quorum=4: _FakeVerifierPanelResult(
            ok=True,
            pass_count=5,
            quorum=quorum,
        ),
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prepare mixed Python and docs change for manual approval",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    approved = CliRunner().invoke(
        evolve,
        [
            "promote",
            session["session_id"],
            "--repo-root",
            str(tmp_path),
            "--approve-critical-risk",
            "--json",
        ],
    )

    assert approved.exit_code != 0
    assert approved.exception is not None
    assert "non-Python delta requires a dedicated passing non-Python verifier" in str(approved.exception)
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "blue docs\n"


def test_auto_promote_runs_evolve_corpus_before_copying(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    corpus_roots: list[Path] = []

    class FailingCorpus:
        ok = False

        def to_dict(self):
            return {
                "ok": False,
                "case_count": 1,
                "cases": [
                    {
                        "case_id": "known_bad_import_swap",
                        "ok": False,
                        "expected": "reject",
                        "actual": "promote",
                        "details": {},
                    }
                ],
                "lock_errors": [],
            }

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def failing_corpus(repo_root: Path):
        corpus_roots.append(Path(repo_root))
        return FailingCorpus()

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_evolve_corpus", failing_corpus)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove corpus gates live promotion",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert corpus_roots == [tmp_path.resolve()]
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["supervisor_verdict"]["evolve_corpus"]["ok"] is False
    assert any("blue evolve corpus rejected promotion" in item for item in session["session_rejections"])
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_defaults_to_codex_profile(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.codex]\nprovider = "codex"\nmodel = "gpt-5.3-codex"\n\ndefault_model = "codex"\n',
        encoding="utf-8",
    )
    seen_commands: list[list[str]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list):
            seen_commands.append([str(part) for part in command])
            if "chat" in command:
                Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Use the right model")
    session = payload["session"]

    chat_commands = [cmd for cmd in seen_commands if "chat" in cmd]
    assert chat_commands
    assert any(
        idx + 1 < len(cmd) and cmd[idx + 1] == "codex"
        for cmd in chat_commands
        for idx, part in enumerate(cmd[:-1])
        if part == "-m"
    )
    assert session["profile"] == "codex"


def test_evolve_profile_legacy_codex_alias_uses_openai_codex(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        'default_model = "local"\n\n'
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.openai_codex]\nprovider = "openai_codex"\nmodel = "gpt-5.5"\n',
        encoding="utf-8",
    )

    assert evolve_runtime._resolve_evolve_profile(tmp_path, "codex") == "openai_codex"


def test_evolve_profile_env_legacy_codex_alias_uses_openai_codex(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        'default_model = "local"\n\n'
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.openai_codex]\nprovider = "openai_codex"\nmodel = "gpt-5.5"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("THOMAS_DEFAULT_MODEL", "codex")

    assert evolve_runtime._resolve_evolve_profile(tmp_path, "") == "openai_codex"


def test_evolve_profile_legacy_codex_still_uses_named_codex_when_present(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        'default_model = "local"\n\n'
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.codex]\nprovider = "codex"\nmodel = "gpt-5.3-codex"\n',
        encoding="utf-8",
    )

    assert evolve_runtime._resolve_evolve_profile(tmp_path, "codex") == "codex"


def test_evolve_run_routes_green_spend_to_main_repo_spend_file(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    seen_envs: list[dict[str, str]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = command, cwd, timeout_seconds
        seen_envs.append(dict(env))
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    evolve_runtime.run_evolve_session(tmp_path, goal="Track spend in main runtime")

    assert seen_envs
    assert any(env.get("THOMAS_SPEND_PATH") == str(tmp_path / "thomas_spend.jsonl") for env in seen_envs)
    assert any(env.get("THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT") == str(tmp_path) for env in seen_envs)


def test_evolve_run_appends_blue_spend_reserve_after_green_child(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 0.49\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "",
                "stderr_tail": "",
                "timed_out": False,
                "usd_total": 999.0,
            }
        return {"command": "verify", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Meter green child spend from blue",
        refactor_first=False,
        passes=1,
    )
    session = payload["session"]
    ledger_rows = [
        json.loads(line)
        for line in (tmp_path / "thomas_spend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert session["status"] == "ready"
    assert session["spend_governor_rejections"] == []
    assert session["spend_governor_checks"][0]["code"] == "within_budget"
    assert session["spend_ledger_writes"][0]["code"] == "ledger_appended"
    assert ledger_rows == [session["spend_ledger_writes"][0]["entry"]]
    assert ledger_rows[0]["source"] == "blue_evolve_child_reserve"
    assert ledger_rows[0]["phase"] == "creative"
    assert ledger_rows[0]["session_id"] == session["session_id"]
    assert ledger_rows[0]["usd_total"] == 0.25
    assert evaluate_spend_governor(tmp_path, today=ledger_rows[0]["day"]).code == "daily_cap_exceeded"


def test_evolve_run_blocks_second_green_child_after_blue_spend_reserve(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 0.49\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    chat_calls = 0

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            Path(cwd, "thomas", "__init__.py").write_text(f'__version__ = "0.1.{chat_calls}"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        raise AssertionError("verification should not run after spend governor rejects the session")

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Stop when blue spend cap is consumed",
        refactor_first=False,
        passes=2,
    )
    session = payload["session"]

    assert chat_calls == 1
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert len(session["pass_results"]) == 1
    assert len(session["spend_ledger_writes"]) == 1
    assert session["spend_governor_checks"][0]["ok"] is True
    assert session["spend_governor_checks"][1]["ok"] is False
    assert session["spend_governor_checks"][1]["code"] == "daily_cap_exceeded"
    assert "daily evolve spend cap would be exceeded" in session["spend_governor_rejections"][0]
    assert "session rejected before verification" in session["verification_skipped_reason"]


def test_evolve_run_routes_green_secrets_to_main_repo_secret_store(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    memory_root = tmp_path / "runtime"
    monkeypatch.setenv("THOMAS_MEMORY_ROOT", str(memory_root.resolve()))
    (tmp_path / "thomas.toml").write_text(f'[memory]\nroot = "{memory_root.as_posix()}"\n', encoding="utf-8")
    seen: list[tuple[Path, dict[str, str], object]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = command, timeout_seconds
        seen.append((Path(cwd), dict(env), command))
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Use main repo OAuth store", refactor_first=False)
    session = payload["session"]
    green_envs = [env for cwd, env, _command in seen if cwd == Path(session["green_root"])]
    green_commands = [command for cwd, _env, command in seen if cwd == Path(session["green_root"])]
    verify_envs = [env for cwd, env, _command in seen if cwd == Path(session["verification_root"])]

    assert green_envs
    assert all(env.get("THOMAS_MEMORY_ROOT") == str(get_paths(tmp_path).green_runtime) for env in green_envs)
    assert all(env.get("THOMAS_SECRET_ROOT") == str(memory_root / ".thomas") for env in green_envs)
    assert all(env.get("THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT") == str(tmp_path) for env in green_envs)
    assert all(env.get("THOMAS_MAX_AGENT_ITERATIONS") == "4" for env in green_envs)
    assert all(env.get("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES") == "1" for env in green_envs)
    assert all(env.get("THOMAS_TOOLS_ALLOW_SHELL") == "false" for env in green_envs)
    assert all(isinstance(command, list) and "--max-iterations" in command for command in green_commands)
    assert all(
        isinstance(command, list) and command[command.index("--max-iterations") + 1] == "4"
        for command in green_commands
    )
    assert all(
        isinstance(command, list) and command[command.index("--job-type") + 1] == "self_development"
        for command in green_commands
    )
    assert all(env.get("THOMAS_QUALITY_ENABLED") == "false" for env in green_envs)
    assert all(env.get("THOMAS_QUALITY_ENFORCE") == "false" for env in green_envs)
    assert all(env.get("THOMAS_QUALITY_MAX_AUTO_RETRIES") == "0" for env in green_envs)
    denylist = set(green_envs[0].get("THOMAS_TOOL_DENYLIST", "").split(","))
    assert {
        "git.status",
        "git.diff",
        "shell.exec",
        "ssh.exec",
        "flow_execute",
        "nodes_execute_node",
        "workflow_execution",
        "upgrade_promote_green_to_blue",
        "upgrade_sync_green_to_blue",
        "upgrade_run_green_tests",
    }.issubset(denylist)
    assert "code.search" not in denylist
    assert "fs.search" not in denylist
    assert verify_envs
    stripped_keys = {
        "THOMAS_SPEND_PATH",
        "THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT",
        "THOMAS_MEMORY_ROOT",
        "THOMAS_SECRET_ROOT",
        "THOMAS_EVOLVE_GREEN_RUNTIME_WRITES",
        "THOMAS_TOOLS_ALLOW_SHELL",
        "THOMAS_TOOL_ALLOWLIST",
        "THOMAS_TOOL_DENYLIST",
        "THOMAS_MAX_AGENT_ITERATIONS",
        "THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT",
        "THOMAS_QUALITY_ENABLED",
        "THOMAS_QUALITY_ENFORCE",
        "THOMAS_QUALITY_MAX_AUTO_RETRIES",
    }
    assert all(stripped_keys.isdisjoint(env) for env in verify_envs)


def test_cli_tool_denylist_env_filters_registered_tools(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    monkeypatch.setenv("THOMAS_TOOL_DENYLIST", "git.status,code.search,fs.search")
    config = load_config(tmp_path / "thomas.toml")

    registry = cli_commands_base._build_tools(config)

    assert registry.get("git.status") is None
    assert registry.get("code.search") is None
    assert registry.get("fs.search") is None
    assert registry.get("fs.read_file") is not None
    assert registry.get("diff.create") is not None


def test_evolve_green_tool_policy_removes_exec_primitives_even_when_shell_is_configured(
    tmp_path: Path, monkeypatch
) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text("[tools]\nallow_shell = true\n", encoding="utf-8")
    green_env = evolve_runtime._evolve_child_env()
    evolve_runtime._merge_tool_denylist(green_env)
    monkeypatch.setenv("THOMAS_TOOLS_ALLOW_SHELL", green_env["THOMAS_TOOLS_ALLOW_SHELL"])
    monkeypatch.setenv("THOMAS_TOOL_DENYLIST", green_env["THOMAS_TOOL_DENYLIST"])
    config = load_config(tmp_path / "thomas.toml")

    registry = cli_commands_base._build_tools(config)

    assert config.tools.allow_shell is False
    for tool_name in (
        "shell.exec",
        "ssh.exec",
        "flow_execute",
        "nodes_execute_node",
        "workflow_execution",
        "upgrade_promote_green_to_blue",
        "upgrade_sync_green_to_blue",
        "upgrade_run_green_tests",
    ):
        assert registry.get(tool_name) is None
    assert registry.get("fs.read_file") is not None
    assert registry.get("diff.create") is not None


def test_evolve_run_skips_verification_after_agent_failure(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    calls: list[Path] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = env, timeout_seconds
        calls.append(Path(cwd))
        if isinstance(command, list) and "chat" in command:
            return {
                "command": "chat",
                "returncode": 124,
                "stdout_tail": "timed out",
                "stderr_tail": "",
                "timed_out": True,
            }
        raise AssertionError("verification should not run after an agent failure")

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove failed agent runs do not spend time verifying",
        refactor_first=False,
    )
    session = payload["session"]

    assert calls == [Path(session["green_root"])]
    assert session["status"] == "agent_failed"
    assert session["promotable"] is False
    assert session["verification"] == []
    assert session["verification_skipped_reason"] == "agent pass failed before verification"


def test_evolve_run_skips_verification_when_agent_makes_no_delta(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    calls: list[Path] = []
    commands: list[object] = []
    envs: list[dict[str, str]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = env, timeout_seconds
        calls.append(Path(cwd))
        commands.append(command)
        envs.append(dict(env))
        if isinstance(command, list) and "chat" in command:
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "NO_ELIGIBLE_CHANGE: no safe edit",
                "stderr_tail": "",
                "timed_out": False,
            }
        raise AssertionError("verification should not run when there is no candidate delta")

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove no-change sessions do not spend time verifying",
        refactor_first=False,
    )
    session = payload["session"]

    assert calls == [Path(session["green_root"]), Path(session["green_root"])]
    assert isinstance(commands[0], list)
    assert isinstance(commands[1], list)
    assert commands[0][commands[0].index("--max-iterations") + 1] == "4"
    assert commands[1][commands[1].index("--max-iterations") + 1] == "6"
    assert commands[0][commands[0].index("--job-type") + 1] == "self_development"
    assert commands[1][commands[1].index("--job-type") + 1] == "self_development"
    assert envs[0].get("THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT") is None
    assert envs[1].get("THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT") == "2"
    assert session["no_change_retry_attempted"] is True
    assert session["pass_results"][1]["retry_reason"] == "no_candidate_changes"
    assert "write-or-refuse" in session["pass_results"][1]["prompt"]
    assert "at most one targeted `code.search` call" in session["pass_results"][1]["prompt"]
    assert "at most one bounded `fs.read_file` call" in session["pass_results"][1]["prompt"]
    assert "do not call `fs.search`, `git.status`, `shell.exec`" in session["pass_results"][1]["prompt"]
    assert "single optional `code.search` call" in session["pass_results"][1]["prompt"]
    assert "copy `old_str` exactly from the `fs.read_file` output" in session["pass_results"][1]["prompt"]
    assert "must be `diff.create` or `fs.write_file`" in session["pass_results"][1]["prompt"]
    assert "`shell.exec` is unavailable; if `diff.create` fails" in session["pass_results"][1]["prompt"]
    assert "Only run verification after a write tool succeeds" in session["pass_results"][1]["prompt"]
    assert session["status"] == "no_change"
    assert session["promotable"] is False
    assert session["verification"] == []
    assert session["verification_skipped_reason"] == "no candidate changes before verification"


def test_evolve_run_retries_no_change_once_and_verifies_rescued_delta(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    chat_calls = 0
    verify_calls = 0

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls, verify_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            if chat_calls == 2:
                Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "ok",
                "stderr_tail": "",
                "timed_out": False,
            }
        verify_calls += 1
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove no-change retry can produce a candidate delta",
        refactor_first=False,
    )
    session = payload["session"]

    assert chat_calls == 2
    assert verify_calls >= 1
    assert session["no_change_retry_attempted"] is True
    assert session["pass_results"][1]["retry_reason"] == "no_candidate_changes"
    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert session["changed_files"] == ["thomas/__init__.py"]
