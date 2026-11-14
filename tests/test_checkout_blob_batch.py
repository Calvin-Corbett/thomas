"""Checkout comparisons batch only files on disk and retain filtered binary bytes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks


@pytest.fixture(params=["false", "true"], ids=["explicit-crlf", "autocrlf"])
def repo(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    def git(*args: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                f"core.hooksPath={tmp_path / 'no-hooks'}",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.fsmonitor=false",
                *args,
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=20,
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.autocrlf", request.param)
    if request.param == "false":
        (tmp_path / ".gitattributes").write_bytes(b"*.txt text eol=crlf\n")
    (tmp_path / "with space.txt").write_bytes(b"first\nsecond\n")
    (tmp_path / "binary.dat").write_bytes(b"\x00\xff\r\n\nblob 500\n")
    (tmp_path / "missing.txt").write_bytes(b"missing\n")
    git("add", ".")
    git("commit", "-m", "fixture")
    (tmp_path / "with space.txt").write_bytes(b"first\r\nsecond\r\n")
    (tmp_path / "missing.txt").unlink()
    return tmp_path


def test_one_batch_skips_absent_files_and_preserves_exact_bytes(repo: Path, monkeypatch) -> None:
    real = checks.subprocess.run
    batches = []

    def record(args, *rest, **kwargs):
        if "cat-file" in args:
            batches.append((args, kwargs.get("input")))
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(checks.subprocess, "run", record)
    changes = [("M", p) for p in ("with space.txt", "binary.dat", "missing.txt")]
    assert checks.already_in_running_copy(repo, "HEAD", "HEAD", changes) == frozenset({"with space.txt", "binary.dat"})
    assert len(batches) == 1
    args, request = batches[0]
    assert any(arg.startswith("--batch=") for arg in args) and "--filters" in args
    assert len(request.splitlines()) == 2
    assert b"missing.txt" not in request
    assert b" with space.txt\n" in request

    (repo / "with space.txt").write_bytes(b"first\nsecond\n")
    assert checks.already_in_running_copy(repo, "HEAD", "HEAD", changes) == frozenset({"binary.dat"})
    (repo / "binary.dat").write_bytes(b"\x00\xfe\r\n\nblob 500\n")
    assert checks.already_in_running_copy(repo, "HEAD", "HEAD", changes) == frozenset()


def test_filtered_size_is_not_used_to_frame_following_blob(repo: Path) -> None:
    """Git's header measures LF storage, not the longer CRLF checkout output."""
    blob = checks.run_git(repo, "rev-parse", "HEAD:with space.txt").stdout.strip()
    binary = checks.run_git(repo, "rev-parse", "HEAD:binary.dat").stdout.strip()
    raw = subprocess.run(
        ["git", "cat-file", "--batch", "--filters"],
        cwd=repo,
        input=f"{blob} with space.txt\n{binary} binary.dat\n".encode(),
        capture_output=True,
        check=True,
        timeout=20,
    ).stdout
    header, _, rest = raw.partition(b"\n")
    expected = (repo / "with space.txt").read_bytes()
    assert int(header.split()[-1]) == len(b"first\nsecond\n")
    assert len(expected) > int(header.split()[-1])
    assert rest.startswith(expected + b"\n" + binary.encode())
    assert checks.already_in_running_copy(
        repo, "HEAD", "HEAD", [("M", "with space.txt"), ("M", "binary.dat")]
    ) == frozenset({"with space.txt", "binary.dat"})


def test_length_changing_smudge_preserves_exact_bytes(repo: Path) -> None:
    script = repo / "smudge.py"
    script.write_text(
        "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read() + b'\\x00smudged\\r\\n')\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "config",
            "filter.expand.smudge",
            f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"',
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=20,
    )
    (repo / ".gitattributes").write_bytes(b"*.txt filter=expand -text\n")
    expected = b"first\nsecond\n\x00smudged\r\n"
    (repo / "with space.txt").write_bytes(expected)
    changes = [("M", "with space.txt"), ("M", "binary.dat")]
    assert checks.already_in_running_copy(repo, "HEAD", "HEAD", changes) == frozenset({"with space.txt", "binary.dat"})
    (repo / "with space.txt").write_bytes(expected.replace(b"\r\n", b"\n"))
    assert checks.already_in_running_copy(repo, "HEAD", "HEAD", changes) == frozenset({"binary.dat"})


@pytest.mark.parametrize("failure", ["collision", "wrong-header", "truncated", "git-error"])
def test_ambiguous_or_failed_batch_returns_no_matches(monkeypatch, failure: str) -> None:
    marker = b"a" * 32
    blob = "b" * 40
    monkeypatch.setattr(checks.os, "urandom", lambda n: marker)
    header = marker.hex().encode() + b" " + blob.encode() + b" blob\n"
    responses = {
        "collision": header + b"payload\n" + header,
        "wrong-header": header.replace(b" blob", b" tree") + b"payload\n",
        "truncated": header + b"payload",
        "git-error": header + b"payload\n",
    }
    monkeypatch.setattr(
        checks.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], int(failure == "git-error"), stdout=responses[failure], stderr=b""
        ),
    )
    assert checks._checkout_bytes(Path("unused"), {"file": blob}) == {}


def test_absent_files_need_no_blob_process(repo: Path, monkeypatch) -> None:
    real = checks.subprocess.run

    def no_cat_file(args, *rest, **kwargs):
        assert "cat-file" not in args
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(checks.subprocess, "run", no_cat_file)
    assert checks.already_in_running_copy(repo, "HEAD", "HEAD", [("M", "missing.txt")]) == frozenset()
