"""What the promoter checked is what lands, and the tree that would land is checked itself.

The caged account can write every hand-in folder in the inbox (scripts/cage/prepare_caged_server.ps1), and until
2026-10-09 the promoter read ``change.patch`` three times: hashed, checked as text, and applied by path, with the writer
audit (up to 120 s) in between. A patch rewritten between those reads landed unchecked. Now it is read once, those bytes
are checked and applied, and the tree git built is judged too: a symlink, a submodule, a mode change, a path that is
not plain ASCII, has a "~" or is over 200 characters, ``runtime/``, the approval cards themselves, or a .gitattributes
or .gitmodules, whatever the patch text said. Cards show each file from its own bytes, whatever any .gitattributes says.

Cancel on a guarded file leaves out exactly that file. The running copy is checked again right after your answer: the
prompt has no timeout, and the caged account can change files there while it is up; and a dev that moved meanwhile
means the new tree is asked about again.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests.green_support import git
from tests.test_a_self_fix_lands_only_when_you_approve import (  # noqa: F401
    Asker,
    _outbox,
    _promoter,
    _submit,
    blue,
    pins,
)


def _restamp(sub: Path, old: bytes, new: bytes) -> None:
    """A hand-in whose patch was made this way: the patch and the hash recorded with it agree."""
    patch = (sub / "change.patch").read_bytes().replace(old, new)
    (sub / "change.patch").write_bytes(patch)
    manifest = json.loads((sub / "submission.json").read_text(encoding="utf-8"))
    manifest["patch_sha256"] = hashlib.sha256(patch).hexdigest()
    (sub / "submission.json").write_text(json.dumps(manifest), encoding="utf-8")


def _crafted_tree(repo: Path, entries: list[tuple[str, str, str]]) -> str:
    """dev's tree with *entries* (mode, object id, path) put in place, built in a private index."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        run = {"cwd": repo, "env": env, "capture_output": True, "text": True, "check": True}
        subprocess.run(["git", "read-tree", "dev"], **run)
        for mode, oid, path in entries:
            # Git for Windows will not put a quote in an index it checks out; a tree can still carry one.
            add = [
                "git",
                "-c",
                "core.protectNTFS=false",
                "update-index",
                "--add",
                "--cacheinfo",
                f"{mode},{oid},{path}",
            ]
            subprocess.run(add, **run)
        return subprocess.run(["git", "write-tree"], **run).stdout.strip()


def _blob(repo: Path, text: str) -> str:
    done = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=text, capture_output=True, text=True)
    return done.stdout.strip()


_RUNTIME_PATCH = (
    b"diff --git a/runtime/evil.json b/runtime/evil.json\n"
    b"new file mode 100644\n"
    b"--- /dev/null\n"
    b"+++ b/runtime/evil.json\n"
    b"@@ -0,0 +1 @@\n"
    b"+{}\n"
)


# -- read once -------------------------------------------------------------------------------------------------- #


def test_a_patch_rewritten_after_its_check_is_not_what_lands(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-swap-late", {"thomas/fix_me.py": "VALUE = 2\n"})

    def audit(_repo: Path) -> list[str]:  # runs after the patch was read and checked, before it is applied
        patch = (sub / "change.patch").read_bytes()
        (sub / "change.patch").write_bytes(patch.replace(b"VALUE = 2", b"VALUE = 9"))
        return []

    ask = Asker(True)
    outcome = _promoter(blue, pins, ask, audit=audit).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2", "what was checked is what landed"
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert "+VALUE = 9" not in _outbox(sub.name, "verdict").get("detail", "")


def test_a_rewritten_patch_cannot_carry_a_path_past_the_check(blue: Path, pins: Path) -> None:
    """The text check refuses runtime/; a patch rewritten after it must not reach runtime/ anyway."""
    sub = _submit(blue, "exec-swap-path", {"thomas/fix_me.py": "VALUE = 2\n"})

    def audit(_repo: Path) -> list[str]:
        (sub / "change.patch").write_bytes(_RUNTIME_PATCH)
        return []

    outcome = _promoter(blue, pins, Asker(True), audit=audit).promote(sub)

    assert "runtime/evil.json" not in git(blue, "ls-tree", "-r", "--name-only", "dev")
    assert not (blue / "runtime").exists()
    assert outcome.status == "landed" and git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2"


def test_the_files_named_in_a_conflict_come_from_the_patch_that_was_read(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-swap-conflict", {"thomas/fix_me.py": "VALUE = 2\n"})
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 3\n", encoding="utf-8")
    git(blue, "commit", "-qam", "dev moved on under it")

    def audit(_repo: Path) -> list[str]:
        (sub / "change.patch").write_bytes(b"not a patch at all\n")
        return []

    outcome = _promoter(blue, pins, Asker(True), audit=audit).promote(sub)

    assert outcome.status == "refused" and outcome.detail.startswith("the change no longer applies to dev")
    assert outcome.conflicts == ["thomas/fix_me.py"], outcome.detail


def test_derive_tree_still_takes_a_patch_file(blue: Path) -> None:
    """tests/test_a_dev_moved_repair_starts_merged.py checks a repair with a patch file; bytes and a file give one
    tree."""
    sub = _submit(blue, "exec-path-or-bytes", {"thomas/fix_me.py": "VALUE = 2\n"})
    dev = git(blue, "rev-parse", "dev")
    patch = sub / "change.patch"
    assert checks.derive_tree(blue, dev, patch) == checks.derive_tree(blue, dev, patch.read_bytes())


def test_read_submission_returns_the_exact_bytes_it_hashed(blue: Path) -> None:
    sub = _submit(blue, "exec-read-once", {"thomas/fix_me.py": "VALUE = 2\n"})
    meta, patch = checks.read_submission(sub)
    assert meta == checks.load_submission(sub)
    assert hashlib.sha256(patch).hexdigest() == meta["patch_sha256"]
    assert patch == (sub / "change.patch").read_bytes()


# -- the tree that would land ------------------------------------------------------------------------------------ #


def _tree_case(blue: Path, case: str) -> list[tuple[str, str, str]]:
    blob = _blob(blue, "X = 1\n")
    old = git(blue, "rev-parse", "dev:thomas/fix_me.py")
    head = git(blue, "rev-parse", "dev")
    return {
        "a symlink": [("120000", _blob(blue, "../outside"), "thomas/link")],
        "a submodule": [("160000", head, "vendor/sub")],
        "a mode change": [("100755", old, "thomas/fix_me.py")],
        "runtime": [("100644", blob, "runtime/state.json")],
        "a right-to-left mark": [("100644", blob, "thomas/a‮b.py")],
        "a space": [("100644", blob, "thomas/a b.py")],
        "a quote": [("100644", blob, 'thomas/a"b.py')],
        "a path over 200 characters": [("100644", blob, "thomas/" + "x" * 194 + ".py")],
        "the approval cards": [("100644", blob, "scripts/cage/card_catalogue.py")],
        "the approval cards, in other letters": [("100644", blob, "scripts/cage/Card_Catalogue.py")],
        "a .gitattributes": [("100644", _blob(blue, "*.py -diff\n"), ".gitattributes")],
        "a .gitattributes in a folder, in other letters": [("100644", blob, "tests/.GitAttributes")],
        "a .gitmodules": [("100644", blob, ".gitmodules")],
        "an 8.3 short name": [("100644", blob, "thomas/server/TOOL_M~1/new.json")],
    }[case]


@pytest.mark.parametrize(
    ("case", "words"),
    [
        ("a symlink", "symlink or submodule"),
        ("a submodule", "symlink or submodule"),
        ("a mode change", "file mode"),
        ("runtime", "may not change"),
        ("a right-to-left mark", "plain printable ASCII"),
        ("a space", "plain printable ASCII"),
        ("a quote", "plain printable ASCII"),
        ("a path over 200 characters", "plain printable ASCII"),
        ("the approval cards", "approval cards"),
        ("the approval cards, in other letters", "approval cards"),
        ("a .gitattributes", "how git shows every other file"),
        ("a .gitattributes in a folder, in other letters", "how git shows every other file"),
        ("a .gitmodules", "how git shows every other file"),
        ("an 8.3 short name", "plain printable ASCII"),
    ],
)
def test_the_tree_git_built_is_judged_whatever_the_patch_said(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch, case: str, words: str
) -> None:
    execution = "exec-tree-" + "".join(ch for ch in case if ch.isalnum())[:30]
    sub = _submit(blue, execution, {"thomas/fix_me.py": "VALUE = 2\n"})
    before = git(blue, "rev-parse", "dev")
    crafted = _crafted_tree(blue, _tree_case(blue, case))
    monkeypatch.setattr(checks, "derive_tree", lambda *_a, **_k: crafted)
    ask = Asker(True, True, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and words in outcome.detail, outcome.detail
    assert ask.asked == [], "refused before any card"
    assert git(blue, "rev-parse", "dev") == before


def test_a_path_that_is_not_plain_ascii_in_the_patch_is_refused_before_any_card(blue: Path, pins: Path) -> None:
    """The text check reads a raw UTF-8 header as a path; git builds it; the tree check refuses it."""
    sub = _submit(blue, "exec-bidi", {"thomas/new_name.py": "X = 1\n"})
    _restamp(sub, b"thomas/new_name.py", "thomas/a‮b.py".encode())
    before = git(blue, "rev-parse", "dev")
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "plain printable ASCII" in outcome.detail, outcome.detail
    assert ask.asked == []
    assert git(blue, "rev-parse", "dev") == before


def test_a_self_fix_cannot_edit_the_approval_cards(blue: Path, pins: Path) -> None:
    """Landed, a changed catalogue no longer matches its pin, and every hand-in after it would wait for a re-pin."""
    sub = _submit(blue, "exec-cards", {"scripts/cage/card_catalogue.py": "KINDS = {}\n"})
    ask = Asker(True, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "approval cards" in outcome.detail, outcome.detail
    assert ask.asked == []


def test_an_ordinary_tree_passes_the_tree_check(blue: Path) -> None:
    sub = _submit(blue, "exec-ordinary", {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "N = 1\n"})
    dev = git(blue, "rev-parse", "dev")
    tree = checks.derive_tree(blue, dev, (sub / "change.patch").read_bytes())
    assert checks.tree_safety_refusal(blue, dev, tree, blue) is None


def test_a_short_name_in_the_patch_is_refused_before_any_card(blue: Path, pins: Path) -> None:
    """C: names folders twice: thomas/server/TOOL_M~1 is thomas/server/tool_manifests, a folder agent_safety.toml
    guards. Spelled the short way, a change got no guarded card, and was refused only after your approval."""
    sub = _submit(blue, "exec-short-name", {"thomas/server/zz_new.json": '{"grant": "everything"}\n'})
    _restamp(sub, b"thomas/server/zz_new.json", b"thomas/server/TOOL_M~1/new.json")
    ask = Asker(True, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "plain printable ASCII" in outcome.detail, outcome.detail
    assert ask.asked == []


def test_a_self_fix_cannot_change_how_git_shows_its_changes(blue: Path, pins: Path) -> None:
    """Landed, "*.py -diff" showed every later Python change as binary: no added line for the guarded-file check, and
    "(binary)" on the card."""
    sub = _submit(blue, "exec-attr-tree", {".gitattributes": "*.py -diff\n", "thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker(True, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and ".gitattributes" in outcome.detail, outcome.detail
    assert ask.asked == []


def test_a_gitattributes_in_the_running_copy_cannot_hide_a_change_from_its_cards(blue: Path, pins: Path) -> None:
    """The caged account can write tests/.gitattributes in the running copy (scripts/cage/grant_repo_access.ps1).
    With "* -diff" there, git showed a network-reach test helper as binary: no guarded card, "(new, binary)" on the
    single card, and "Binary files differ" where the chat showed its diff."""
    sub = _submit(blue, "exec-attr-hide", {"tests/net_helper.py": "import socket\n"})
    (blue / "tests").mkdir(exist_ok=True)
    (blue / "tests" / ".gitattributes").write_text("* -diff\n", encoding="utf-8")
    ask = Asker(True, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert len(ask.asked) == 2, "the guarded card, then the change"
    assert ask.asked[0][0].startswith("Change a file that guards Thomas") and "new network reach" in ask.asked[0][0]
    assert "tests/net_helper.py (new, +1)" in ask.asked[1][0]
    cards = _outbox(sub.name, "pending")["cards"]
    assert all("+import socket" in card["excerpt"] for card in cards), [card["excerpt"] for card in cards]


def test_python_nested_past_what_the_parser_reads_is_refused_before_any_card(blue: Path, pins: Path) -> None:
    """compile() raises RecursionError, not SyntaxError, for `x = 1+1+...` with thousands of terms: it escaped the
    check, and every pass failed on the same hand-in."""
    sub = _submit(blue, "exec-deep", {"thomas/deep.py": "x = " + "+".join(["1"] * 20_000) + "\n"})
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "thomas/deep.py does not compile" in outcome.detail, outcome.detail
    assert ask.asked == []
