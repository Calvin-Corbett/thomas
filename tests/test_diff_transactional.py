"""CAP-006: transactional preflight, rollback, and per-hunk accept/reject.

Acceptance line: "Add transactional preflight plus rollback and independent
hunk accept/reject."

Proves, against thomas.tools.diff_transaction and the diff.apply_patch /
diff.preview_patch tools:

* preflight: a single conflicting hunk blocks the ENTIRE apply — no file is
  modified — and the conflicting hunk is named;
* rollback: files are snapshotted before the first write and ALL of them are
  restored when a write fails mid-apply (injected via monkeypatched write);
* selection: a per-hunk accept list applies exactly the accepted subset, and
  the preview exposes the stable hunk ids used to name that subset.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.diff import ApplyPatchTool, PreviewPatchTool
from thomas.tools.diff_transaction import (
    PatchFormatError,
    apply_patch_transactional,
    parse_patch,
    preflight_patch,
)

TWO_FILE_PATCH = (
    "--- a/one.txt\n"
    "+++ b/one.txt\n"
    "@@ -1,3 +1,3 @@\n"
    " alpha\n"
    "-beta\n"
    "+BETA\n"
    " gamma\n"
    "--- a/two.txt\n"
    "+++ b/two.txt\n"
    "@@ -1,2 +1,2 @@\n"
    "-delta\n"
    "+DELTA\n"
    " epsilon\n"
)

MULTI_HUNK_PATCH = (
    "--- a/multi.txt\n"
    "+++ b/multi.txt\n"
    "@@ -1,3 +1,3 @@\n"
    "-line1\n"
    "+LINE1\n"
    " line2\n"
    " line3\n"
    "@@ -5,3 +5,3 @@\n"
    " line5\n"
    "-line6\n"
    "+LINE6\n"
    " line7\n"
)

MULTI_CONTENT = "".join(f"line{i}\n" for i in range(1, 9))


def _write_two_files(root: Path) -> None:
    (root / "one.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (root / "two.txt").write_text("delta\nepsilon\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Stable hunk identifiers (preview names hunks the apply can accept)
# ---------------------------------------------------------------------------


def test_parse_patch_assigns_stable_per_file_hunk_ids() -> None:
    patches = parse_patch(TWO_FILE_PATCH + MULTI_HUNK_PATCH)
    ids = [h.hunk_id for fp in patches for h in fp.hunks]
    assert ids == ["one.txt#1", "two.txt#1", "multi.txt#1", "multi.txt#2"]
    # Re-parsing the same patch text yields the same identifiers.
    again = [h.hunk_id for fp in parse_patch(TWO_FILE_PATCH + MULTI_HUNK_PATCH) for h in fp.hunks]
    assert again == ids


@pytest.mark.asyncio
async def test_preview_patch_tool_exposes_hunk_ids_and_conflict_status(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text(MULTI_CONTENT, encoding="utf-8")
    # Sabotage the second hunk's context so it conflicts.
    conflicted = MULTI_HUNK_PATCH.replace("-line6\n", "-line6-DOES-NOT-MATCH\n")

    result = await PreviewPatchTool(tmp_path).execute({"patch": conflicted})

    assert result.ok
    assert "multi.txt#1 [clean]" in result.data
    assert "multi.txt#2 [conflict]" in result.data
    assert "1/2 hunks apply cleanly" in result.data


# ---------------------------------------------------------------------------
# Transactional preflight: one conflicting hunk blocks the entire apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conflicting_hunk_blocks_entire_apply_and_names_it(tmp_path: Path) -> None:
    _write_two_files(tmp_path)
    # two.txt diverged from what the patch expects -> its hunk conflicts.
    (tmp_path / "two.txt").write_text("changed\nepsilon\n", encoding="utf-8")

    result = await ApplyPatchTool(tmp_path).execute({"patch": TWO_FILE_PATCH})

    assert not result.ok
    assert "nothing applied" in result.error
    assert "two.txt#1" in (result.data or "")
    # The clean hunk (one.txt#1) was NOT applied either — all-or-nothing.
    assert (tmp_path / "one.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
    assert (tmp_path / "two.txt").read_text(encoding="utf-8") == "changed\nepsilon\n"


def test_preflight_reports_every_conflicting_hunk(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text("totally\ndifferent\n", encoding="utf-8")
    report = preflight_patch(MULTI_HUNK_PATCH, tmp_path)
    assert not report.ok
    assert {c.hunk_id for c in report.conflicts} == {"multi.txt#1", "multi.txt#2"}


def test_missing_target_file_is_a_preflight_conflict(tmp_path: Path) -> None:
    report = apply_patch_transactional(TWO_FILE_PATCH, tmp_path)
    assert not report.ok
    assert {c.hunk_id for c in report.conflicts} == {"one.txt#1", "two.txt#1"}
    assert not (tmp_path / "one.txt").exists()


# ---------------------------------------------------------------------------
# Rollback: mid-apply write failure restores ALL affected files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mid_apply_write_failure_restores_all_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_two_files(tmp_path)
    real_write_text = Path.write_text

    def failing_write_text(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self.name == "two.txt":
            raise OSError("disk full (injected)")
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    result = await ApplyPatchTool(tmp_path).execute({"patch": TWO_FILE_PATCH})
    monkeypatch.undo()

    assert not result.ok
    assert "rolled back" in result.error
    # one.txt WAS written (clean hunk) then restored; two.txt untouched/restored.
    assert (tmp_path / "one.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
    assert (tmp_path / "two.txt").read_text(encoding="utf-8") == "delta\nepsilon\n"


def test_mid_apply_failure_removes_files_created_by_the_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_two_files(tmp_path)
    creating_patch = (
        TWO_FILE_PATCH + "--- /dev/null\n" + "+++ b/brand_new.txt\n" + "@@ -0,0 +1,2 @@\n" + "+fresh\n" + "+content\n"
    )
    real_write_text = Path.write_text

    def failing_write_text(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self.name == "brand_new.txt":
            # Simulate a failure after the file handle was created (truncated file).
            real_write_text(self, "", *args, **kwargs)
            raise OSError("device error (injected)")
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    report = apply_patch_transactional(creating_patch, tmp_path)
    monkeypatch.undo()

    assert not report.ok
    assert report.rolled_back
    assert not (tmp_path / "brand_new.txt").exists()
    assert (tmp_path / "one.txt").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
    assert (tmp_path / "two.txt").read_text(encoding="utf-8") == "delta\nepsilon\n"


# ---------------------------------------------------------------------------
# Independent hunk accept/reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subset_selection_applies_exactly_the_accepted_hunks(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text(MULTI_CONTENT, encoding="utf-8")

    result = await ApplyPatchTool(tmp_path).execute({"patch": MULTI_HUNK_PATCH, "hunks": ["multi.txt#2"]})

    assert result.ok
    assert "applied hunks: multi.txt#2" in result.data
    assert "skipped hunks: multi.txt#1" in result.data
    content = (tmp_path / "multi.txt").read_text(encoding="utf-8")
    assert content == "line1\nline2\nline3\nline4\nline5\nLINE6\nline7\nline8\n"


def test_subset_selection_accepts_one_based_global_indices(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text(MULTI_CONTENT, encoding="utf-8")

    report = apply_patch_transactional(MULTI_HUNK_PATCH, tmp_path, selection=["1"])

    assert report.ok
    assert report.applied_hunks == ["multi.txt#1"]
    assert report.skipped_hunks == ["multi.txt#2"]
    content = (tmp_path / "multi.txt").read_text(encoding="utf-8")
    assert content == "LINE1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n"


def test_preflight_runs_only_against_the_selected_subset(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text(MULTI_CONTENT, encoding="utf-8")
    # Hunk #1 conflicts, hunk #2 is clean — selecting only #2 must succeed.
    conflicted = MULTI_HUNK_PATCH.replace("-line1\n", "-line1-STALE\n")

    full = apply_patch_transactional(conflicted, tmp_path)
    assert not full.ok
    assert {c.hunk_id for c in full.conflicts} == {"multi.txt#1"}

    subset = apply_patch_transactional(conflicted, tmp_path, selection=["multi.txt#2"])
    assert subset.ok
    assert subset.applied_hunks == ["multi.txt#2"]
    content = (tmp_path / "multi.txt").read_text(encoding="utf-8")
    assert "LINE6" in content
    assert content.startswith("line1\n")


@pytest.mark.asyncio
async def test_unknown_hunk_selection_applies_nothing(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text(MULTI_CONTENT, encoding="utf-8")

    result = await ApplyPatchTool(tmp_path).execute({"patch": MULTI_HUNK_PATCH, "hunks": ["multi.txt#9"]})

    assert not result.ok
    assert "unknown hunk selection" in result.error
    assert (tmp_path / "multi.txt").read_text(encoding="utf-8") == MULTI_CONTENT


def test_empty_selection_applies_nothing(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text(MULTI_CONTENT, encoding="utf-8")
    report = apply_patch_transactional(MULTI_HUNK_PATCH, tmp_path, selection=[])
    assert not report.ok
    assert "empty hunk selection" in report.error
    assert (tmp_path / "multi.txt").read_text(encoding="utf-8") == MULTI_CONTENT


# ---------------------------------------------------------------------------
# Existing-caller compatibility: default is full apply (all hunks accepted)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_apply_without_selection_applies_all_hunks(tmp_path: Path) -> None:
    _write_two_files(tmp_path)

    result = await ApplyPatchTool(tmp_path).execute({"patch": TWO_FILE_PATCH})

    assert result.ok
    assert "patched: one.txt" in result.data
    assert "patched: two.txt" in result.data
    assert (tmp_path / "one.txt").read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    assert (tmp_path / "two.txt").read_text(encoding="utf-8") == "DELTA\nepsilon\n"


@pytest.mark.asyncio
async def test_new_file_creation_patch_still_works(tmp_path: Path) -> None:
    patch = "--- /dev/null\n+++ b/pkg/created.txt\n@@ -0,0 +1,2 @@\n+first\n+second\n"

    result = await ApplyPatchTool(tmp_path).execute({"patch": patch})

    assert result.ok
    assert (tmp_path / "pkg" / "created.txt").read_text(encoding="utf-8") == "first\nsecond\n"


@pytest.mark.asyncio
async def test_malformed_patch_is_rejected_without_writes(tmp_path: Path) -> None:
    result = await ApplyPatchTool(tmp_path).execute({"patch": "this is not a diff"})
    assert not result.ok
    assert "Patch failed" in result.error


def test_malformed_hunk_header_raises_patch_format_error() -> None:
    bad = "--- a/x.txt\n+++ b/x.txt\n@@ not-a-header @@\n-a\n+b\n"
    with pytest.raises(PatchFormatError):
        parse_patch(bad)
