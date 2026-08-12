"""Two measured Code-run defects, both closed at the prompt level.

1. The final completion message described the delivered page with entirely
   wrong specifics -- it named three cats that do not appear anywhere in the
   shipped file. The summary was written from memory of what the model meant
   to build, not from the artifact it actually built. The composed prompt now
   tells the builder to re-read its changed files before summarizing and to
   name only details present in them.

2. Verification scratch (``.thomas-homepage-server.log``, ``verify-*.cjs``)
   landed in the user's project root, showed up in CHANGED FILES beside their
   real work with a Keep/Revert choice they never asked for, and got swept
   into checkpoint commits. The composed prompt now directs scratch under
   ``.thomas/scratch/`` and asks for cleanup -- and ``project_delta_since``
   (the one filter every user-facing change list flows through) treats
   ``.thomas/scratch/`` as Thomas's own bookkeeping, same as the transcript
   store, so anything the builder parks there is invisible end-to-end.

Neither fix is a gate: nothing rejects or reshapes the run's output. The
prompt steers; the filter only keeps Thomas's own debris out of lists that
describe the user's work.
"""

from __future__ import annotations

from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.forge.anvil.forge_code_git import _run_git, project_delta_since, snapshot


def _prompt() -> str:
    return compose_headless_prompt("Build me a homepage about my three cats")


def test_the_prompt_demands_a_summary_read_from_the_changed_files() -> None:
    """The instruction must say: re-read first, then summarize what is there."""
    prompt = _prompt()
    assert "re-read" in prompt.lower(), "no instruction to re-read the changed files before summarizing"
    assert "only details" in prompt.lower(), (
        "no instruction restricting the summary to details actually present in the files"
    )
    assert "I re-checked" in prompt, "the preferred 'I re-checked <file>' phrasing is not offered"


def test_the_prompt_sends_scratch_under_thomas_scratch_and_asks_for_cleanup() -> None:
    prompt = _prompt()
    assert ".thomas/scratch/" in prompt, "no instruction naming .thomas/scratch/ as the scratch location"
    assert "delete" in prompt.lower(), "no instruction to delete scratch before finishing"


def test_the_scratch_instruction_only_applies_when_the_user_asked_for_a_build() -> None:
    """The new text lives in the build/verify section, after the chat-vs-edit
    framing -- a greeting turn must not open with scratch-file bookkeeping."""
    prompt = _prompt()
    assert prompt.index("ONLY when the user actually asks") < prompt.index(".thomas/scratch/")


def _new_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, ["init"])
    _run_git(repo, ["config", "user.email", "test@example.com"])
    _run_git(repo, ["config", "user.name", "Forge Test"])
    _run_git(repo, ["config", "commit.gpgsign", "false"])
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(repo, ["add", "-A"])
    _run_git(repo, ["commit", "-m", "seed"])
    return repo


def test_scratch_under_thomas_scratch_never_reaches_the_user_change_list(tmp_path) -> None:
    """End-to-end against real git: a run that writes one real file and one
    scratch probe must surface ONLY the real file in ``project_delta_since``,
    which is what the CHANGED FILES drawer, the verifier, and the checkpoint
    all consume."""
    repo = _new_repo(tmp_path)
    snap = snapshot(repo)

    (repo / "index.html").write_text("<!doctype html><p>cats</p>", encoding="utf-8")
    scratch = repo / ".thomas" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "verify-homepage.cjs").write_text("process.exit(0);\n", encoding="utf-8")
    (scratch / "homepage-server.log").write_text("listening on 3000\n", encoding="utf-8")

    changed = project_delta_since(repo, snap)

    assert "index.html" in changed, "the user's real file must still be reported"
    assert not any(p.replace("\\", "/").startswith(".thomas/scratch/") for p in changed), (
        f"scratch debris leaked into the user-facing change list: {changed}"
    )


def test_scratch_left_in_the_project_root_is_still_visible(tmp_path) -> None:
    """The filter is a namespace, not a pattern-match on 'scratch-looking'
    names. A probe the builder drops in the project root anyway MUST stay
    visible -- hiding it would silently reshape the user's working tree, and
    seeing it is how anyone notices the prompt was ignored."""
    repo = _new_repo(tmp_path)
    snap = snapshot(repo)

    (repo / "verify-homepage.cjs").write_text("process.exit(0);\n", encoding="utf-8")

    assert "verify-homepage.cjs" in project_delta_since(repo, snap)
