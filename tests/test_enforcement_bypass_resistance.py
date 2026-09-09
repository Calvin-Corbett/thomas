from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from datetime import date, timedelta
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


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _wire_protected_range(
    monkeypatch,
    *,
    commits: dict[str, list[str]],
    messages: dict[str, str] | None = None,
    waivers: list[dict] | None = None,
    merge_only: list[str] | None = None,
) -> None:
    """Wire the diff-range mode onto a fake per-commit history.

    ``commits`` maps sha -> files that ONE commit touched, in range order.
    """
    order = list(commits)
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(
        protected_files_gate,
        "_range_commits",
        lambda base, head, *, include_merges=False: list(merge_only or []) + order if include_merges else order,
    )
    monkeypatch.setattr(protected_files_gate, "_commit_changed_files", lambda sha: list(commits.get(sha, [])))
    monkeypatch.setattr(protected_files_gate, "_commit_message", lambda sha: (messages or {}).get(sha, "chore: work"))
    monkeypatch.setattr(protected_files_gate, "_load_waivers", lambda: list(waivers or []))


def test_protected_files_gate_supports_diff_range(monkeypatch, capsys) -> None:
    _wire_protected_range(monkeypatch, commits={SHA_A: ["agent_safety.toml"]})

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
    _wire_protected_range(
        monkeypatch,
        commits={SHA_A: ["scripts/forge/gates/protected_files_gate.py"]},
        messages={SHA_A: "fix: gate\n\nThomas-Protected-Files-Approved:   \n"},
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False


def test_protected_files_gate_diff_range_allows_approval_trailer(monkeypatch, capsys) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={SHA_A: ["agent_safety.toml", "thomas/server/app.py"]},
        messages={
            SHA_A: (
                "fix: protected gate recovery\n\n"
                "Thomas-Protected-Files-Approved: test-user-approved hardening gate recovery 2026-05-28\n"
            )
        },
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["violations"] == ["agent_safety.toml"]
    assert payload["approved_protected_files"] is True
    assert "test-user-approved" in payload["approval_reason"]


def _waiver(sha: str, *, expires: date, guard: str = "protected_files_gate", **overrides) -> dict:
    row = {
        "id": f"2026-08-12-{sha[:7]}-{guard}",
        "commit": sha,
        "guard": guard,
        "approved_by": "core-platform",
        "approved_on": "2026-08-12",
        "expires_on": expires.isoformat(),
        "reason": "Landed before the gate measured per commit; cannot be reworded retroactively.",
    }
    row.update(overrides)
    return row


# (a) A genuinely oversized, unapproved SINGLE commit must still FAIL.
def test_protected_files_gate_single_unapproved_commit_still_fails(monkeypatch, capsys) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={
            SHA_A: [
                "GUARDRAILS.md",
                "AGENTS.md",
                "agent_safety.toml",
                "tests/test_architecture.py",
                "scripts/forge/gates/protected_files_gate.py",
                "thomas/core/config.py",
            ]
        },
        messages={SHA_A: "feat: relax the rules that were in my way\n"},
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False
    assert payload["commit_count"] == 1
    # 5 protected paths; thomas/core/config.py is not protected and is not counted.
    assert len(payload["violations"]) == 5
    assert "thomas/core/config.py" not in payload["violations"]
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_A]


# (b) A trailer in commit A must NOT approve the violation in commit B.
def test_protected_files_gate_trailer_does_not_approve_other_commits(monkeypatch, capsys) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={
            SHA_A: ["agent_safety.toml"],
            SHA_B: ["GUARDRAILS.md"],
            SHA_C: ["thomas/core/config.py"],
        },
        messages={
            SHA_A: ("fix: approved edit\n\nThomas-Protected-Files-Approved: test-user approved TH-1 on 2026-08-12\n"),
            SHA_B: "chore: sneak a rule change in behind the approved commit\n",
            SHA_C: "chore: unrelated work\n",
        },
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1, "one trailer in the range must not approve a different commit's violation"
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False
    # A is approved on its own message; B is not; C touched nothing protected.
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_B]
    assert payload["unapproved_commits"][0]["files"] == ["GUARDRAILS.md"]
    approved_shas = [row["sha"] for row in payload["offending_commits"] if row["approved"]]
    assert approved_shas == [SHA_A]


def test_protected_files_approval_rejects_a_sequence_of_messages() -> None:
    # Structural guard: the range-wide shape must be impossible to pass in.
    with pytest.raises(TypeError):
        protected_files_gate._protected_files_approval(
            ["fix: x\n\nThomas-Protected-Files-Approved: approved\n", "chore: y\n"]
        )

    ok, trailer, reason = protected_files_gate._protected_files_approval(
        "fix: x\n\nThomas-Protected-Files-Approved: approved by test-user\n"
    )
    assert ok is True
    assert trailer == "thomas-protected-files-approved"
    assert reason == "approved by test-user"


# (c) A valid waiver passes AND is reported as waived.
def test_protected_files_gate_valid_waiver_passes_and_is_reported(monkeypatch, capsys) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        messages={SHA_B: "chore: landed months ago, no trailer\n"},
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30))],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["waived"] is True
    assert [row["sha"] for row in payload["waived_commits"]] == [SHA_B]
    assert payload["waived_commits"][0]["waiver_id"] == f"2026-08-12-{SHA_B[:7]}-protected_files_gate"
    assert payload["waived_commits"][0]["waiver_approved_by"] == "core-platform"
    # The violation is still reported: a waived pass is not a clean pass.
    assert payload["violations"] == ["GUARDRAILS.md"]

    _wire_protected_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        messages={SHA_B: "chore: landed months ago, no trailer\n"},
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30))],
    )
    rc_text = protected_files_gate.run(["--base", "base", "--head", "head"])
    text = capsys.readouterr().out
    assert rc_text == 0
    assert "WAIVED" in text
    assert "not a clean pass" in text
    assert SHA_B[:12] in text


# (d) An EXPIRED waiver must not pass.
def test_protected_files_gate_expired_waiver_does_not_pass(monkeypatch, capsys) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        messages={SHA_B: "chore: landed months ago, no trailer\n"},
        waivers=[_waiver(SHA_B, expires=date.today() - timedelta(days=1))],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["waived"] is False
    assert payload["waived_commits"] == []
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_B]


def test_protected_files_gate_waiver_expiring_today_is_not_in_the_future(monkeypatch, capsys) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        waivers=[_waiver(SHA_B, expires=date.today())],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"commit": "*"},
        {"commit": "all"},
        {"commit": SHA_B[:12]},  # prefix form must not match
        {"commit": SHA_A},  # a waiver for a different commit
        {"guard": "commit_growth_guard"},  # right commit, wrong guard
        {"approved_by": ""},
        {"approved_on": ""},
        {"reason": ""},
        {"id": ""},
        {"expires_on": ""},
        {"expires_on": "not-a-date"},
    ],
)
def test_protected_files_gate_rejects_non_matching_waiver_forms(monkeypatch, capsys, bad) -> None:
    _wire_protected_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30), **bad)],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1, f"waiver override {bad} must not apply"
    assert payload["ok"] is False
    assert payload["waived"] is False


def test_protected_files_gate_range_cannot_waive_itself(monkeypatch, capsys) -> None:
    # A range may not both write the waiver registry and lean on it.
    _wire_protected_range(
        monkeypatch,
        commits={
            SHA_B: ["GUARDRAILS.md"],
            SHA_C: ["docs/ops/landed_history_waivers.json"],
        },
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30))],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["reason"] == "self_waived_range"


def test_protected_files_gate_empty_range_is_explicit_not_silent(monkeypatch, capsys) -> None:
    # base == head: must not raise, must not look like a measured clean pass.
    _wire_protected_range(monkeypatch, commits={})

    rc = protected_files_gate.run(["--base", "same", "--head", "same", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["no_commits"] is True
    assert payload["reason"] == "empty_range"
    assert payload["commit_count"] == 0
    assert payload["violations"] == []

    _wire_protected_range(monkeypatch, commits={})
    protected_files_gate.run(["--base", "same", "--head", "same"])
    assert "nothing was measured" in capsys.readouterr().out


def test_protected_files_gate_merge_only_range_fails_closed(monkeypatch, capsys) -> None:
    # --no-merges left nothing measurable, but the range is not empty.
    _wire_protected_range(monkeypatch, commits={}, merge_only=["d" * 40])

    rc = protected_files_gate.run(["--base", "base", "--head", "head", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["reason"] == "unmeasurable_merge_only_range"
    assert payload["merge_commits_skipped"] == 1


def test_protected_files_gate_fails_closed_when_range_cannot_be_enumerated(monkeypatch, capsys) -> None:
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)

    def _boom(base, head, *, include_merges=False):
        raise RuntimeError("fatal: bad revision 'nope..nope2'")

    monkeypatch.setattr(protected_files_gate, "_range_commits", _boom)

    rc = protected_files_gate.run(["--base", "nope", "--head", "nope2", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "bad revision" in payload["error"]


def test_protected_files_gate_waiver_registry_matches_documented_schema() -> None:
    registry = Path(protected_files_gate.LANDED_HISTORY_WAIVERS)
    assert registry.exists(), "docs/ops/landed_history_waivers.json must exist"
    doc = json.loads(registry.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert isinstance(doc["waivers"], list)
    for row in doc["waivers"]:
        for field in protected_files_gate.WAIVER_REQUIRED_FIELDS:
            assert str(row.get(field) or "").strip(), f"waiver {row.get('id')!r} is missing {field}"
        assert len(str(row["commit"])) == 40, "no prefix/wildcard waivers"


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


# ---------------------------------------------------------------------------
# bulk_commit_guard diff-range mode (2026-08-12 scoping fix).
#
# The guard's limit is a PER COMMIT limit. Diff-range mode used to diff only
# the two endpoints of base..head and compare that one number against it, so a
# 597-commit range reported the two-month total (1923 files) as if one commit
# had done it. And its approval helper scanned every message in the range and
# returned True on the first trailer found anywhere, so one trailer approved
# every oversized commit in the range.
#
# Full per-commit / waiver coverage: tests/test_bulk_commit_guard_per_commit.py
# ---------------------------------------------------------------------------

_BULK_SHA_A = "a" * 40
_BULK_SHA_B = "b" * 40


def _bulk_fake_range(monkeypatch, commits, *, endpoint=None) -> None:
    """Fake an ordered range of commits: {sha: (changed_files, message)}."""
    monkeypatch.setattr(bulk_commit_guard, "_range_commits", lambda repo_root, base, head: list(commits))
    monkeypatch.setattr(bulk_commit_guard, "_commit_changed_files", lambda repo_root, sha: list(commits[sha][0]))
    monkeypatch.setattr(bulk_commit_guard, "_commit_message", lambda repo_root, sha: commits[sha][1])
    monkeypatch.setattr(
        bulk_commit_guard,
        "_git_lines",
        lambda repo_root, args, *, what="": list(endpoint or []),
    )


def test_bulk_commit_guard_supports_diff_range(monkeypatch, capsys) -> None:
    _bulk_fake_range(monkeypatch, {_BULK_SHA_A: (["a.py", "b.py"], "chore: two files\n")})

    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["staged_count"] == 2
    assert payload["approved_bulk_change"] is False


def test_bulk_commit_guard_diff_range_allows_approval_trailer(monkeypatch, capsys) -> None:
    _bulk_fake_range(
        monkeypatch,
        {
            _BULK_SHA_A: (
                ["a.py", "b.py"],
                "fix: takeover\n\nThomas-Bulk-Change-Approved: test-user-approved dirty-tree publish\n",
            )
        },
    )

    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["approved_bulk_change"] is True
    assert "test-user-approved" in payload["approval_reason"]


def test_bulk_commit_guard_trailer_does_not_approve_another_commit(monkeypatch, capsys) -> None:
    # One trailer used to approve every oversized commit in the range.
    _bulk_fake_range(
        monkeypatch,
        {
            _BULK_SHA_A: (["a.py", "b.py"], "fix: approved\n\nThomas-Bulk-Change-Approved: reviewed\n"),
            _BULK_SHA_B: (["c.py", "d.py"], "fix: not approved\n"),
        },
    )

    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert [row["sha"] for row in payload["violations"]] == [_BULK_SHA_B]
    assert payload["approved_bulk_change"] is False


def test_commit_growth_guard_supports_diff_range(monkeypatch, capsys) -> None:
    # Diff-range mode measures EACH commit against its own parent, so the seams
    # are per-commit now. Full scoping/approval/waiver proofs live in
    # tests/test_commit_growth_guard_per_commit.py.
    sha, parent = "a" * 40, "1" * 40
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.delenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", raising=False)
    monkeypatch.setattr(commit_growth_guard, "_range_commits", lambda repo_root, base, head: [sha])
    monkeypatch.setattr(commit_growth_guard, "_range_all_commits", lambda repo_root, base, head: [sha])
    monkeypatch.setattr(commit_growth_guard, "_commit_parent", lambda repo_root, s: parent)
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["thomas/new.py"],
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: 0 if rev == parent else 400,
    )
    monkeypatch.setattr(commit_growth_guard, "_commit_message", lambda repo_root, s: "feat: dump")
    monkeypatch.setattr(commit_growth_guard, "_load_waivers", lambda repo_root: [])

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/new.py"
    assert payload["approved_growth"] is False


def test_commit_growth_guard_diff_range_allows_approval_trailer(monkeypatch, capsys) -> None:
    # A trailer approves ONLY the commit whose own message carries it. The
    # cross-commit leak this used to allow is covered in
    # tests/test_commit_growth_guard_per_commit.py.
    sha, parent = "a" * 40, "1" * 40
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.delenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", raising=False)
    monkeypatch.setattr(commit_growth_guard, "_range_commits", lambda repo_root, base, head: [sha])
    monkeypatch.setattr(commit_growth_guard, "_range_all_commits", lambda repo_root, base, head: [sha])
    monkeypatch.setattr(commit_growth_guard, "_commit_parent", lambda repo_root, s: parent)
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["thomas/large.py"],
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: 10 if rev == parent else 400,
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_commit_message",
        lambda repo_root, s: (
            "fix: takeover\n\nThomas-Commit-Growth-Approved: test-user-approved public safety-arc replay\n"
        ),
    )
    monkeypatch.setattr(commit_growth_guard, "_load_waivers", lambda repo_root: [])

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["approved_growth"] is True
    assert "test-user-approved" in payload["approval_reason"]


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
    _bulk_fake_range(monkeypatch, {_BULK_SHA_A: (["a.py", "b.py", "c.py"], "chore: three files\n")})
    rc = bulk_commit_guard.run(Path("."), max_files=1, json_output=True, base="base", head="head")
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    # Fails on the measurement itself, not because the range was unresolvable.
    assert payload["violations"][0]["files"] == 3
    assert payload["error"] == ""


def test_commit_growth_guard_ignores_disable_env_R4(monkeypatch, capsys) -> None:
    sha, parent = "a" * 40, "1" * 40
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", "1")
    monkeypatch.setattr(commit_growth_guard, "_range_commits", lambda repo_root, base, head: [sha])
    monkeypatch.setattr(commit_growth_guard, "_range_all_commits", lambda repo_root, base, head: [sha])
    monkeypatch.setattr(commit_growth_guard, "_commit_parent", lambda repo_root, s: parent)
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: ["thomas/new.py"],
    )
    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: 0 if rev == parent else 400,
    )
    monkeypatch.setattr(commit_growth_guard, "_commit_message", lambda repo_root, s: "feat: dump")
    monkeypatch.setattr(commit_growth_guard, "_load_waivers", lambda repo_root: [])
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
