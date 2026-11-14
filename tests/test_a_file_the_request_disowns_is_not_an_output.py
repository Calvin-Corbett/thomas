"""A file a sentence says is not an output is not one, and a learned check does not bring a misreading back.

On 2026-09-27 four Thomas projects were told: "The completion gate asked for files that were never outputs of your
task: ... files other Thomas projects changed (for example docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md, ...), and auth.json,
the name of a file on this machine ... Never create them to satisfy a check." The contract read every path in that
sentence as a file to create, and three teams created `auth.json` and the other project's doc in their copies to get
past it. Separately, every item a run missed is kept as a learned check and joins every later contract, so the
misreadings fixed earlier that night (other projects' files, a file the task deleted) kept coming back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from thomas.core import acceptance_contract as ac
from thomas.core import acceptance_learning as al

DISOWNING = (
    "Carry on. The completion gate asked for files that were never outputs of your task: files other projects changed "
    "(for example docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md), and auth.json, the name of a file outside your copy. "
    "Write the change up in notes/size.md."
)


def _outputs(text: str, ws: Path, learned: list[dict] | None = None) -> set[str]:
    return {i.item_id for i in ac.build_contract(text, ws, learned=learned or []) if i.kind == ac.KIND_OUTPUT_PATH}


def test_a_sentence_that_says_its_files_are_not_outputs_names_no_output(tmp_path: Path) -> None:
    outputs = _outputs(DISOWNING, tmp_path)

    assert "output:docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md" not in outputs
    assert "output:auth.json" not in outputs
    assert "output:notes/size.md" in outputs  # the sentence that asks for a file still does


def test_do_not_create_names_no_output(tmp_path: Path) -> None:
    assert _outputs("Do not create docs/scratch.md; write the summary to docs/summary.md.", tmp_path) == {
        "output:docs/summary.md"
    }


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "green"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "generate_gap_assets.py").write_text("print('filler')\n", encoding="utf-8")
    run = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*run, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*run, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*run, "commit", "-qm", "base"], cwd=repo, check=True)
    (repo / "scripts" / "generate_gap_assets.py").unlink()  # the task deleted it
    (repo / "docs").mkdir()
    return repo


def _miss(ws: Path, path: str) -> ac.ContractItem:
    return ac.ContractItem(f"output:{path}", ac.KIND_OUTPUT_PATH, f"`{path}` exists", "prompt", str(ws / path))


def test_a_learned_output_the_request_still_mentions_is_read_again(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for path in ("docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md", "scripts/generate_gap_assets.py", "docs/report.md"):
        al.record_misses(repo, [_miss(repo, path)], caught=True)
    learned = al.load_learned(repo)
    notes = "Other Thomas projects are working in their own copies right now.\n- thomas-x: docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md"
    request = f"Delete scripts/generate_gap_assets.py and tidy the folder.\n\n{notes}"

    outputs = _outputs(request, repo, learned)

    assert "output:docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md" not in outputs  # only Thomas's notes name it
    assert "output:scripts/generate_gap_assets.py" not in outputs  # in the last commit: deleted, not made
    assert "output:docs/report.md" in outputs  # a learned output this request never mentions still stands
