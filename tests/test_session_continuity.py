"""CAP-064 L2: local<->cloud continuity via session envelope + git-bundle handoff.

Proves, against real hermetic temp git repositories (no network) with an
injected clock:

- An envelope + git bundle produced on host A resumes on a SEPARATE host B
  (distinct temp dirs), reconstructing the SAME commits and tree AND the exact
  pending task steps -- i.e. an identical working tree + a resumable task.
- A tampered bundle (one flipped byte) is rejected by the digest check and the
  destination is never populated (no silent partial resume).
- Secret VALUES never appear in the envelope -- only variable names.
- The envelope round-trips through JSON unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.tools.session_continuity import (
    BundleIntegrityError,
    ContinuityHandoff,
    EnvelopeFormatError,
    SessionEnvelope,
    digest_file,
    load_envelope,
    repo_state,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "Tester")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    (root / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "second")
    return root


class _FrozenClock:
    def __init__(self, value: float = 1_700_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def host_a_repo(tmp_path: Path) -> Path:
    return _init_repo(tmp_path / "hostA" / "repo")


def _capture(host_a_repo: Path, out_dir: Path):
    handoff = ContinuityHandoff(clock=_FrozenClock())
    return handoff, handoff.capture(
        repo_root=host_a_repo,
        out_dir=out_dir,
        task_id="CAP-064-run",
        objective="Move the task from local to cloud",
        pending_steps=["run tests", "fix regression", "push branch"],
        source_host="local-laptop",
        cwd="src",
        refs=["app.py"],
        env={"OPENAI_API_KEY": "sk-SUPER-SECRET", "HOME": "/home/user"},
        context_ref="conversation://thread/42",
    )


def test_envelope_bundle_resumes_on_separate_host(host_a_repo: Path, tmp_path: Path) -> None:
    # Host A: capture envelope + bundle.
    handoff, captured = _capture(host_a_repo, tmp_path / "transfer")
    assert captured.bundle_path.is_file()
    assert captured.envelope_path.is_file()

    source = repo_state(host_a_repo)

    # Host B: a completely separate temp dir, resume from the transferred artifacts.
    dest = tmp_path / "hostB" / "repo"
    resumed = handoff.resume(
        envelope=captured.envelope,
        bundle_path=captured.bundle_path,
        dest_root=dest,
    )

    # Same commits + same tree => identical working tree.
    dest_state = repo_state(dest)
    assert dest_state.head_commit == source.head_commit
    assert dest_state.tree_hash == source.tree_hash
    assert set(dest_state.commit_list) == set(source.commit_list)
    assert (dest / "src" / "app.py").read_text(encoding="utf-8") == "print('v2')\n"

    # Resumable task: pending steps + context reconstructed exactly.
    assert resumed.pending_steps == ("run tests", "fix regression", "push branch")
    assert resumed.task_id == "CAP-064-run"
    assert resumed.objective == "Move the task from local to cloud"
    assert resumed.context_ref == "conversation://thread/42"
    assert resumed.cwd == "src"
    assert resumed.refs == ("app.py",)
    assert resumed.head_commit == source.head_commit


def test_tampered_bundle_is_rejected(host_a_repo: Path, tmp_path: Path) -> None:
    handoff, captured = _capture(host_a_repo, tmp_path / "transfer")

    # Flip one byte in the middle of the bundle.
    data = bytearray(captured.bundle_path.read_bytes())
    mid = len(data) // 2
    data[mid] ^= 0xFF
    captured.bundle_path.write_bytes(bytes(data))
    assert digest_file(captured.bundle_path) != captured.envelope.bundle_digest

    dest = tmp_path / "hostB" / "repo"
    with pytest.raises(BundleIntegrityError):
        handoff.resume(
            envelope=captured.envelope,
            bundle_path=captured.bundle_path,
            dest_root=dest,
        )
    # No silent partial resume: destination was never created.
    assert not dest.exists()


def test_secret_values_never_enter_envelope(host_a_repo: Path, tmp_path: Path) -> None:
    _handoff, captured = _capture(host_a_repo, tmp_path / "transfer")

    # Names are recorded (sorted), values are not.
    assert captured.envelope.env_var_names == ("HOME", "OPENAI_API_KEY")

    serialized = captured.envelope_path.read_text(encoding="utf-8")
    assert "sk-SUPER-SECRET" not in serialized
    assert "/home/user" not in serialized
    assert "OPENAI_API_KEY" in serialized  # the name is fine

    reloaded = load_envelope(captured.envelope_path)
    assert "sk-SUPER-SECRET" not in reloaded.to_json()


def test_envelope_json_round_trips(host_a_repo: Path, tmp_path: Path) -> None:
    _handoff, captured = _capture(host_a_repo, tmp_path / "transfer")
    again = SessionEnvelope.from_json(captured.envelope.to_json())
    assert again == captured.envelope
    assert again.created_at == 1_700_000_000.0


def test_bad_schema_version_rejected() -> None:
    with pytest.raises(EnvelopeFormatError):
        SessionEnvelope.from_json('{"schema_version": 999}')
