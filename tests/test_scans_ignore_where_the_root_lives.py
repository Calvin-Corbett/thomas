"""Where a folder is stored must not decide what is found inside it.

Four separate scanners filtered hidden and vendor directories by testing each
file's ABSOLUTE path parts. Thomas keeps his projects and workspaces under
`~/.thomas/`, so `.thomas` matched as an ancestor of every file, and each of
these scans silently returned nothing at all.

The one that was caught in the act cost real work: `_orphaned_web_assets`
reported that nothing loads anything, so Thomas added a script tag, was told
again, added a second, and the page died running the file twice. He was doing
exactly what his verifier told him to.

This test covers the family rather than the instance, because the same mistake
has now been made four times in four files.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Every site that filters directory names while walking a tree.
SITES = [
    # Moved out of thomas/forge/anvil/build_verify.py on 2026-07-28 so the
    # marketplace verifier could call it too. The path has to follow the code:
    # left pointing at build_verify this check would find no filtering lines
    # there and pass by having nothing to look at.
    ("thomas/tools/web_preflight.py", "orphaned_web_assets"),
    ("thomas/tools/visual_edit.py", "_iter_files"),
    ("thomas/tools/design_system.py", "_iter_files"),
    ("thomas/server/exhaustive_artifact_evidence.py", "rglob"),
]


def _lines_filtering_directories(text: str) -> list[str]:
    """Lines that decide whether to skip a path by inspecting its parts."""
    return [
        line
        for line in text.splitlines()
        if ".parts" in line and not line.strip().startswith("#") and re.search(r"part\b", line)
    ]


def test_no_scan_filters_on_an_absolute_paths_parts() -> None:
    offenders = []
    for relative, _ in SITES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for line in _lines_filtering_directories(text):
            # `x.relative_to(...).parts` is correct; a bare `path.parts` is not.
            if re.search(r"(?<!\))\b\w+\.parts\b", line) and "relative_to" not in line:
                offenders.append(f"{relative}: {line.strip()}")
    assert not offenders, "filtering on absolute parts lets the root's own location decide:\n" + "\n".join(offenders)


def test_the_orphan_scan_is_the_one_that_was_caught(tmp_path) -> None:
    """A live check that the fix holds, not just that the source reads right."""
    from thomas.forge.anvil.build_verify import _orphaned_web_assets

    root = tmp_path / ".thomas" / "projects" / "app"
    root.mkdir(parents=True)
    (root / "app.js").write_text("const value = 1;", encoding="utf-8")
    (root / "index.html").write_text('<script src="app.js"></script>', encoding="utf-8")

    assert _orphaned_web_assets(root, ["app.js"]) == []


def test_artifact_evidence_survives_a_dotted_workspace(tmp_path) -> None:
    """Against the absolute path this returned nothing, so a run that produced
    real artifacts could not prove it."""
    from thomas.server.exhaustive_artifact_evidence import _artifact_evidence

    work = tmp_path / ".thomas" / "runtime" / "work"
    work.mkdir(parents=True)
    (work / "report.md").write_text("# real output", encoding="utf-8")

    ok, evidence, _issues = _artifact_evidence(["report.md"], work_dir=str(work))

    assert "report.md" in evidence
    assert ok


def test_a_hidden_folder_inside_the_workspace_is_still_skipped(tmp_path) -> None:
    """The filter must still do its job once it is looking in the right place."""
    from thomas.server.exhaustive_artifact_evidence import _artifact_evidence

    work = tmp_path / ".thomas" / "runtime" / "work"
    (work / ".cache").mkdir(parents=True)
    (work / ".cache" / "junk.md").write_text("noise", encoding="utf-8")
    (work / "report.md").write_text("# real output", encoding="utf-8")

    _ok, evidence, _issues = _artifact_evidence(["report.md"], work_dir=str(work))

    assert not any("junk.md" in name for name in evidence)
