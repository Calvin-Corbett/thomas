from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

changelog_gate = importlib.import_module("forge.gates.changelog_gate")
bulk_commit_guard = importlib.import_module("forge.gates.bulk_commit_guard")
commit_growth_guard = importlib.import_module("forge.gates.commit_growth_guard")
exception_handler_gate = importlib.import_module("forge.gates.exception_handler_gate")
post_commit_audit = importlib.import_module("post_commit_audit")
protected_files_gate = importlib.import_module("forge.gates.protected_files_gate")
enforcement_integrity = importlib.import_module("forge.gates.enforcement_integrity")
commit_scope_gate = importlib.import_module("forge.gates.commit_scope_gate")
type_safety_gate = importlib.import_module("forge.gates.type_safety_gate")
validate_agent_changes = importlib.import_module("validate_agent_changes")
precommit_skip_policy = importlib.import_module("forge.gates.precommit_skip_policy")


def _clear_agent_context(monkeypatch) -> None:
    for key in set(post_commit_audit.AGENT_CONTEXT_ENV_KEYS) | set(post_commit_audit.AGENT_ENV_KEYS):
        monkeypatch.delenv(key, raising=False)


def test_changelog_gate_blocks_threshold_without_changelog(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/", "scripts/"))
    monkeypatch.setattr(
        changelog_gate,
        "_staged_files",
        lambda: ["thomas/a.py", "thomas/b.py", "scripts/c.py"],
    )

    rc = changelog_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["code_files_staged"] == 3
    assert payload["changelog_staged"] is False
    assert "CHANGELOG.md is not staged" in payload["reason"]


def test_changelog_gate_blocks_trivial_changelog_padding(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/",))
    monkeypatch.setattr(
        changelog_gate,
        "_staged_files",
        lambda: ["thomas/a.py", "thomas/b.py", "thomas/c.py", "CHANGELOG.md"],
    )
    monkeypatch.setattr(changelog_gate, "_changelog_diff_content", lambda: "")

    rc = changelog_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["changelog_staged"] is True
    assert "contains no meaningful changes" in payload["reason"]


def test_changelog_gate_allows_meaningful_changelog_entry(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/",))
    monkeypatch.setattr(
        changelog_gate,
        "_staged_files",
        lambda: ["thomas/a.py", "thomas/b.py", "thomas/c.py", "CHANGELOG.md"],
    )
    monkeypatch.setattr(
        changelog_gate,
        "_changelog_diff_content",
        lambda: "### Fixed\n- chat: restore guarded changelog bypass audit coverage",
    )

    rc = changelog_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["changelog_staged"] is True


def test_protected_files_gate_supports_diff_range(monkeypatch, capsys) -> None:
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(
        protected_files_gate,
        "_changed_files",
        lambda *, base=None, head=None: ["agent_safety.toml"],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"] == ["agent_safety.toml"]
    assert payload["approved_protected_files"] is False


def test_protected_files_gate_supports_protected_prefixes() -> None:
    protected = {"evolve_corpus/"}

    assert protected_files_gate._is_protected_path("evolve_corpus/LOCK.json", protected) is True
    assert protected_files_gate._is_protected_path("evolve_corpus/cases/new.json", protected) is True
    assert protected_files_gate._is_protected_path("evolve_corpus", protected) is False
    assert protected_files_gate._is_protected_path("thomas/core/example.py", protected) is False


def test_protected_files_gate_diff_range_requires_non_empty_approval(monkeypatch, capsys) -> None:
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(
        protected_files_gate,
        "_changed_files",
        lambda *, base=None, head=None: ["scripts/forge/gates/protected_files_gate.py"],
    )
    monkeypatch.setattr(
        protected_files_gate,
        "_commit_messages",
        lambda base, head: ["fix: gate\n\nThomas-Protected-Files-Approved:   \n"],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False


def test_protected_files_gate_diff_range_allows_approval_trailer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(
        protected_files_gate,
        "_changed_files",
        lambda *, base=None, head=None: ["agent_safety.toml", "thomas/server/app.py"],
    )
    monkeypatch.setattr(
        protected_files_gate,
        "_commit_messages",
        lambda base, head: [
            "fix: protected gate recovery\n\n"
            "Thomas-Protected-Files-Approved: Calvin-approved hardening gate recovery 2026-05-28\n"
        ],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["violations"] == ["agent_safety.toml"]
    assert payload["approved_protected_files"] is True
    assert "Calvin-approved" in payload["approval_reason"]


def test_protected_files_gate_staged_mode_rejects_commit_message_env_trailer(monkeypatch, capsys) -> None:
    # R4 (praxis-unbypassable-2026-05-29): a local staged commit must NOT be
    # self-approvable by setting THOMAS_COMMIT_MESSAGE with an approval trailer.
    # That env is agent-settable, so honoring it locally was a bypass. Local
    # protected-file edits must go through native-auth breakglass instead.
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(
        protected_files_gate,
        "_staged_files",
        lambda: ["scripts/forge/gates/protected_files_gate.py"],
    )
    monkeypatch.setenv(
        "THOMAS_COMMIT_MESSAGE",
        "fix: protected files\n\nThomas-Protected-Files-Approved: self-approved by attacker\n",
    )

    rc = protected_files_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False


def test_bulk_commit_guard_supports_diff_range(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        bulk_commit_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["a.py", "b.py"],
    )

    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["staged_count"] == 2
    assert payload["approved_bulk_change"] is False


def test_bulk_commit_guard_diff_range_allows_approval_trailer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        bulk_commit_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["a.py", "b.py"],
    )
    monkeypatch.setattr(
        bulk_commit_guard,
        "_commit_messages",
        lambda repo_root, base, head: [
            "fix: takeover\n\nThomas-Bulk-Change-Approved: Calvin-approved dirty-tree publish\n"
        ],
    )

    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["approved_bulk_change"] is True
    assert "Calvin-approved" in payload["approval_reason"]


def test_commit_growth_guard_supports_diff_range(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.delenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", raising=False)
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["thomas/new.py"],
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: 0 if rev == "base" else 400,
    )

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/new.py"
    assert payload["approved_growth"] is False


def test_commit_growth_guard_diff_range_allows_approval_trailer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.delenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", raising=False)
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["thomas/large.py"],
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: 10 if rev == "base" else 400,
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_commit_messages",
        lambda repo_root, base, head: [
            "fix: takeover\n\nThomas-Commit-Growth-Approved: Calvin-approved public safety-arc replay\n"
        ],
    )

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["approved_growth"] is True
    assert "Calvin-approved" in payload["approval_reason"]


def test_exception_handler_gate_supports_diff_range(monkeypatch, capsys) -> None:
    monkeypatch.setattr(exception_handler_gate, "_changed_files", lambda *, base=None, head=None: ["thomas/a.py"])
    monkeypatch.setattr(
        exception_handler_gate,
        "_content_at_rev",
        lambda rev, rel: "def f():\n    try:\n        work()\n    except Exception:\n        pass\n",
    )
    monkeypatch.setattr(exception_handler_gate, "_exception_ratchet", lambda: False)
    monkeypatch.setattr(exception_handler_gate, "_require_specific_exceptions", lambda: True)
    monkeypatch.setattr(exception_handler_gate, "_broad_catch_requires", lambda: {"logging"})

    rc = exception_handler_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"] == [{"path": "thomas/a.py", "line": 4}]


def test_changelog_gate_supports_diff_range(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/",))
    monkeypatch.setattr(
        changelog_gate,
        "_changed_files",
        lambda *, base=None, head=None: ["thomas/a.py", "thomas/b.py", "thomas/c.py", "CHANGELOG.md"],
    )
    monkeypatch.setattr(
        changelog_gate,
        "_changelog_diff_content",
        lambda base=None, head=None: "### Fixed\n- gates: support CI diff range mode",
    )

    rc = changelog_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["code_files_staged"] == 3


def test_post_commit_audit_ignores_normal_commit_when_breadcrumb_exists(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    breadcrumb = git_dir / "thomas_precommit_ran"
    breadcrumb.write_text("ok\n", encoding="utf-8")
    audit_log = git_dir / "thomas_noverify_audit.jsonl"

    monkeypatch.setattr(post_commit_audit, "ROOT", root)
    monkeypatch.setattr(post_commit_audit, "BREADCRUMB_FILE", breadcrumb)
    monkeypatch.setattr(post_commit_audit, "AUDIT_LOG", audit_log)

    post_commit_audit.main()

    assert not breadcrumb.exists()
    assert not audit_log.exists()


def test_post_commit_audit_auto_reverts_codex_bypass_and_logs_missing_changelog(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    audit_log = git_dir / "thomas_noverify_audit.jsonl"

    monkeypatch.setattr(post_commit_audit, "ROOT", root)
    monkeypatch.setattr(post_commit_audit, "BREADCRUMB_FILE", git_dir / "thomas_precommit_ran")
    monkeypatch.setattr(post_commit_audit, "AUDIT_LOG", audit_log)
    monkeypatch.setattr(
        post_commit_audit,
        "_git",
        lambda args: {
            ("rev-parse", "HEAD"): "abcdef1234567890",
            ("rev-parse", "--abbrev-ref", "HEAD"): "master",
            ("log", "-1", "--pretty=%s"): "Checkpoint dirty worktree state",
            ("diff", "--name-only", "HEAD~1", "HEAD"): "thomas/a.py\nthomas/b.py\nthomas/c.py\n",
        }.get(tuple(args), ""),
    )
    monkeypatch.setattr(post_commit_audit, "_resolve_agent", lambda: "Codex desktop")
    monkeypatch.setattr(post_commit_audit, "_commit_missing_required_changelog", lambda: True)
    _clear_agent_context(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(root / ".codex"))

    calls: list[list[str]] = []

    def _fake_run(args, cwd=None, capture_output=None, text=None):
        calls.append(list(args))
        assert cwd == root
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(post_commit_audit.subprocess, "run", _fake_run)

    post_commit_audit.main()
    out = capsys.readouterr().out
    rows = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert any(call[:3] == ["git", "reset", "--soft"] for call in calls)
    assert "AUTO-REVERTING COMMIT" in out
    assert "skipped a required CHANGELOG update" in out
    assert rows[0]["bypass_detected"] is True
    assert rows[0]["missing_changelog"] is True
    assert rows[1]["event"] == "auto_revert"
    assert rows[1]["revert_success"] is True


def test_post_commit_audit_human_bypass_warns_but_does_not_reset(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    audit_log = git_dir / "thomas_noverify_audit.jsonl"

    monkeypatch.setattr(post_commit_audit, "ROOT", root)
    monkeypatch.setattr(post_commit_audit, "BREADCRUMB_FILE", git_dir / "thomas_precommit_ran")
    monkeypatch.setattr(post_commit_audit, "AUDIT_LOG", audit_log)
    monkeypatch.setattr(
        post_commit_audit,
        "_git",
        lambda args: {
            ("rev-parse", "HEAD"): "abcdef1234567890",
            ("rev-parse", "--abbrev-ref", "HEAD"): "master",
            ("log", "-1", "--pretty=%s"): "Manual bypass",
            ("diff", "--name-only", "HEAD~1", "HEAD"): "thomas/a.py\n",
        }.get(tuple(args), ""),
    )
    monkeypatch.setattr(post_commit_audit, "_resolve_agent", lambda: "human-user")
    monkeypatch.setattr(post_commit_audit, "_commit_missing_required_changelog", lambda: False)
    _clear_agent_context(monkeypatch)

    def _unexpected_reset(args, cwd=None, capture_output=None, text=None):
        raise AssertionError(f"unexpected subprocess.run call: {args}")

    monkeypatch.setattr(post_commit_audit.subprocess, "run", _unexpected_reset)

    post_commit_audit.main()
    out = capsys.readouterr().out
    rows = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert "WARNING: PRE-COMMIT HOOKS WERE BYPASSED" in out
    assert len(rows) == 1
    assert rows[0]["bypass_detected"] is True
    assert rows[0]["missing_changelog"] is False


# ---------------------------------------------------------------------------
# R4 (praxis-unbypassable-2026-05-29): the unauthenticated guard-disable envs
# must no longer skip the guard. The sanctioned skip path is breakglass SKIP.
# ---------------------------------------------------------------------------


def test_bulk_commit_guard_ignores_disable_env_R4(monkeypatch, capsys) -> None:
    monkeypatch.setenv("THOMAS_BULK_COMMIT_GUARD_DISABLE", "1")
    monkeypatch.setattr(
        bulk_commit_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["a.py", "b.py", "c.py"],
    )
    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False


def test_commit_growth_guard_ignores_disable_env_R4(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", "1")
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["thomas/new.py"],
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: 0 if rev == "base" else 400,
    )
    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False


# ---------------------------------------------------------------------------
# enforcement_integrity fail-closed (2026-06-03 hardening): a protected gate
# must be attestable. Two prior gaps let coverage shrink silently:
#   (1) a script on the protected list but absent from the manifest passed as
#       advisory-only "missing_from_manifest" -- so the active pre-push
#       secret-scan preflight could be rewritten with no integrity alarm;
#   (2) deleting agent_safety.toml collapsed the protected list to [] (not even
#       self-checking), so verify() passed while checking nothing.
# ---------------------------------------------------------------------------


def _setup_integrity(monkeypatch, tmp_path: Path, *, scripts: list[str], manifest: dict[str, str]) -> None:
    """Point enforcement_integrity at a hermetic ROOT + manifest + script list."""
    monkeypatch.setattr(enforcement_integrity, "ROOT", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(enforcement_integrity, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(enforcement_integrity, "_load_protected_scripts", lambda: list(scripts))


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_enforcement_integrity_fails_closed_on_protected_script_missing_hash(monkeypatch, tmp_path, capsys) -> None:
    # Gap (1): a protected-list script with NO manifest hash must FAIL closed.
    _write_script(tmp_path / "gate_a.py", "print('a')\n")
    _write_script(tmp_path / "preflight.py", "print('secret-scan')\n")
    manifest = {"gate_a.py": enforcement_integrity._hash_file(tmp_path / "gate_a.py")}
    _setup_integrity(monkeypatch, tmp_path, scripts=["gate_a.py", "preflight.py"], manifest=manifest)

    rc = enforcement_integrity.verify(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "preflight.py" in payload["missing_from_manifest"]


def test_enforcement_integrity_checks_manifest_entry_even_if_list_shrinks(monkeypatch, tmp_path, capsys) -> None:
    # Gap (2) corollary: a manifest entry is verified even if the live protected
    # list omits it -- deleting the config cannot un-protect a tracked gate.
    _write_script(tmp_path / "gate_a.py", "print('tampered')\n")
    manifest = {"gate_a.py": hashlib.sha256(b"print('good')\n").hexdigest()}
    _setup_integrity(monkeypatch, tmp_path, scripts=[], manifest=manifest)

    rc = enforcement_integrity.verify(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert any(item["path"] == "gate_a.py" for item in payload["tampered"])


def test_enforcement_integrity_missing_toml_still_self_checks(monkeypatch, tmp_path) -> None:
    # Gap (2): with no agent_safety.toml the protected list must still include
    # SELF_PATH (was [] -> verify() checked nothing).
    monkeypatch.setattr(enforcement_integrity, "ROOT", tmp_path)
    assert enforcement_integrity._load_protected_scripts() == [enforcement_integrity.SELF_PATH]


def test_enforcement_integrity_passes_when_manifest_matches(monkeypatch, tmp_path, capsys) -> None:
    # Positive control: list == manifest with matching hashes -> PASS.
    _write_script(tmp_path / "gate_a.py", "print('a')\n")
    manifest = {"gate_a.py": enforcement_integrity._hash_file(tmp_path / "gate_a.py")}
    _setup_integrity(monkeypatch, tmp_path, scripts=["gate_a.py"], manifest=manifest)

    rc = enforcement_integrity.verify(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["missing_from_manifest"] == []


# ---------------------------------------------------------------------------
# staged-files fail-closed (2026-06-03 hardening): a git error while listing
# staged/changed files must FAIL the gate, not look like an empty (clean) change
# set that PASSes. Previously each helper returned [] on `git diff` rc!=0.
# ---------------------------------------------------------------------------


def _git_boom(*_args, **_kwargs):
    raise RuntimeError("git exploded")


class _GitFail:
    returncode = 128
    stdout = ""
    stderr = "fatal: not a git repository"


def test_commit_scope_staged_files_raises_on_git_error(monkeypatch) -> None:
    monkeypatch.setattr(commit_scope_gate.subprocess, "run", lambda *a, **k: _GitFail())
    with pytest.raises(RuntimeError):
        commit_scope_gate._staged_files()


def test_commit_scope_gate_fails_closed_on_git_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_scope_gate, "_staged_files", _git_boom)
    rc = commit_scope_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False


def test_protected_files_gate_fails_closed_on_git_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(protected_files_gate, "_staged_files", _git_boom)
    rc = protected_files_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False


def test_type_safety_gate_fails_closed_on_git_error(monkeypatch, capsys) -> None:
    # mypy must appear installed so the gate reaches the staged-files read.
    monkeypatch.setattr(type_safety_gate.shutil, "which", lambda _name: "/usr/bin/mypy")
    monkeypatch.setattr(type_safety_gate, "_staged_files", _git_boom)
    rc = type_safety_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False


def test_validate_agent_changes_fails_closed_on_git_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(validate_agent_changes, "get_staged_files", _git_boom)
    rc = validate_agent_changes.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED" in out


def test_validate_agent_changes_staged_helper_raises_on_git_error(monkeypatch) -> None:
    monkeypatch.setattr(validate_agent_changes.subprocess, "run", lambda *a, **k: _GitFail())
    with pytest.raises(RuntimeError):
        validate_agent_changes.get_staged_files()


# ---------------------------------------------------------------------------
# skip-policy audit log must be writable from a linked worktree (2026-06-03):
# ROOT/.git is a `gitdir:` POINTER FILE there, not a directory, so the audit log
# (and thus an authorized breakglass skip) could not be written.
# ---------------------------------------------------------------------------


def test_skip_policy_git_dir_follows_worktree_pointer(monkeypatch, tmp_path) -> None:
    real_gitdir = tmp_path / "realgit" / "worktrees" / "wt"
    real_gitdir.mkdir(parents=True)
    fake_root = tmp_path / "wt"
    fake_root.mkdir()
    (fake_root / ".git").write_text(f"gitdir: {real_gitdir}\n", encoding="utf-8")
    monkeypatch.setattr(precommit_skip_policy, "ROOT", fake_root)

    resolved = precommit_skip_policy._git_dir()
    assert resolved == real_gitdir
    assert resolved.is_dir()  # writable: the audit log can land here


def test_skip_policy_git_dir_normal_repo_uses_dot_git(monkeypatch, tmp_path) -> None:
    fake_root = tmp_path / "repo"
    (fake_root / ".git").mkdir(parents=True)
    monkeypatch.setattr(precommit_skip_policy, "ROOT", fake_root)

    assert precommit_skip_policy._git_dir() == fake_root / ".git"
