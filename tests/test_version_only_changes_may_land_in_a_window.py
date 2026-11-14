"""Only exact version-line replacements escape the two metadata files' window exclusions."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from scripts.cage import card_catalogue, self_change_checks, window_rules

from tests.green_support import git

SOURCES = {
    "pyproject.toml": '[build-system]\nrequires = ["setuptools>=69"]\n[project]\nversion = "1.2.3"\nname = "sample"\n',
    "thomas/__init__.py": '"""Package metadata."""\n__version__ = "1.2.3"\n\ndef untouched():\n    return 1\n',
}


def patch(path: str, before: str, after: str) -> str:
    body = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=2**31 - 1,
        )
    )
    return f"diff --git a/{path} b/{path}\nindex 1234567..abcdef0 100644\n{body}"


def why(path: str, diff: str, status: str = "M", enforced: tuple[str, ...] = ()) -> str:
    return window_rules.why_never(
        path,
        status,
        added_diff=diff,
        enforced=enforced,
        closure=frozenset({path}),
        catalogue=card_catalogue,
    )


@pytest.mark.parametrize("path", SOURCES)
def test_one_version_replacement_may_land_even_when_the_file_is_loaded(path: str) -> None:
    before = SOURCES[path]
    assert why(path, patch(path, before, before.replace("1.2.3", "1.2.4"))) == ""


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("status", ["A", "D", "R100", "C100", "T"])
def test_only_a_modified_existing_file_gets_the_exception(path: str, status: str) -> None:
    before = SOURCES[path]
    assert why(path, patch(path, before, before.replace("1.2.3", "1.2.4")), status)


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize(
    "extra",
    ["\n", "# another change\n", "import os\n", 'version = "9.9.9"\n', '__version__ = "9.9.9"\n'],
)
def test_a_second_changed_line_still_needs_a_card(path: str, extra: str) -> None:
    before = SOURCES[path]
    after = before.replace("1.2.3", "1.2.4") + extra
    assert why(path, patch(path, before, after))


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("version", ["1.2", "1.2.3rc1", "v1.2.4", "١.٢.٤", '1.2.4" # note'])
def test_the_new_line_must_be_the_exact_three_part_version_form(path: str, version: str) -> None:
    before = SOURCES[path]
    assert why(path, patch(path, before, before.replace("1.2.3", version)))


@pytest.mark.parametrize("path", SOURCES)
def test_non_version_changes_and_removing_the_version_need_a_card(path: str) -> None:
    before = SOURCES[path]
    assignment = 'version = "1.2.3"' if path == "pyproject.toml" else '__version__ = "1.2.3"'
    for after in [before.replace(assignment + "\n", ""), before.replace(assignment, assignment + " # note")]:
        assert why(path, patch(path, before, after))
    bad_before = before.replace("1.2.3", "1.2.3rc1")
    assert why(path, patch(path, bad_before, before))


@pytest.mark.parametrize(
    "before",
    [
        '[tool.other]\nversion = "1.2.3"\n',
        '[project.other]\nversion = "1.2.3"\n',
        '[project]\nversion = "7.8.9"\n[tool.other]\nversion = "1.2.3"\n',
        "[project]\nversion = \"7.8.9\"\ndescription = '''\nversion = \"1.2.3\"\n'''\n",
        '[project]\nversion = "1.2.3"\ninvalid = [\n',
        '[project]\nversion = "1.2.3"\nversion = "7.8.9"\n',
    ],
)
def test_toml_version_must_really_belong_to_project(before: str) -> None:
    assert why("pyproject.toml", patch("pyproject.toml", before, before.replace("1.2.3", "1.2.4")))


@pytest.mark.parametrize(
    "before",
    ["note = '''\n__version__ = \"1.2.3\"\n'''\n", 'if True:\n__version__ = "1.2.3"\n'],
)
def test_python_version_must_be_a_real_module_assignment(before: str) -> None:
    path = "thomas/__init__.py"
    assert why(path, patch(path, before, before.replace("1.2.3", "1.2.4")))


@pytest.mark.parametrize("path", SOURCES)
def test_a_next_patch_lands_even_when_its_own_file_is_an_enforcement_path(path: str) -> None:
    """Every change to Thomas's code bumps pyproject.toml's version, and pyproject.toml is on the enforcement list,
    so until 2026-10-27 no such change could land in a window. You decided that day that the version line may."""
    before = SOURCES[path]
    diff = patch(path, before, before.replace("1.2.3", "1.2.4"))
    assert why(path, diff, enforced=(path, "scripts/forge/gates/other_gate.py")) == ""


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("version", ["1.2.5", "1.2.30", "1.3.0", "2.0.0", "1.2.2", "0.2.3"])
def test_only_the_next_patch_escapes_and_a_jump_or_a_step_back_needs_a_card(path: str, version: str) -> None:
    before = SOURCES[path]
    assert why(path, patch(path, before, before.replace("1.2.3", version)))
    assert why(path, patch(path, before, before.replace("1.2.3", version)), enforced=(path,))


@pytest.mark.parametrize("path", ["nested/pyproject.toml", "PYPROJECT.TOML", "thomas/other/__init__.py"])
def test_other_paths_do_not_get_the_exception(path: str) -> None:
    before = SOURCES["thomas/__init__.py" if path.endswith("__init__.py") else "pyproject.toml"]
    assert why(path, patch(path, before, before.replace("1.2.3", "1.2.4")))


@pytest.mark.parametrize("path", SOURCES)
def test_malformed_partial_or_metadata_changing_diffs_need_a_card(path: str) -> None:
    before = SOURCES[path]
    diff = patch(path, before, before.replace("1.2.3", "1.2.4"))
    variants = [
        "",
        diff.replace("100644", "120000"),
        diff.replace("index ", "old mode 100644\nnew mode 100755\nindex "),
        diff.replace("@@ -1,", "@@ -2,"),
        diff.replace(f"+++ b/{path}", "+++ b/other"),
        diff + diff,
        diff.replace(
            "-" + ("version" if path == "pyproject.toml" else "__version__") + ' = "1.2.3"\n',
            "-"
            + ("version" if path == "pyproject.toml" else "__version__")
            + ' = "1.2.3"\n\\ No newline at end of file\n',
        ),
        diff.replace(
            "-" + ("version" if path == "pyproject.toml" else "__version__"),
            "+extra\n-" + ("version" if path == "pyproject.toml" else "__version__"),
        ),
    ]
    for malformed in variants:
        assert why(path, malformed), malformed


def commit_files(repo: Path, files: dict[str, str]) -> str:
    for path, text in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


def test_rules_read_full_exact_git_diff_and_do_not_exempt_other_files(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    before = dict(SOURCES)
    # Put the table header outside Git's normal three context lines.
    before["pyproject.toml"] = before["pyproject.toml"].replace("[project]\n", "[project]\n" + "# context\n" * 12)
    before["thomas/__init__.py"] += '\nraise RuntimeError("never execute submitted code")\n'
    before[".gitattributes"] = "pyproject.toml -diff\nthomas/__init__.py -diff\n"
    parent = commit_files(tmp_path, before)
    after = {path: text.replace("1.2.3", "1.2.4") for path, text in before.items()}
    tree = commit_files(tmp_path, after)
    rules = window_rules.Rules(tmp_path, entries=(), modules={})
    options = dict(catalogue=card_catalogue, enforced=())
    changes = [("M", path) for path in SOURCES]
    assert rules.excluded(parent, tree, changes, **options) == []
    for path in SOURCES:  # its own place on the enforcement list no longer blocks a next patch (2026-10-27)
        assert rules.excluded(parent, tree, changes, catalogue=card_catalogue, enforced=iter([path])) == []
    after["thomas/__init__.py"] += "# extra edit\n"
    after["pyproject.toml"] += '\n[tool.pytest.ini_options]\naddopts = "-p unexpected"\n'
    after["setup.cfg"] = "[metadata]\nname = sample\n"
    second_tree = commit_files(tmp_path, after)
    excluded = rules.excluded(parent, second_tree, changes + [("A", "setup.cfg")], **options)
    assert {path for path, _ in excluded} == set(SOURCES) | {"setup.cfg"}
    git(tmp_path, "rm", "--", *SOURCES)
    git(tmp_path, "commit", "-qm", "delete metadata")
    deletion_tree = git(tmp_path, "rev-parse", "HEAD")
    assert len(rules.excluded(second_tree, deletion_tree, [("D", path) for path in SOURCES], **options)) == 2


@pytest.mark.parametrize("old_newline,new_newline", [(False, False), (False, True), (True, False)])
def test_real_git_newline_changes_need_a_card(tmp_path: Path, old_newline: bool, new_newline: bool) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Window test")
    git(tmp_path, "config", "user.email", "window@example.invalid")
    git(tmp_path, "config", "core.autocrlf", "false")
    before = {"pyproject.toml": '[project]\nversion = "1.2.3"', "thomas/__init__.py": '__version__ = "1.2.3"'}
    after = {path: text.replace("1.2.3", "1.2.4") + ("\n" if new_newline else "") for path, text in before.items()}
    parent = commit_files(tmp_path, {path: text + ("\n" if old_newline else "") for path, text in before.items()})
    tree = commit_files(tmp_path, after)
    excluded = window_rules.Rules(tmp_path, entries=(), modules={}).excluded(
        parent, tree, [("M", path) for path in before], catalogue=card_catalogue, enforced=()
    )
    assert {path for path, _ in excluded} == (set(before) if old_newline != new_newline else set())
