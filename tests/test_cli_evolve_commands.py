from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve
from thomas.upgrade import evolve as evolve_runtime
from thomas.upgrade.doppelganger import get_paths, sync_blue_to_green


def _seed_repo(root: Path) -> None:
    (root / "thomas").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
    (root / "thomas" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    (root / "tests" / "test_architecture.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")


def test_evolve_init_and_status(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    runner = CliRunner()
    init_result = runner.invoke(
        evolve,
        [
            "init",
            "--repo-root",
            str(tmp_path),
            "--objective",
            "Improve Thomas reliability",
            "--verify-cmd",
            "python -m pytest tests/test_architecture.py -q",
        ],
    )
    assert init_result.exit_code == 0, init_result.output
    assert (tmp_path / ".thomas" / "evolve" / "charter.json").exists()
    assert (tmp_path / ".thomas" / "evolve" / "charter.md").exists()

    status_result = runner.invoke(evolve, ["status", "--repo-root", str(tmp_path), "--json"])
    assert status_result.exit_code == 0, status_result.output
    payload = json.loads(status_result.output)
    assert payload["initialized"] is True
    assert payload["charter"]["objective"] == "Improve Thomas reliability"
    assert payload["run_count"] == 0


def test_evolve_run_and_promote(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    runner = CliRunner()

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "updated",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)

    run_result = runner.invoke(evolve, ["run", "--repo-root", str(tmp_path), "--goal", "Tighten Thomas UX", "--json"])
    assert run_result.exit_code == 0, run_result.output
    payload = json.loads(run_result.output)
    session = payload["session"]
    assert session["status"] == "ready"
    assert "thomas/__init__.py" in session["changed_files"]
    assert session["promotable"] is True
    assert session["verified_tree_hash"]
    assert session["verified_at"]

    promote_result = runner.invoke(evolve, ["promote", "--repo-root", str(tmp_path), "--json"])
    assert promote_result.exit_code == 0, promote_result.output
    promote_payload = json.loads(promote_result.output)
    assert promote_payload["session"]["status"] == "promoted"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'


def test_evolve_self_host_check_runs_maintenance_evolve_and_fresh_task(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    runner = CliRunner()

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "updated",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(
        evolve_runtime,
        "_attempt_maintenance_checkpoint",
        lambda *_args, **_kwargs: {
            "ok": True,
            "attempted": True,
            "message": "scoped agent commit created",
            "commit_sha": "abc123",
        },
    )
    monkeypatch.setattr(
        evolve_runtime,
        "_run_self_host_fresh_task",
        lambda *_args, **_kwargs: {
            "ok": True,
            "task_id": "self-host-123",
            "progress_summary": "task_pyproject.json was written.",
            "rc": 0,
        },
    )
    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    result = runner.invoke(
        evolve,
        [
            "self-host-check",
            "--repo-root",
            str(tmp_path),
            "--maintenance-agent",
            "thomas-maintainer",
            "--worker-agent",
            "thomas-chat-worker",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["stage"] == "completed"
    assert payload["maintenance"]["commit_sha"] == "abc123"
    assert payload["promotion"]["session"]["status"] == "promoted"
    assert payload["fresh_task"]["ok"] is True


def test_evolve_promote_rejects_green_mutation_after_verification(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    runner = CliRunner()

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "updated",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    run_result = runner.invoke(evolve, ["run", "--repo-root", str(tmp_path), "--goal", "Tighten Thomas UX", "--json"])
    assert run_result.exit_code == 0, run_result.output

    green_init = get_paths(tmp_path).green_root / "thomas" / "__init__.py"
    green_init.write_text('__version__ = "0.1.1"\n', encoding="utf-8")

    promote_result = runner.invoke(evolve, ["promote", "--repo-root", str(tmp_path), "--json"])
    assert promote_result.exit_code != 0
    assert "green tree changed after verification" in str(promote_result.exception)


def test_sync_blue_to_green_includes_support_docs_and_assets(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    support_files = {
        "AGENTS.md": "root agent rules\n",
        "GUARDRAILS.md": "root guardrails\n",
        "WORKTREE_RULES.md": "worktree rules\n",
        "agent_safety.toml": "[protected]\npolicy_files=[]\nguardrails_files=[]\nenforcement_files=[]\nenforcement_scripts=[]\n",
        "docs/AGENT_FILE_EDITING_RULES.md": "edit rules\n",
        "docs/ai/AGENT_ROUTER.md": "router\n",
        "docs/ai/CHECKLISTS/agent-lane-chat.md": "chat lane\n",
        "extensions/catalog.json": "{}\n",
        "apps/site/src/lib/site-config.ts": "export const config = {};\n",
        "apps/site/src/app/marketplace/page.tsx": "export default function Page() { return null; }\n",
        "apps/site/src/app/api/marketplace/catalog/route.ts": "export async function GET() { return Response.json({}); }\n",
        "apps/site/src/app/api/v1/plugins/catalog/route.ts": "export async function GET() { return Response.json({}); }\n",
        "apps/site/src/app/api/v1/plugins/download-token/route.ts": "export async function GET() { return Response.json({}); }\n",
        "apps/site/src/app/api/v1/plugins/[pluginId]/route.ts": "export async function GET() { return Response.json({}); }\n",
    }
    for rel, text in support_files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)

    for rel in support_files:
        assert (paths.green_root / rel).exists(), rel


def test_evolve_run_reverts_protected_file_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            Path(cwd, "tests", "test_architecture.py").write_text(
                "def test_smoke():\n    assert False\n", encoding="utf-8"
            )
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "updated",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Safe runtime tweak")
    session = payload["session"]
    green_test = get_paths(tmp_path).green_root / "tests" / "test_architecture.py"

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["policy_violations"] == ["tests/test_architecture.py"]
    assert "tests/test_architecture.py" not in session["changed_files"]
    assert "thomas/__init__.py" in session["changed_files"]
    assert green_test.read_text(encoding="utf-8") == "def test_smoke():\n    assert True\n"


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
        cmd[idx + 1] == "codex"
        for cmd in chat_commands
        for idx, part in enumerate(cmd[:-1])
        if part == "-m" and cmd[idx - 1] == "4"
    )
    assert session["profile"] == "codex"


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
