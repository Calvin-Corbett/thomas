"""What a rebased landing judges again, and what it may leave standing (scripts/crew/brief/gate_reuse.py).

The first version kept the pass of 17 "selection only" gates unless the neighbour touched a selected path. Review found
that a landing could get through on such a pass that a fresh run would have refused (a neighbour that changed the policy or
a gate, a selected file edited between two attempts, a break-glass window that ended). Now only ``exception_handler`` is
kept, only against a fingerprint of everything it reads, and every other gate runs again. These tests hold each input of
the fingerprint, the list of what it watches, and the "everything else runs again" rule.
"""

from __future__ import annotations

import ast
import itertools
import os
import subprocess
from pathlib import Path

import pytest
from scripts.crew.brief import commit as commit_tool
from scripts.crew.brief import gate_reuse, gate_runner
from scripts.crew.brief.gate_reuse import FINGERPRINTED, Fingerprints, Passed, rerun_set

from tests.commit_lane_support import NEIGHBOUR, PY, git, init_repo, write

NOW = 1000.0
ROOT = Path(__file__).resolve().parents[1]
GATE = "exception_handler"


def _again(names, passed, *, fingerprint="fp", now=NOW):
    return rerun_set(names, passed, now=now, fingerprint_of=lambda name: fingerprint)


def test_a_gate_with_no_trusted_pass_runs_again() -> None:
    assert _again([GATE], {}) == {GATE}


def test_the_fingerprinted_gate_keeps_its_pass_only_against_an_identical_fingerprint() -> None:
    passed = {GATE: Passed(NOW - 5, "fp-1")}
    assert _again([GATE], passed, fingerprint="fp-1") == set()
    assert _again([GATE], passed, fingerprint="fp-2") == {GATE}
    assert _again([GATE], passed, fingerprint=None) == {GATE}  # git could not say: judge again
    assert _again([GATE], {GATE: Passed(NOW - 5)}, fingerprint="fp-1") == {GATE}  # a pass that carries no fingerprint
    assert _again([GATE], {GATE: Passed(NOW - 5)}, fingerprint=None) == {GATE}  # nothing to compare is not "equal"


def test_every_other_gate_runs_again_even_with_a_pass_and_a_matching_fingerprint() -> None:
    # Includes the gates that consult the break-glass state (commit_growth, protected_files, protected_deletion,
    # monolith_filename_guard) and the ones that read the whole tree (duplicate_filename): a pass from before a window ended
    # or a neighbour landed is not a pass.
    registry = [name for name, _command in commit_tool.LOCAL_GATE_COMMANDS]
    others = [n for n in registry if n not in gate_reuse.REUSABLE_LIVE and n not in FINGERPRINTED]
    assert len(others) > 30
    for name in ("commit_growth", "protected_files", "protected_deletion", "monolith_filename_guard", "ruff"):
        assert name in others
    passed = {name: Passed(NOW - 1, "fp") for name in others}
    assert _again(others, passed) == set(others)


def test_the_process_scan_is_reused_inside_one_landing_and_not_beyond_the_window() -> None:
    passed = {"active_folder_guard": Passed(NOW - 10)}
    assert _again(["active_folder_guard"], passed) == set()
    stale = {"active_folder_guard": Passed(NOW - gate_reuse.LIVE_REUSE_SECONDS - 1)}
    assert _again(["active_folder_guard"], stale) == {"active_folder_guard"}


def test_a_gate_nobody_classified_runs_again_so_a_new_gate_cannot_be_skipped_by_omission() -> None:
    assert _again(["gate_added_tomorrow"], {"gate_added_tomorrow": Passed(NOW - 1, "fp")}) == {"gate_added_tomorrow"}


def test_the_classification_names_real_gates_and_does_not_contradict_itself() -> None:
    registry = {name for name, _command in commit_tool.LOCAL_GATE_COMMANDS}
    assert registry >= gate_reuse.REUSABLE_LIVE and registry >= set(FINGERPRINTED)
    assert not (gate_reuse.REUSABLE_LIVE & set(FINGERPRINTED))
    assert {"active_folder_guard"} == gate_reuse.REUSABLE_LIVE and set(FINGERPRINTED) == {GATE}
    assert registry >= gate_runner.BOARD_READERS and registry >= gate_runner.LAST


# -- the fingerprint itself, against a real repository

_counter = itertools.count()


def _repo(tmp_path: Path) -> Path:
    repo, _board = init_repo(
        tmp_path, claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",)
    )
    write(repo / "src" / "other.py", "x = 1\n")
    write(repo / "src" / "a1.py", "y = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "more files")
    write(repo / "src" / "app.py", 'print("changed")\n')
    return repo


def _prints(repo: Path, tmp_path: Path, selected=("src/app.py",), base: str | None = None) -> Fingerprints:
    """The attempt's fingerprints: an index built on `base` (default HEAD) plus the selected paths, as the commit tool does."""
    base = base or git(repo, "rev-parse", "HEAD")
    folder = tmp_path / f"index{next(_counter)}"
    folder.mkdir()
    env = {**os.environ, "GIT_INDEX_FILE": str(folder / "index")}
    subprocess.run(["git", "read-tree", base], cwd=repo, env=env, check=True)
    subprocess.run(["git", "add", "-A", "--", *selected], cwd=repo, env=env, check=True)
    return Fingerprints(repo, index_env=env, base=base, selected=selected)


def test_the_same_inputs_give_the_same_fingerprint(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = _prints(repo, tmp_path).of(GATE)
    assert first and first == _prints(repo, tmp_path).of(GATE)
    assert _prints(repo, tmp_path, selected=("src/app.py", "src/app.py")).of(GATE) == first  # a repeat changes nothing


def test_a_neighbour_landing_somewhere_else_does_not_change_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = _prints(repo, tmp_path).of(GATE)
    write(repo / "elsewhere" / "n.txt", "x\n")
    git(repo, "add", "elsewhere/n.txt")
    git(repo, "commit", "-qm", "neighbour")
    assert _prints(repo, tmp_path).of(GATE) == before  # the base moved, nothing the gate reads did


def test_a_selected_file_edited_between_two_attempts_changes_it(tmp_path: Path) -> None:
    # Review finding E1: the index is rebuilt from the working tree each attempt, so the old pass judged older bytes.
    repo = _repo(tmp_path)
    before = _prints(repo, tmp_path).of(GATE)
    write(repo / "src" / "app.py", "try:\n    pass\nexcept:\n    pass\n")
    assert _prints(repo, tmp_path).of(GATE) != before


def test_a_neighbour_that_changed_a_selected_path_in_the_base_changes_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = _prints(repo, tmp_path).of(GATE)
    script = tmp_path / "neighbour.py"
    script.write_text(NEIGHBOUR, encoding="utf-8")
    subprocess.run([PY, str(script), str(repo), "src/app.py", "print('theirs')"], check=True, capture_output=True)
    write(repo / "src" / "app.py", 'print("changed")\n')  # the working tree holds our own text again
    assert (
        _prints(repo, tmp_path).of(GATE) != before
    )  # the same index entry as before, on a base that differs for this path


def test_a_selected_path_that_is_gone_or_new_changes_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    one = _prints(repo, tmp_path, selected=("src/app.py", "src/other.py")).of(GATE)
    (repo / "src" / "other.py").unlink()  # selected, and now deleted
    assert _prints(repo, tmp_path, selected=("src/app.py", "src/other.py")).of(GATE) != one


@pytest.mark.parametrize("relative", FINGERPRINTED[GATE])
def test_a_change_to_anything_the_gate_reads_besides_the_selection_changes_it(tmp_path: Path, relative: str) -> None:
    # Review finding: a neighbour that changed agent_safety.toml (or a gate) is not a selected path.
    repo = _repo(tmp_path)
    absent = _prints(repo, tmp_path).of(GATE)
    write(repo / relative, "one = 1\n")
    one = _prints(repo, tmp_path).of(GATE)
    write(repo / relative, "one = 2\n")
    two = _prints(repo, tmp_path).of(GATE)
    (repo / relative).unlink()
    assert len({absent, one, two}) == 3
    assert _prints(repo, tmp_path).of(GATE) == absent


def test_a_watched_file_that_changes_while_the_gate_runs_means_the_pass_is_not_kept(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    prints = _prints(repo, tmp_path)
    assert prints.stamp(GATE) == prints.of(GATE) is not None
    write(repo / "agent_safety.toml", "[exceptions]\nrequire_specific_exceptions = false\n")
    assert prints.stamp(GATE) is None  # it judged the policy that was there when it started
    assert prints.stamp("not_a_fingerprinted_gate") is None


def test_a_path_with_glob_characters_is_read_literally(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo / "src" / "a[1].py", "z = 1\n")
    before = _prints(repo, tmp_path, selected=("src/a[1].py",)).of(GATE)
    write(repo / "src" / "a1.py", "y = 2\n")  # the pattern a[1].py would also match this file; it must not
    assert _prints(repo, tmp_path, selected=("src/a[1].py",)).of(GATE) == before
    write(repo / "src" / "a[1].py", "z = 2\n")
    assert _prints(repo, tmp_path, selected=("src/a[1].py",)).of(GATE) != before


def test_the_fingerprint_is_none_when_git_cannot_say_or_nothing_is_selected_or_the_gate_is_not_fingerprinted(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    assert _prints(repo, tmp_path).of("ruff") is None
    assert _prints(repo, tmp_path, selected=()).of(GATE) is None
    folder = tmp_path / "broken"
    folder.mkdir()
    env = {**os.environ, "GIT_INDEX_FILE": str(folder / "index")}
    assert Fingerprints(repo, index_env=env, base="0" * 40, selected=["src/app.py"]).of(GATE) is None


def test_a_file_that_cannot_be_read_never_digests_the_same_twice(tmp_path: Path) -> None:
    folder = tmp_path / "locked.toml"
    folder.mkdir()  # a directory where a file is expected: read_bytes fails with an OSError that is not "absent"
    first = gate_reuse.watch_digest(tmp_path, ["locked.toml"])
    assert first != gate_reuse.watch_digest(tmp_path, ["locked.toml"])
    assert gate_reuse.watch_digest(tmp_path, ["missing.toml"]) == gate_reuse.watch_digest(tmp_path, ["missing.toml"])


# -- the watch list, held to the gate's own source


def _repo_modules_imported_by(rel: str, seen: set[str]) -> None:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in {"scripts", "thomas"}:
            modules = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names if alias.name.split(".")[0] in {"scripts", "thomas"}]
        for module in modules:
            target = module.replace(".", "/") + ".py"
            if (ROOT / target).is_file() and target not in seen:
                seen.add(target)
                _repo_modules_imported_by(target, seen)


def test_the_watch_list_is_the_gate_plus_every_repo_module_it_imports_and_its_policy_files() -> None:
    gate = "scripts/forge/gates/exception_handler_gate.py"
    imported: set[str] = set()
    _repo_modules_imported_by(gate, imported)
    watched = set(FINGERPRINTED[GATE])
    assert gate in watched
    assert imported <= watched, f"the gate imports {sorted(imported - watched)}, which the fingerprint does not watch"
    assert watched - imported - {gate} == {"agent_safety.toml", "agent_safety.local.toml"}
    from scripts.crew.brief import safety_config

    assert safety_config.CONFIG_PATH.name == "agent_safety.toml"  # the file load_config reads, and its ".local" overlay
    assert "THOMAS_AGENT_SAFETY_CONFIG" in (ROOT / "scripts/crew/brief/safety_config.py").read_text(encoding="utf-8")


def test_the_package_init_files_the_imports_run_hold_no_code() -> None:
    # An import of scripts.crew.brief.safety_config also runs these; if one gains code, the watch list is missing it.
    for rel in ("scripts/__init__.py", "scripts/crew/__init__.py", "scripts/crew/brief/__init__.py"):
        body = ast.parse((ROOT / rel).read_text(encoding="utf-8")).body
        assert all(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) for n in body), rel


def test_the_kept_gate_never_asks_about_a_break_glass_window() -> None:
    # The reason commit_growth, protected_files and the others are not kept: they consult the break-glass state, which can
    # end between two attempts. If this gate ever does, a pass from before the window ended must not be reused.
    # (safety_config.py only reads the break-glass QUOTA out of the policy file; asking whether a window is open is what
    # the runtime guard does, and neither file touches it.)
    for rel in ("scripts/forge/gates/exception_handler_gate.py", "scripts/crew/brief/safety_config.py"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "runtime_protection" not in text and "_runtime_guard" not in text, rel
    gate_text = (ROOT / "scripts/forge/gates/exception_handler_gate.py").read_text(encoding="utf-8").lower()
    assert "breakglass" not in gate_text and "break_glass" not in gate_text
