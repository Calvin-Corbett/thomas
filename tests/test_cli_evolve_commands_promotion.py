"""Evolve's promotion: what blocks a candidate, what promote rejects, and what the delta copies.

Split from test_cli_evolve_commands.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests._cli_evolve_fakes import _FakeVerifierPanelResult, _seed_repo
from thomas.forge.anvil import evolve as evolve_runtime
from thomas.forge.anvil.doppelganger import (
    get_paths,
    promote_green_delta_to_blue,
    sync_blue_to_green,
    sync_green_to_blue,
)


def test_evolve_run_blocks_unused_import_candidate_with_generated_ruff(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text(
                "import os\n\n__version__ = '0.2.0'\n",
                encoding="utf-8",
            )
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if isinstance(command, list) and command[:4] == [sys.executable, "-m", "ruff", "check"]:
            return {
                "command": "ruff",
                "returncode": 1,
                "stdout_tail": "F401 `os` imported but unused",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {"command": "generated", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make an import-only improvement",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]
    ruff_rows = [item for item in session["verification"] if item.get("description") == "ruff changed-python hygiene"]

    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert ruff_rows
    assert ruff_rows[0]["returncode"] == 1
    assert "F401" in ruff_rows[0]["stdout_tail"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_blocks_docstring_only_candidate_with_semantic_delta(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text(
                '"""Updated but behavior-free module docs."""\n\n__version__ = "0.0.0"\n',
                encoding="utf-8",
            )
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if isinstance(command, list) and command[:2] == [sys.executable, "-c"] and "semantic-noop" in command[2]:
            return {
                "command": "semantic",
                "returncode": 1,
                "stdout_tail": "",
                "stderr_tail": "semantic-noop Python change(s): thomas/__init__.py",
                "timed_out": False,
            }
        return {"command": "generated", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make a docstring-only improvement",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]
    semantic_rows = [item for item in session["verification"] if item.get("description") == "python semantic delta"]

    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert semantic_rows
    assert semantic_rows[0]["returncode"] == 1
    assert "semantic-noop" in semantic_rows[0]["stderr_tail"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_green_delta_drift_after_verified_session(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    assert session["status"] == "ready"
    assert session["promotable"] is True

    paths = get_paths(tmp_path)
    (paths.green_root / "thomas" / "__init__.py").write_text('__version__ = "0.9.9"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="green tree changed since evolve session verification"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_preserves_unrelated_dirty_blue_files(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    unrelated = tmp_path / "thomas" / "core" / "unrelated.py"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("VALUE = 'blue baseline'\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    assert session["status"] == "ready"
    unrelated.write_text("VALUE = 'user dirty blue edit'\n", encoding="utf-8")

    promoted = evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert promoted["session"]["status"] == "promoted"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'
    assert unrelated.read_text(encoding="utf-8") == "VALUE = 'user dirty blue edit'\n"


def test_promote_rejects_when_blue_target_changed_since_session_baseline(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    (tmp_path / "thomas" / "__init__.py").write_text('__version__ = "user-edit"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue target files changed since evolve session baseline"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == ('__version__ = "user-edit"')


def test_promote_rejects_when_blue_supervisor_manifest_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    blue_anvil = tmp_path / "thomas" / "forge" / "anvil" / "evolve.py"
    blue_anvil.parent.mkdir(parents=True, exist_ok=True)
    blue_anvil.write_text("BASELINE = 'safe'\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    assert "thomas/forge/anvil/evolve.py" in session["blue_supervisor_manifest"]["files"]
    blue_anvil.write_text("BASELINE = 'tampered'\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue supervisor/anvil files changed since evolve session baseline"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_forged_blue_supervisor_manifest_signature(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    blue_anvil = tmp_path / "thomas" / "forge" / "anvil" / "evolve.py"
    blue_anvil.parent.mkdir(parents=True, exist_ok=True)
    blue_anvil.write_text("BASELINE = 'safe'\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session["blue_supervisor_manifest"]["signature"]["value"] = "0" * 64
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue supervisor/anvil manifest signature mismatch"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_legacy_session_without_blue_baseline_fingerprint(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session.pop("blue_delta_base_fingerprint", None)
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing blue delta base fingerprint"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_calls_blue_only_supervisor_before_copying(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    paths = get_paths(tmp_path)
    (paths.green_root / "tests" / "test_architecture.py").write_text("def test_smoke():\n    pass\n", encoding="utf-8")

    forged_delta = evolve_runtime._collect_tree_delta(paths)
    session["delta"] = forged_delta
    session["changed_files"] = list(forged_delta["changed_files"])
    session["verified_delta_fingerprint"] = evolve_runtime._delta_fingerprint(paths, forged_delta)
    session["blue_delta_base_fingerprint"] = evolve_runtime._delta_fingerprint_for_root(tmp_path, forged_delta)
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue-only supervisor rejected evolve promotion"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert "test_architecture.py" not in (tmp_path / "tests" / "test_architecture.py").read_text(encoding="utf-8")


def test_promote_verifier_panel_uses_fresh_supervisor_verdict(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    seen: dict[str, object] = {}

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def fake_panel(session_payload, *, supervisor_verdict, quorum=4):
        seen["stored_supervisor_ok"] = dict(session_payload.get("supervisor_verdict") or {}).get("ok")
        seen["fresh_supervisor_ok"] = supervisor_verdict.get("ok")
        return _FakeVerifierPanelResult(ok=True, pass_count=5, quorum=quorum)

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_verifier_panel", fake_panel)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session["supervisor_verdict"] = {
        "ok": False,
        "findings": [{"code": "forged_stale_artifact", "severity": "reject"}],
    }
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    promoted = evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert seen == {"stored_supervisor_ok": False, "fresh_supervisor_ok": True}
    assert promoted["session"]["status"] == "promoted"
    assert promoted["session"]["verifier_panel"]["ok"] is True
    assert promoted["session"]["supervisor_verdict"]["verifier_panel"]["pass_count"] == 5
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'


def test_promote_rejects_when_verifier_panel_lacks_quorum(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def fake_panel(session_payload, *, supervisor_verdict, quorum=4):
        _ = session_payload, supervisor_verdict
        return _FakeVerifierPanelResult(ok=False, pass_count=3, quorum=quorum)

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_verifier_panel", fake_panel)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    with pytest.raises(RuntimeError, match="verifier panel rejected evolve promotion: pass_count 3 below quorum 4"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_when_verifier_panel_has_hold_despite_quorum(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def fake_panel(session_payload, *, supervisor_verdict, quorum=4):
        _ = session_payload, supervisor_verdict
        return _FakeVerifierPanelResult(
            ok=True,
            pass_count=4,
            quorum=quorum,
            votes=[
                {"role": "correctness", "status": "pass", "reason": "ok", "severity": "advisory"},
                {"role": "regression", "status": "pass", "reason": "ok", "severity": "advisory"},
                {"role": "security", "status": "pass", "reason": "ok", "severity": "advisory"},
                {"role": "reward_hack", "status": "pass", "reason": "ok", "severity": "advisory"},
                {
                    "role": "reproducibility",
                    "status": "hold",
                    "reason": "needs replay evidence",
                    "severity": "advisory",
                },
            ],
        )

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_verifier_panel", fake_panel)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    with pytest.raises(
        RuntimeError,
        match=r"verifier panel rejected evolve promotion: non-passing verifier vote\(s\): reproducibility:hold",
    ):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_delta_promotion_does_not_copy_unlisted_green_changes(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    blue_unrelated = tmp_path / "thomas" / "core" / "unrelated.py"
    green_unrelated = paths.green_root / "thomas" / "core" / "unrelated.py"
    blue_unrelated.parent.mkdir(parents=True)
    green_unrelated.parent.mkdir(parents=True)
    blue_unrelated.write_text("VALUE = 'dirty blue'\n", encoding="utf-8")
    green_unrelated.write_text("VALUE = 'stale green'\n", encoding="utf-8")
    (paths.green_root / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    promote_green_delta_to_blue(paths, ["thomas/__init__.py"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'
    assert blue_unrelated.read_text(encoding="utf-8") == "VALUE = 'dirty blue'\n"


def test_delta_promotion_applies_verified_deletions_only(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    paths = get_paths(tmp_path)
    delete_me = tmp_path / "thomas" / "feature" / "delete_me.py"
    keep_me = tmp_path / "thomas" / "feature" / "keep_me.py"
    delete_me.parent.mkdir(parents=True)
    delete_me.write_text("VALUE = 'delete'\n", encoding="utf-8")
    keep_me.write_text("VALUE = 'keep blue'\n", encoding="utf-8")
    sync_blue_to_green(paths)

    (paths.green_root / "thomas" / "feature" / "delete_me.py").unlink()
    (paths.green_root / "thomas" / "feature" / "keep_me.py").write_text("VALUE = 'stale green'\n", encoding="utf-8")

    promote_green_delta_to_blue(paths, ["thomas/feature/delete_me.py"])

    assert not delete_me.exists()
    assert keep_me.read_text(encoding="utf-8") == "VALUE = 'keep blue'\n"


def test_promotion_candidate_root_preserves_blue_support_scope(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "evolve_supervisor").mkdir()
    (tmp_path / "evolve_supervisor" / "__init__.py").write_text("VERSION = 'blue'\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    candidate_root = evolve_runtime._prepare_delta_candidate_root(
        paths,
        {"changed_files": ["thomas/__init__.py"]},
    )

    assert (candidate_root / "evolve_supervisor" / "__init__.py").read_text(encoding="utf-8") == "VERSION = 'blue'\n"
    assert (candidate_root / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == ('__version__ = "0.1.0"')


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
        "evolve_supervisor/__init__.py": "VERSION = 'blue'\n",
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
    assert (paths.green_root / "evolve_corpus" / "LOCK.json").exists()


def test_sync_green_to_blue_blocks_protected_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "tests" / "test_architecture.py").write_text(
        "def test_smoke():\n    assert False\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="protected/supervisor-owned diff"):
        sync_green_to_blue(paths)

    assert (tmp_path / "tests" / "test_architecture.py").read_text(encoding="utf-8") == (
        "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n"
    )


def test_sync_green_to_blue_blocks_runtime_protected_guard_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    guard = tmp_path / "thomas" / "tools" / "filesystem.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("PROTECTED = True\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "tools" / "filesystem.py").write_text("PROTECTED = False\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="thomas/tools/filesystem.py"):
        sync_green_to_blue(paths)

    assert guard.read_text(encoding="utf-8") == "PROTECTED = True\n"


def test_sync_green_to_blue_blocks_protected_prefix_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        'policy_files=["evolve_corpus/"]\n'
        "guardrails_files=[]\n"
        "enforcement_files=[]\n"
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "evolve_corpus" / "cases" / "known_good_minimal.json").write_text(
        '{"case_id":"tampered"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="evolve_corpus/cases/known_good_minimal.json"):
        sync_green_to_blue(paths)


def test_sync_green_to_blue_blocks_supervisor_owned_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    (tmp_path / "thomas" / "forge" / "anvil" / "evolve.py").write_text(
        "SUPERVISOR = 'blue'\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve.py").write_text(
        "SUPERVISOR = 'tampered'\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve.py"):
        sync_green_to_blue(paths)

    assert (tmp_path / "thomas" / "forge" / "anvil" / "evolve.py").read_text(encoding="utf-8") == (
        "SUPERVISOR = 'blue'\n"
    )


def test_sync_green_to_blue_blocks_new_loop_package_python_file_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").write_text(
        "ALWAYS_PASS = True\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve_fake_gate.py"):
        sync_green_to_blue(paths)

    assert not (tmp_path / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").exists()


def test_sync_green_to_blue_blocks_existing_loop_package_python_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'blue'\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'tampered'\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve_loop_learning.py"):
        sync_green_to_blue(paths)

    assert (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").read_text(
        encoding="utf-8"
    ) == "RANKER = 'blue'\n"


def test_delta_promotion_allows_verified_existing_loop_package_python_diff(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    loop_file = tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py"
    loop_file.parent.mkdir(parents=True)
    loop_file.write_text("RANKER = 'blue'\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'green'\n",
        encoding="utf-8",
    )

    promote_green_delta_to_blue(paths, ["thomas/forge/anvil/evolve_loop_learning.py"])

    assert loop_file.read_text(encoding="utf-8") == "RANKER = 'green'\n"


def test_delta_promotion_blocks_new_loop_package_python_file(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil").mkdir(parents=True, exist_ok=True)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").write_text(
        "ALWAYS_PASS = True\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve_fake_gate.py"):
        promote_green_delta_to_blue(paths, ["thomas/forge/anvil/evolve_fake_gate.py"])

    assert not (tmp_path / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").exists()


def test_delta_promotion_blocks_runtime_protected_guard_delta(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    guard = tmp_path / "thomas" / "tools" / "filesystem.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("PROTECTED = True\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "tools" / "filesystem.py").write_text("PROTECTED = False\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="thomas/tools/filesystem.py"):
        promote_green_delta_to_blue(paths, ["thomas/tools/filesystem.py"])

    assert guard.read_text(encoding="utf-8") == "PROTECTED = True\n"
