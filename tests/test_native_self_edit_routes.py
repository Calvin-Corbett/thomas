"""Test native promotion against real dirty source bytes and immutable checks."""

import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_self_edit as isolation
from thomas.server.routes.evolve_agent_self_edit_actions import apply_record, recover_record
from thomas.server.routes.evolve_agent_self_edit_policy import validate_scope
from thomas.server.routes.evolve_agent_self_edit_runs import finish_run, read_record, save_record


@pytest.fixture
def run_record(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "thomas").mkdir()
    (source / "thomas/__init__.py").write_text("")
    (source / "thomas" / "feature.py").write_text("VALUE = 'original dirty bytes'\n")
    (source / "agent_safety.toml").write_text(
        '[protected]\npolicy_files=["agent_safety.toml"]\nenforcement_files=["thomas/guard.py"]\n'
    )
    (source / "plans/thomas").mkdir(parents=True)
    (source / "plans/thomas/WORKBOARD.md").write_text("## Agent Claims\n")
    (source / "tests").mkdir()
    (source / "tests/test_feature.py").write_text(
        "from thomas.feature import VALUE\n# thomas/feature.py\ndef test_feature():\n    assert VALUE == 'improved'\n"
    )
    candidate = isolation.prepare_candidate(source, tmp_path / "candidates")
    (candidate.candidate_root / "thomas/feature.py").write_text("VALUE = 'improved'\n")
    record = {
        "conversation_id": "fc_native",
        "run_id": "run-native",
        "source_root": str(source),
        "candidate_root": str(candidate.candidate_root),
        "scope": ["thomas/feature.py"],
        "status": "running",
        "runtime_verified": False,
        "changed_files": [],
        "reason": "",
    }
    save_record(source, record)
    return source, candidate, record


def test_checked_candidate_applies_and_undo_preserves_original_dirt(run_record):
    source, candidate, record = run_record
    result = finish_run(source, record, successful=True)
    assert result["status"] == "ready", result
    assert (source / "thomas/feature.py").read_text() == "VALUE = 'original dirty bytes'\n"
    assert apply_record(source, record)["status"] == "applied"
    assert (source / "thomas/feature.py").read_text() == "VALUE = 'improved'\n"
    assert recover_record(source, record)["status"] == "undone"
    assert (source / "thomas/feature.py").read_text() == "VALUE = 'original dirty bytes'\n"
    assert read_record(source, "fc_native", "run-native")["status"] == "undone"


@pytest.mark.parametrize("extra", ["agent_safety.toml", "thomas/guard.py", "thomas/other.py", "tests/test_feature.py"])
def test_out_of_scope_oracle_and_policy_changes_never_become_ready(run_record, extra):
    source, candidate, record = run_record
    (candidate.candidate_root / extra).write_text("# tampered\n")
    result = finish_run(source, record, successful=True)
    assert result["status"] == "failed"
    with pytest.raises(isolation.SelfEditSnapshotError):
        apply_record(source, record)
    assert "original dirty bytes" in (source / "thomas/feature.py").read_text()


@pytest.mark.parametrize(
    "path", ["../outside.py", "thomas/../agent_safety.toml", "thomas/guard.py", "thomas/*", "thomas/GUARDRAILS.md"]
)
def test_invalid_or_protected_scope_is_rejected(run_record, path):
    source, _, _ = run_record
    with pytest.raises(isolation.SelfEditSnapshotError):
        validate_scope(source, [path])


def test_active_claim_blocks_promotion_even_after_checks(run_record):
    source, _, record = run_record
    assert finish_run(source, record, successful=True)["status"] == "ready"
    (source / "plans/thomas/WORKBOARD.md").write_text(
        "## Agent Claims\n- agent=another; scope=thomas/feature.py; task=other\n"
    )
    with pytest.raises(isolation.SelfEditSnapshotError, match="claimed"):
        apply_record(source, record)


@pytest.mark.parametrize("target", ["source", "candidate"])
def test_changed_bytes_after_checks_block_application(run_record, target):
    source, candidate, record = run_record
    assert finish_run(source, record, successful=True)["status"] == "ready"
    root = source if target == "source" else candidate.candidate_root
    (root / "thomas/feature.py").write_text("VALUE = 'changed later'\n")
    with pytest.raises(isolation.SelfEditSnapshotError):
        apply_record(source, record)


def test_failed_checks_and_interruption_cannot_apply(run_record):
    source, candidate, record = run_record
    (candidate.candidate_root / "thomas/feature.py").write_text("VALUE = 'wrong'\n")
    assert finish_run(source, record, successful=True)["status"] == "failed"
    assert any(e.get("actual_returncode") != 0 for e in record["evidence"])
    assert finish_run(source, record, successful=False)["status"] == "failed"
    with pytest.raises(isolation.SelfEditSnapshotError):
        apply_record(source, record)


@pytest.mark.parametrize(
    "path",
    [
        "thomas/tools/runtime_protection_paths.py",
        "thomas/tools/filesystem.py",
        "thomas/tools/diff.py",
        "thomas/forge/anvil/forge_code_self_edit_integration.py",
        "thomas/forge/anvil/forge_code_runner.py",
        "thomas/server/routes/evolve_agent_self_edit_policy.py",
    ],
)
def test_authority_files_are_blocked_without_temporary_workboard_claims(run_record, path):
    source, _, _ = run_record
    with pytest.raises(isolation.SelfEditSnapshotError, match="Protected"):
        validate_scope(source, [path])
    assert validate_scope(source, ["thomas/server/web/js/chat_results.js"])


def test_undo_works_after_private_candidate_baseline_is_lost(run_record):
    source, candidate, record = run_record
    assert finish_run(source, record, successful=True)["status"] == "ready"
    assert apply_record(source, record)["status"] == "applied"
    candidate.candidate_root.with_suffix(".baseline.json").unlink()
    assert recover_record(source, record)["status"] == "undone"
    assert "original dirty bytes" in (source / "thomas/feature.py").read_text()


def test_native_entry_binds_server_source_and_scope_through_real_http(run_record, monkeypatch):
    from tests.test_evolve_agent_routes import _drive
    from thomas.forge.anvil import forge_code_projects, forge_code_store

    source, _, _ = run_record
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: source)

    async def scenario(client):
        body = {
            "self_edit": True,
            "project_identity": "thomas-source",
            "self_edit_scope": ["thomas/feature.py"],
            "model_id": "gpt-5.6-luna",
            "profile": "openai_codex",
            "project_root": "untrusted browser path",
        }
        response = await client.post("/api/evolve/agent/conversations/new", json=body)
        data = await response.json()
        assert response.status == 200, data
        conv = data["conversation"]
        assert conv["self_edit_scope"] == ["thomas/feature.py"]
        assert conv["project_root"] == str(source)
        assert forge_code_store.load_conversation(source, conv["id"])["self_edit"] is True
        body["project_identity"] = str(source)
        response = await client.post("/api/evolve/agent/conversations/new", json=body)
        assert response.status == 400

    _drive(source, scenario)


@pytest.mark.parametrize("access", ["workspace", "project", "pc", "full", "read_only"])
def test_native_send_accepts_only_confined_writable_access(run_record, monkeypatch, access):
    from tests.test_evolve_agent_routes import _drive
    from thomas.forge.anvil import forge_code_projects
    from thomas.server.routes import evolve_agent_routes

    source, _, _ = run_record
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: source)
    prepared = []

    def stop_before_launch(*args):
        prepared.append(True)
        raise RuntimeError("private candidate preparation reached")

    monkeypatch.setattr(evolve_agent_routes, "prepare_run", stop_before_launch)

    async def scenario(client):
        created = await client.post(
            "/api/evolve/agent/conversations/new",
            json={
                "self_edit": True,
                "project_identity": "thomas-source",
                "self_edit_scope": ["thomas/feature.py"],
            },
        )
        cid = (await created.json())["conversation"]["id"]
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "conversation_id": cid,
                "message": "Improve the selected file",
                "model_id": "gpt-5.6-luna",
                "profile": "openai_codex",
                "engine": "agent",
                "file_access": access,
                "guardrails": "guarded",
                "autonomy_level": 3,
            },
        )
        data = await response.json()
        assert response.status in {400, 409}, data
        assert bool(prepared) is (access in {"workspace", "project"}), data

    # Wide access is granted as a verified Windows sign-in would (5213bb30), so
    # the self-edit rule meets the real request instead of a level already capped
    # to Project -- and must still refuse it.
    from tests.test_evolve_agent_routes import _owner_raised

    raises = [("file_access", access)] if access in {"pc", "full"} else []
    with _owner_raised(*raises):
        _drive(source, scenario)
