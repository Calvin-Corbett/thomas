"""The live diff does bounded work per poll, keeps the end of a long diff, and never reads outside the project.

Review findings on thomas/server/routes/evolve_agent_live_diff_routes.py, 2026-10-29:

* The whole ``git diff`` came into the server on every 3 s poll; the 64 KB cap applied only afterwards (a 49.5 MB
  data file: 13.4 s and 541 MB per call). A file over the size limit, on disk or at HEAD, is now never diffed.
* The cap kept the START of a long diff, and the screen shows its last hunk: lines past the cut never showed.
* ``diff.noprefix`` / ``diff.mnemonicPrefix`` in your git config blanked every tracked file's lines.
* Any failure of ``git diff HEAD`` fell back to the empty tree and reported a whole-file rewrite; a failed
  ``git status`` answered ok with no files, which reset the screen's baseline.
* git lists the files under an untracked junction as the project's own, and their content was sent back.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_git
from thomas.server.routes import evolve_agent_live_diff_routes as live


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for key, value in (("user.email", "t@example.com"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    _git(repo, "config", "core.autocrlf", "false")
    return repo


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _files(result: dict) -> dict[str, dict]:
    return {row["file"]: row for row in result["files"]}


def _spy(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real = forge_code_git._run_git

    def spy(root, args, timeout=forge_code_git._DEFAULT_TIMEOUT):
        calls.append(list(args))
        return real(root, args, timeout)

    monkeypatch.setattr(forge_code_git, "_run_git", spy)
    return calls


def test_a_tracked_file_too_large_to_diff_is_listed_without_being_diffed(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_FILE_BYTES", 4096)
    repo = _repo(tmp_path)
    rows = "".join(f"{n},a\n" for n in range(2000))  # ~13 KB
    _write(repo / "data.csv", rows)
    _write(repo / "gone.csv", rows)
    _write(repo / "app.js", "one\n")
    _commit(repo)
    _write(repo / "data.csv", rows.replace(",a", ",b"))  # every line rewritten
    (repo / "gone.csv").unlink()  # deleted: its HEAD copy is what a diff would read
    _write(repo / "app.js", "two\n")
    calls = _spy(monkeypatch)
    files = _files(live.live_diff(repo))
    for name in ("data.csv", "gone.csv"):
        assert files[name]["too_large"] is True and files[name]["diff"] == ""
    assert (files["app.js"]["added"], files["app.js"]["removed"]) == (1, 1)
    [diff_call] = [args for args in calls if "diff" in args]
    assert not any("csv" in arg for arg in diff_call)  # never asked of git, so never read into the server


def test_a_long_new_file_keeps_its_end_with_true_line_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_DIFF_CHARS", 4096)
    repo = _repo(tmp_path)
    _write(repo / "seed.txt", "x\n")
    _commit(repo)
    lines = [f"<p>line {n}</p>" for n in range(1, 3001)] + ["<footer>NEW LINE THE AGENT JUST WROTE</footer>"]
    _write(repo / "index.html", "".join(line + "\n" for line in lines))
    entry = _files(live.live_diff(repo))["index.html"]
    diff = entry["diff"]
    assert entry["truncated"] is True and entry["added"] == 3001 and len(diff) <= 4096
    assert diff.startswith("diff --git a/index.html b/index.html\n")
    assert diff.endswith("+<footer>NEW LINE THE AGENT JUST WROTE</footer>\n")
    header = re.search(r"^@@ -0,0 \+(\d+),(\d+) @@$", diff, re.M)
    first, count = int(header.group(1)), int(header.group(2))
    body = diff[header.end() + 1 :].splitlines()
    assert len(body) == count and first + count - 1 == 3001
    assert body[0] == "+" + lines[first - 1]  # the first line kept carries its own number


def test_a_long_tracked_diff_keeps_its_last_hunk(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_DIFF_CHARS", 4096)
    repo = _repo(tmp_path)
    original = [f"row {n}" for n in range(1, 2001)]
    _write(repo / "app.txt", "".join(line + "\n" for line in original))
    _commit(repo)
    changed = [f"ROW {n}" if n <= 400 else line for n, line in enumerate(original, start=1)]
    changed[1989] = "the line the agent is on"
    _write(repo / "app.txt", "".join(line + "\n" for line in changed))
    entry = _files(live.live_diff(repo))["app.txt"]
    assert (entry["added"], entry["removed"], entry["truncated"]) == (401, 401, True)  # counted over the whole diff
    assert "+the line the agent is on\n" in entry["diff"] and "+ROW 1\n" not in entry["diff"]
    assert re.search(r"^@@ -1987,7 \+1987,7 @@", entry["diff"], re.M)


@pytest.mark.parametrize("setting", ["diff.noprefix", "diff.mnemonicPrefix"])
def test_a_git_config_that_changes_diff_prefixes_keeps_the_lines(tmp_path, setting):
    repo = _repo(tmp_path)
    _write(repo / "app.js", "one\n")
    _commit(repo)
    _git(repo, "config", setting, "true")
    _write(repo / "app.js", "two\n")
    entry = _files(live.live_diff(repo))["app.js"]
    assert (entry["added"], entry["removed"]) == (1, 1) and "+two" in entry["diff"]


@pytest.mark.parametrize("failing", ["diff", "ls-tree"])
def test_git_that_gives_no_answer_about_head_is_an_error_not_a_whole_file_rewrite(tmp_path, monkeypatch, failing):
    repo = _repo(tmp_path)
    _write(repo / "app.js", "".join(f"line {n}\n" for n in range(500)))
    _commit(repo)
    _write(repo / "app.js", "".join(f"line {n}\n" for n in range(499)) + "changed\n")
    real = forge_code_git._run_git

    def busy(root, args, timeout=forge_code_git._DEFAULT_TIMEOUT):
        if failing in args and "HEAD" in args:  # only the read against HEAD; the empty tree would still answer
            return -9, "", "git was not run: 8 git processes were already in flight"
        return real(root, args, timeout)

    monkeypatch.setattr(forge_code_git, "_run_git", busy)
    with pytest.raises(forge_code_git.ForgeCodeGitError, match="in flight"):
        live.live_diff(repo)


def test_a_repository_with_no_commit_compares_with_the_empty_tree(tmp_path):
    repo = _repo(tmp_path)
    _write(repo / "app.js", "a\nb\n")
    _git(repo, "add", "app.js")
    entry = _files(live.live_diff(repo))["app.js"]
    assert (entry["added"], entry["removed"], entry["untracked"]) == (2, 0, False)


def test_a_git_status_that_gives_no_answer_is_an_error_not_an_empty_project(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _write(repo / "app.js", "a\n")
    _commit(repo)

    def busy(_root):
        raise forge_code_git.ForgeCodeGitError("git status could not confirm workspace state: git was not run")

    monkeypatch.setattr(forge_code_git, "_status_entries", busy)
    with pytest.raises(forge_code_git.ForgeCodeGitError):
        live.live_diff(repo)


def test_a_folder_that_is_no_repository_still_reads_as_no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    folder = tmp_path / "plain"
    folder.mkdir()
    result = live.live_diff(folder)
    assert result["history"] is False and result["files"] == [] and result["error"]


def _link_folder(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # no admin rights needed, as for a run
    else:
        os.symlink(target, link, target_is_directory=True)


def test_nothing_behind_a_junction_out_of_the_project_is_read(tmp_path):
    repo = _repo(tmp_path)
    _write(repo / "app.js", "a\n")
    _commit(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside / "secret.txt", "OUTSIDE-SECRET\n")
    _link_folder(repo / "link", outside)
    _write(repo / "mine.txt", "my work\n")
    try:
        os.symlink(outside / "secret.txt", repo / "leak.txt")  # a file link, where the system allows one
    except OSError:
        pass
    result = live.live_diff(repo)
    assert "OUTSIDE-SECRET" not in json.dumps(result)
    files = _files(result)
    assert not any(name.startswith("link/") for name in files)
    assert files["mine.txt"]["added"] == 1
    if "leak.txt" in files:
        assert files["leak.txt"]["diff"] == "" and files["leak.txt"]["link"] is True
