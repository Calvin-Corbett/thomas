"""The verifier must check the user's files, not Thomas's own bookkeeping.

Thomas writes its Code transcripts into the selected repository, under
``.thomas/evolve/agent/``. Those writes are durable evidence, but they are not
user-project work, and `forge_code_git.project_delta_since` exists precisely to
keep them out -- its docstring says they "must never inflate completion or
artifact counts".

The report used it. `_verify_and_iterate` used the unfiltered `delta_since`, so
the two disagreed about what this run had changed.

Measured on the Call-of-Duty run. Its recorded `changed_files` were the three
real files, while the check printed beside them read::

    exit 0 parsed .thomas/evolve/agent/conversations/fc_20260730T164534_d8fa2f.json
    checked game.js parsed index.html checked styles.css
    STATIC_VERIFY_OK: 4 files checked, 0 imported

Three files delivered, four reported checked, and the extra one was ANOTHER
conversation's state file. Thomas graded its own paperwork and counted it as
coverage.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.build_verify import _verify_and_iterate

BOOKKEEPING = ".thomas/evolve/agent/conversations/fc_20260730T164534_d8fa2f.json"


def _write(root: Path, rel: str, body: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _capture(root: Path, monkeypatch) -> list[list[str]]:
    """Record the file list the verifier is actually handed."""
    seen: list[list[str]] = []

    def fake_verify(cwd, changed, emit):  # noqa: ANN001 - test double
        seen.append(list(changed))
        return True, 0, "ok"

    from thomas.forge.anvil import forge_code_git

    monkeypatch.setattr(
        forge_code_git,
        "delta_since",
        lambda cwd, snap: ["index.html", BOOKKEEPING, "game.js"],
    )
    monkeypatch.setattr(
        forge_code_git,
        "project_delta_since",
        lambda cwd, snap: [
            path
            for path in ["index.html", BOOKKEEPING, "game.js"]
            if not str(path).replace("\\", "/").lower().startswith(".thomas/evolve/agent/")
        ],
    )
    _verify_and_iterate(root, {}, lambda event: None, lambda prompt: (0, ""), "goal", verifier=fake_verify)
    return seen


def test_thomas_own_transcript_is_not_verified_as_a_deliverable(tmp_path, monkeypatch) -> None:
    _write(tmp_path, "index.html", "<!doctype html><p>hi</p>")
    _write(tmp_path, "game.js", "const a = 1;")
    _write(tmp_path, BOOKKEEPING, "{}")

    seen = _capture(tmp_path, monkeypatch)

    assert seen, "the verifier was never called"
    handed = seen[0]
    assert BOOKKEEPING not in handed, (
        "Thomas's own conversation record was handed to the verifier and would be "
        "counted in 'N files checked'"
    )
    assert "index.html" in handed and "game.js" in handed, "the real files must still be checked"


def test_a_run_that_only_wrote_bookkeeping_verifies_nothing(tmp_path, monkeypatch) -> None:
    """Otherwise parsing one JSON file reads as a passing check on a run that
    changed nothing a user asked for."""

    _write(tmp_path, BOOKKEEPING, "{}")
    seen: list[list[str]] = []

    def fake_verify(cwd, changed, emit):  # noqa: ANN001 - test double
        seen.append(list(changed))
        return True, 0, "ok"

    from thomas.forge.anvil import forge_code_git

    monkeypatch.setattr(forge_code_git, "delta_since", lambda cwd, snap: [BOOKKEEPING])
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda cwd, snap: [])

    rc = _verify_and_iterate(
        tmp_path, {}, lambda event: None, lambda prompt: (0, ""), "goal", verifier=fake_verify
    )

    assert rc == 0
    assert not seen, "a bookkeeping-only run must not run a check it can then call passing"
