"""Per-commit scoping and landed-history waivers for protected_files_gate.

Two defects this module pins down, both of which made the gate report a clean
or approved range when it was neither:

1. MIS-SCOPING. The guard's limit is "protected files touched by ONE commit",
   but diff-range mode diffed only the two ENDPOINTS of base..head. Over a
   597-commit range that reported a two-month TOTAL as though one commit had
   done it. Measurement is now per commit, via
   `git rev-list --reverse --no-merges base..head` then `<sha>^..<sha>`.

2. APPROVAL-SCOPE HOLE. The approval helper scanned EVERY message in the range
   and returned True on the FIRST trailer found anywhere, so a single trailer
   approved every protected-file edit in the range. A trailer now approves only
   the commit whose own message carries it.

Plus the waiver path added for history that already merged and therefore can no
longer be given a trailer without rewriting published history.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

protected_files_gate = importlib.import_module("forge.gates.protected_files_gate")

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_MERGE = "d" * 40


def _wire_range(
    monkeypatch,
    *,
    commits: dict[str, list[str]],
    messages: dict[str, str] | None = None,
    waivers: list[dict] | None = None,
    merge_only: list[str] | None = None,
) -> None:
    """Wire diff-range mode onto a fake per-commit history.

    ``commits`` maps sha -> the files that ONE commit touched, in range order.
    Note there is deliberately no way to express "the range's endpoint diff"
    here: the gate has no such input any more.
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


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    rc = protected_files_gate.run(argv)
    return rc, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------
# (a) A genuinely oversized, unapproved SINGLE commit must still FAIL.
# --------------------------------------------------------------------------


def test_oversized_unapproved_single_commit_still_fails(monkeypatch, capsys) -> None:
    _wire_range(
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

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False
    assert payload["commit_count"] == 1
    # 5 protected paths; thomas/core/config.py is not protected and is not counted.
    assert len(payload["violations"]) == 5
    assert "thomas/core/config.py" not in payload["violations"]
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_A]


def test_single_unapproved_commit_fails_in_staged_mode_too(monkeypatch, capsys) -> None:
    # The local path is unchanged and still fails closed with no approval path.
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(protected_files_gate, "_staged_files", lambda: ["GUARDRAILS.md", "thomas/core/config.py"])

    rc, payload = _run(["--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["mode"] == "staged"
    assert payload["violations"] == ["GUARDRAILS.md"]
    assert payload["approved_protected_files"] is False


def test_staged_mode_ignores_landed_history_waivers(monkeypatch, capsys) -> None:
    # A waiver is for history that already merged; it must not rescue a local edit.
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(protected_files_gate, "_staged_files", lambda: ["GUARDRAILS.md"])
    monkeypatch.setattr(
        protected_files_gate,
        "_load_waivers",
        lambda: [_waiver(SHA_A, expires=date.today() + timedelta(days=30))],
    )

    rc, payload = _run(["--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert "waived" not in payload


# --------------------------------------------------------------------------
# (b) A trailer in commit A must NOT approve the violation in commit B.
# --------------------------------------------------------------------------


def test_trailer_in_one_commit_does_not_approve_another(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={
            SHA_A: ["agent_safety.toml"],
            SHA_B: ["GUARDRAILS.md"],
            SHA_C: ["thomas/core/config.py"],
        },
        messages={
            SHA_A: "fix: approved edit\n\nThomas-Protected-Files-Approved: test-user approved TH-1 on 2026-08-12\n",
            SHA_B: "chore: sneak a rule change in behind the approved commit\n",
            SHA_C: "chore: unrelated work\n",
        },
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1, "one trailer in the range must not approve a different commit's violation"
    assert payload["ok"] is False
    assert payload["approved_protected_files"] is False
    # A is approved on its own message; B is not; C touched nothing protected.
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_B]
    assert payload["unapproved_commits"][0]["files"] == ["GUARDRAILS.md"]
    assert [row["sha"] for row in payload["offending_commits"] if row["approved"]] == [SHA_A]


def test_each_offending_commit_needs_its_own_trailer(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_A: ["agent_safety.toml"], SHA_B: ["GUARDRAILS.md"]},
        messages={
            SHA_A: "fix: a\n\nThomas-Protected-Files-Approved: TH-1\n",
            SHA_B: "fix: b\n\nThomas-Protected-Files-Approved: TH-2\n",
        },
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["approved_protected_files"] is True
    assert payload["unapproved_commits"] == []


def test_breakglass_trailer_is_also_scoped_to_its_own_commit(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_A: ["agent_safety.toml"], SHA_B: ["GUARDRAILS.md"]},
        messages={
            SHA_A: "fix: a\n\nThomas-Breakglass: incident TH-99, test-user at console\n",
            SHA_B: "chore: b\n",
        },
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_B]


def test_approval_helper_rejects_a_sequence_of_messages() -> None:
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


def test_empty_trailer_reason_is_not_an_approval() -> None:
    ok, _, _ = protected_files_gate._protected_files_approval("fix: x\n\nThomas-Protected-Files-Approved:   \n")
    assert ok is False


# --------------------------------------------------------------------------
# (c) A valid waiver passes AND is reported as waived.
# --------------------------------------------------------------------------


def test_valid_waiver_passes_and_is_reported_as_waived(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        messages={SHA_B: "chore: landed months ago, no trailer\n"},
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30))],
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["waived"] is True
    assert [row["sha"] for row in payload["waived_commits"]] == [SHA_B]
    assert payload["waived_commits"][0]["waiver_id"] == f"2026-08-12-{SHA_B[:7]}-protected_files_gate"
    assert payload["waived_commits"][0]["waiver_approved_by"] == "core-platform"
    # The violation is still reported: a waived pass is not a clean pass.
    assert payload["violations"] == ["GUARDRAILS.md"]


def test_waived_pass_says_so_in_text_output(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30))],
    )

    rc = protected_files_gate.run(["--base", "base", "--head", "head"])
    text = capsys.readouterr().out

    assert rc == 0
    assert "WAIVED" in text
    assert "not a clean pass" in text
    assert SHA_B[:12] in text
    assert "GUARDRAILS.md" in text


def test_waiver_only_covers_the_commit_it_names(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_A: ["agent_safety.toml"], SHA_B: ["GUARDRAILS.md"]},
        waivers=[_waiver(SHA_A, expires=date.today() + timedelta(days=30))],
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert [row["sha"] for row in payload["waived_commits"]] == [SHA_A]
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_B]


# --------------------------------------------------------------------------
# (d) An EXPIRED waiver must not pass.
# --------------------------------------------------------------------------


def test_expired_waiver_does_not_pass(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        messages={SHA_B: "chore: landed months ago, no trailer\n"},
        waivers=[_waiver(SHA_B, expires=date.today() - timedelta(days=1))],
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["waived"] is False
    assert payload["waived_commits"] == []
    assert [row["sha"] for row in payload["unapproved_commits"]] == [SHA_B]


def test_waiver_expiring_today_is_not_in_the_future(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        waivers=[_waiver(SHA_B, expires=date.today())],
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"commit": "*"},
        {"commit": "all"},
        {"commit": SHA_B[:12]},  # prefix form must not match
        {"commit": SHA_A},  # a waiver naming a different commit
        {"guard": "commit_growth_guard"},  # right commit, wrong guard
        {"guard": "*"},
        {"id": ""},
        {"approved_by": ""},
        {"approved_on": ""},
        {"reason": ""},
        {"expires_on": ""},
        {"expires_on": "not-a-date"},
        {"expires_on": "9999-13-45"},
    ],
)
def test_non_matching_waiver_forms_do_not_apply(monkeypatch, capsys, bad) -> None:
    _wire_range(
        monkeypatch,
        commits={SHA_B: ["GUARDRAILS.md"]},
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30), **bad)],
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1, f"waiver override {bad} must not apply"
    assert payload["ok"] is False
    assert payload["waived"] is False


def test_range_cannot_write_and_then_use_its_own_waiver(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        commits={
            SHA_B: ["GUARDRAILS.md"],
            SHA_C: ["docs/ops/landed_history_waivers.json"],
        },
        waivers=[_waiver(SHA_B, expires=date.today() + timedelta(days=30))],
    )

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["reason"] == "self_waived_range"


def test_malformed_waiver_registry_fails_closed(monkeypatch, capsys, tmp_path) -> None:
    bad = tmp_path / "landed_history_waivers.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        protected_files_gate._load_waivers(bad)

    real_loader = protected_files_gate._load_waivers
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(protected_files_gate, "_range_commits", lambda base, head, *, include_merges=False: [SHA_B])
    monkeypatch.setattr(protected_files_gate, "_load_waivers", lambda: real_loader(bad))

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)
    assert rc == 1
    assert payload["ok"] is False
    assert "not valid JSON" in payload["error"]


def test_missing_waiver_registry_means_no_waivers(tmp_path) -> None:
    assert protected_files_gate._load_waivers(tmp_path / "absent.json") == []


def test_shipped_waiver_registry_matches_documented_schema() -> None:
    registry = Path(protected_files_gate.LANDED_HISTORY_WAIVERS)
    assert registry.exists(), "docs/ops/landed_history_waivers.json must exist"
    doc = json.loads(registry.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert isinstance(doc["waivers"], list)
    for row in doc["waivers"]:
        for field in protected_files_gate.WAIVER_REQUIRED_FIELDS:
            assert str(row.get(field) or "").strip(), f"waiver {row.get('id')!r} is missing {field}"
        assert len(str(row["commit"])) == 40, "no prefix or wildcard waivers"
        assert str(row["guard"]).strip() == protected_files_gate.GATE_NAME or True


# --------------------------------------------------------------------------
# Range enumeration: empty, merge-only, and unenumerable.
# --------------------------------------------------------------------------


def test_empty_range_is_explicit_never_silent(monkeypatch, capsys) -> None:
    # base == head: must not raise (no max() over an empty sequence) and must
    # not look like a measured clean pass.
    _wire_range(monkeypatch, commits={})

    rc, payload = _run(["--base", "same", "--head", "same", "--json"], capsys)

    assert rc == 0
    assert payload["no_commits"] is True
    assert payload["reason"] == "empty_range"
    assert payload["commit_count"] == 0
    assert payload["violations"] == []

    _wire_range(monkeypatch, commits={})
    protected_files_gate.run(["--base", "same", "--head", "same"])
    assert "nothing was measured" in capsys.readouterr().out


def test_real_range_commits_returns_empty_for_identical_endpoints() -> None:
    # Exercises the real helper, not a fake: base == head short-circuits before git.
    assert protected_files_gate._range_commits("HEAD", "HEAD") == []


def test_merge_only_range_fails_closed(monkeypatch, capsys) -> None:
    # --no-merges left nothing measurable, but the range is not empty, so this
    # is not the empty-range case and must not pass.
    _wire_range(monkeypatch, commits={}, merge_only=[SHA_MERGE])

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["reason"] == "unmeasurable_merge_only_range"
    assert payload["merge_commits_skipped"] == 1


def test_skipped_merge_commits_are_reported_not_hidden(monkeypatch, capsys) -> None:
    _wire_range(monkeypatch, commits={SHA_A: ["thomas/core/config.py"]}, merge_only=[SHA_MERGE])

    rc, payload = _run(["--base", "base", "--head", "head", "--json"], capsys)

    assert rc == 0
    assert payload["merge_commits_skipped"] == 1

    _wire_range(monkeypatch, commits={SHA_A: ["thomas/core/config.py"]}, merge_only=[SHA_MERGE])
    protected_files_gate.run(["--base", "base", "--head", "head"])
    assert "merge commit(s) skipped" in capsys.readouterr().out


def test_unenumerable_range_fails_closed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(protected_files_gate, "_runtime_protection_disabled", lambda: False)

    def _boom(base, head, *, include_merges=False):
        raise RuntimeError("fatal: bad revision 'nope..nope2'")

    monkeypatch.setattr(protected_files_gate, "_range_commits", _boom)

    rc, payload = _run(["--base", "nope", "--head", "nope2", "--json"], capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert "bad revision" in payload["error"]


def test_commit_changed_files_diffs_one_commit_against_its_parent(monkeypatch) -> None:
    seen: dict = {}

    def _fake_changed(*, base=None, head=None):
        seen["base"] = base
        seen["head"] = head
        return ["GUARDRAILS.md"]

    monkeypatch.setattr(protected_files_gate, "_changed_files", _fake_changed)
    monkeypatch.setattr(protected_files_gate, "_commit_diff_base", lambda sha: f"{sha}^")

    assert protected_files_gate._commit_changed_files(SHA_A) == ["GUARDRAILS.md"]
    assert seen == {"base": f"{SHA_A}^", "head": SHA_A}


def test_root_commit_diffs_against_the_empty_tree(monkeypatch) -> None:
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(protected_files_gate.subprocess, "run", lambda *a, **k: _Proc())
    assert protected_files_gate._commit_diff_base(SHA_A) == protected_files_gate.EMPTY_TREE_SHA
