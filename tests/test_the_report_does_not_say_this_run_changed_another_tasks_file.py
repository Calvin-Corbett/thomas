"""The run report must not contradict itself about who wrote a file.

`changed_files` is the git delta of a SHARED project folder, not a record of what
this run wrote. Thomas allows eight simultaneous Code runs, so another task's
uncommitted file landing in this run's delta is ordinary. `_build_open_risks`
already knows this and deliberately says "this run may not have written them"
rather than "overwritten here" — but `_build_attention_pointers` was never told,
and stamped "changed in this run" on the very same filenames.

MEASURED, one report, two sections, built from the Godot-FPS case recorded in
`forge_code_store.files_written_by_another_task` (a shared folder where two other
tasks wrote alpha.txt and gamma.txt while the FPS run held it):

    BEFORE
      open_risks         this run's changes include work from another code task:
                         alpha.txt, gamma.txt — ... this run may not have written them
      attention_pointers #1 index.html -- changed in this run
                         #2 alpha.txt  -- changed in this run     <- false
                         #3 gamma.txt  -- changed in this run     <- false

    AFTER
                         #1 index.html -- changed in this run
                         #2 alpha.txt  -- in this run's changed-file list, but created
                                          by a different code task ... may not have written it
                         #3 gamma.txt  -- (same)

The CONTROL is what makes this a defect and not a wording preference. Run the
same builder with `foreign_writes=[]` — a run that genuinely wrote all three —
and BEFORE the fix the three pointer rows are character-for-character identical
to the ones above. The sentence was printed either way, so it carried no
information about authorship at all.

Second measurement, the ranking. `_MAX_POINTERS` caps the list at 10 and the old
order was raw git order, so another task's leftovers could evict this run's own
work completely. Ten stale `alpha_*.txt` plus the two files the run wrote:

    BEFORE  #1..#10 alpha_0.txt .. alpha_9.txt   (this run's own files: NONE)
    AFTER   #1 zz_game.js, #2 zz_index.html, then the foreign ones
"""

from __future__ import annotations

import json

from thomas.forge.anvil.run_report import build_run_report

# The measured Godot-FPS shape: three files in the delta, two of them another
# task's. The transcript is a normal one-write, one-check run.
_TRANSCRIPT = "/n".join(
    [
        json.dumps({"fc": "tool_result", "name": "fs.write_file", "text": "Wrote 4120 chars to index.html"}),
        json.dumps({"fc": "tool", "name": "run", "text": "static verify"}),
        json.dumps({"fc": "tool_result", "text": "STATIC_VERIFY_OK: index.html alpha.txt gamma.txt"}),
    ]
)


def _report(changed: list[str], foreign: list[str]) -> dict:
    return build_run_report(
        goal="build the FPS",
        transcript=_TRANSCRIPT,
        changed_files=changed,
        returncode=0,
        ok=True,
        outcome="completed",
        reason=f"{len(changed)} file(s) changed",
        foreign_writes=foreign,
    )


def _why(report: dict, target: str) -> str:
    return next(p["why"] for p in report["attention_pointers"] if p["target"] == target)


def test_another_tasks_file_is_not_called_changed_in_this_run() -> None:
    report = _report(["index.html", "alpha.txt", "gamma.txt"], ["alpha.txt", "gamma.txt"])

    for stranger in ("alpha.txt", "gamma.txt"):
        why = _why(report, stranger)
        assert "changed in this run" not in why, (
            f"{stranger} was created by a different task; this run has no basis for claiming it changed it"
        )
        assert "may not have written it" in why, f"{stranger} must say what the data actually supports"


def test_the_run_s_own_file_is_still_called_changed_in_this_run() -> None:
    """The control for the test above: the fix withholds a claim, it does not delete a phrase."""
    report = _report(["index.html", "alpha.txt", "gamma.txt"], ["alpha.txt", "gamma.txt"])

    assert _why(report, "index.html") == "changed in this run"


def test_a_run_with_no_foreign_writes_labels_every_file_the_same_as_before() -> None:
    """A run that really did write everything must be untouched by this change."""
    report = _report(["index.html", "alpha.txt", "gamma.txt"], [])

    assert [p["why"] for p in report["attention_pointers"]] == ["changed in this run"] * 3


def test_the_pointers_never_contradict_the_report_s_own_risks() -> None:
    """The invariant, stated once: no file the risks say may not be ours is
    labelled as ours. This is the cross-section guard — the two halves are built
    from one list now, and this fails if they are ever split again."""
    changed = ["index.html", "alpha.txt", "gamma.txt"]
    foreign = ["alpha.txt", "gamma.txt"]
    report = _report(changed, foreign)

    risk_text = " ".join(f"{r['risk']} {r['detail']}" for r in report["open_risks"])
    assert "may not have written them" in risk_text, "the risk must still fire, or this proves nothing"

    for pointer in report["attention_pointers"]:
        if pointer["target"] in foreign:
            assert "changed in this run" not in pointer["why"]


def test_another_tasks_leftovers_cannot_push_this_run_s_work_off_the_list() -> None:
    """`_MAX_POINTERS` is 10; ten stale files used to fill it and leave none of ours."""
    foreign = [f"alpha_{i}.txt" for i in range(10)]
    mine = ["zz_game.js", "zz_index.html"]
    report = _report([*foreign, *mine], foreign)

    targets = [p["target"] for p in report["attention_pointers"]]
    assert targets[:2] == mine, "this run's own files must be the reviewer's first stop"
    for name in mine:
        assert name in targets, f"{name} was written by this run and must survive the cap"


def test_a_windows_spelled_path_still_matches_a_forward_slash_foreign_name() -> None:
    """`files_written_by_another_task` normalises separators on the way out, so the
    two lists can disagree on spelling. An unnormalised comparison would fail OPEN
    — the file keeps the false "changed in this run" label — which is the worst
    direction for this particular guard to fail in."""
    report = _report(["src\\alpha.txt", "src\\mine.js"], ["src/alpha.txt"])

    assert "changed in this run" not in _why(report, "src\\alpha.txt")
    assert _why(report, "src\\mine.js") == "changed in this run"


def test_a_failing_check_reference_outranks_and_outlives_the_authorship_label() -> None:
    """"referenced by a failing check" is a statement about a CHECK, not about who
    wrote the file, so it stays true for a foreign file and must not be replaced."""
    events = [
        {"fc": "tool", "name": "run", "text": "pytest"},
        {"fc": "tool_result", "is_error": True, "text": "alpha.txt:12: SyntaxError"},
    ]
    report = build_run_report(
        goal="g",
        events=events,
        changed_files=["alpha.txt"],
        returncode=1,
        ok=False,
        outcome="failed",
        reason="exited 1",
        foreign_writes=["alpha.txt"],
    )
    whys = " ".join(p["why"] for p in report["attention_pointers"])

    assert "referenced by a failing check or error" in whys
    assert "changed in this run" not in whys
