"""Tests for thomas.tools.source_annotations (CAP-147 backend core).

Proves the exact L2 acceptance line -- "User-authored anchored annotations that
open agent conversations and create source diffs" -- deterministically against a
hermetic dict-backed reader, injected clock, and injected id factory. No network,
no real disk source files, temp store path only.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.tools.source_annotations import (
    STATUS_ANCHORED,
    STATUS_ORPHANED,
    AnnotationStore,
    NoSuggestedEditError,
    OrphanedAnchorError,
    apply_unified_diff,
)

# ---------------------------------------------------------------------------
# Hermetic seams
# ---------------------------------------------------------------------------


class FakeReader:
    """Dict-backed file reader: maps path -> current text. Mutable for edits."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = dict(files)

    def __call__(self, path: str) -> str:
        return self.files[path]


def make_clock():
    counter = itertools.count(1)
    return lambda: f"2026-07-21T00:00:{next(counter):02d}+00:00"


def make_id_factory():
    counter = itertools.count(1)
    return lambda: f"ann-{next(counter):03d}"


ORIGINAL = "\n".join(
    [
        "def alpha():",  # 1
        "    return 1",  # 2
        "",  # 3
        "def beta():",  # 4
        "    x = compute()",  # 5  <-- anchor target
        "    return x",  # 6
        "",  # 7
        "def gamma():",  # 8
        "    return 3",  # 9
    ]
)


def build_store(tmp_path, files):
    return AnnotationStore(
        tmp_path / "annotations.json",
        reader=FakeReader(files),
        clock=make_clock(),
        id_factory=make_id_factory(),
    )


# ---------------------------------------------------------------------------
# (1) create anchored annotation
# ---------------------------------------------------------------------------


def test_create_captures_region_and_context(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    ann = store.create_annotation("m.py", 5, 5, "why compute here?")
    assert ann.id == "ann-001"
    assert ann.status == STATUS_ANCHORED
    assert ann.anchor.line_start == 5
    assert ann.anchor.line_end == 5
    assert ann.anchor.region_lines == ["    x = compute()"]
    # Context captured around the region (DEFAULT_CONTEXT_LINES=3 each side).
    assert ann.anchor.before_context == ["    return 1", "", "def beta():"]
    assert ann.anchor.after_context == ["    return x", "", "def gamma():"]


def test_create_rejects_bad_range(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    with pytest.raises(ValueError):
        store.create_annotation("m.py", 0, 2, "bad")
    with pytest.raises(ValueError):
        store.create_annotation("m.py", 5, 99, "past end")


# ---------------------------------------------------------------------------
# (2) re-anchor: survive an edit ABOVE, orphan when the anchor text is deleted
# ---------------------------------------------------------------------------


def test_reanchor_survives_edit_above(tmp_path):
    reader = FakeReader({"m.py": ORIGINAL})
    store = AnnotationStore(
        tmp_path / "s.json",
        reader=reader,
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    ann = store.create_annotation("m.py", 5, 5, "note")
    assert ann.anchor.line_start == 5

    # Insert two brand-new lines at the top -> the anchored region moves to 7.
    edited = "\n".join(["# header", "# license"]) + "\n" + ORIGINAL
    reader.files["m.py"] = edited

    updated = store.reanchor(ann.id)
    assert updated.status == STATUS_ANCHORED
    assert updated.anchor.line_start == 7
    assert updated.anchor.line_end == 7
    # Points at the SAME text, now on the correct new line.
    assert updated.anchor.region_lines == ["    x = compute()"]
    new_lines = edited.split("\n")
    assert new_lines[updated.anchor.line_start - 1] == "    x = compute()"


def test_reanchor_orphans_when_anchor_text_deleted(tmp_path):
    reader = FakeReader({"m.py": ORIGINAL})
    store = AnnotationStore(
        tmp_path / "s.json",
        reader=reader,
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    ann = store.create_annotation("m.py", 5, 5, "note")

    # Delete the anchored line entirely.
    edited = "\n".join(
        [
            "def alpha():",
            "    return 1",
            "",
            "def beta():",
            "    return x",
            "",
            "def gamma():",
            "    return 3",
        ]
    )
    reader.files["m.py"] = edited

    updated = store.reanchor(ann.id)
    assert updated.status == STATUS_ORPHANED
    # Last-known range is left untouched -- NOT silently re-pointed at other code.
    assert updated.anchor.line_start == 5
    assert updated.anchor.region_lines == ["    x = compute()"]


def test_reanchor_disambiguates_duplicate_region_by_context(tmp_path):
    # Two identical region lines; context must select the original neighbourhood.
    src = "\n".join(
        [
            "def a():",  # 1
            "    return 1",  # 2  duplicate text
            "def b():",  # 3
            "    return 1",  # 4  duplicate text  <-- anchor here (ctx: def b)
        ]
    )
    reader = FakeReader({"m.py": src})
    store = AnnotationStore(
        tmp_path / "s.json",
        reader=reader,
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    ann = store.create_annotation("m.py", 4, 4, "b's return")
    assert ann.anchor.before_context == ["def a():", "    return 1", "def b():"]

    # Prepend a line so everything shifts down by one; both duplicates remain.
    reader.files["m.py"] = "# top\n" + src
    updated = store.reanchor(ann.id)
    # Should track the 'def b()' occurrence -> now line 5, not the 'def a()' one.
    assert updated.status == STATUS_ANCHORED
    assert updated.anchor.line_start == 5
    assert ("# top\n" + src).split("\n")[updated.anchor.line_start - 2] == "def b():"


def test_reanchor_file_reanchors_all(tmp_path):
    reader = FakeReader({"m.py": ORIGINAL})
    store = AnnotationStore(
        tmp_path / "s.json",
        reader=reader,
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    a1 = store.create_annotation("m.py", 2, 2, "alpha body")
    a2 = store.create_annotation("m.py", 5, 5, "beta body")
    reader.files["m.py"] = "# header\n" + ORIGINAL
    updated = store.reanchor_file("m.py")
    by_id = {a.id: a for a in updated}
    assert by_id[a1.id].anchor.line_start == 3
    assert by_id[a2.id].anchor.line_start == 6


# ---------------------------------------------------------------------------
# (3) open a conversation
# ---------------------------------------------------------------------------


def test_open_conversation_links_ref(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    ann = store.create_annotation("m.py", 5, 5, "discuss this")
    assert ann.conversation_ref is None
    linked = store.open_conversation(ann.id, "thread-42")
    assert linked.conversation_ref == "thread-42"
    # Persisted: a fresh store instance reads the linked ref back.
    reopened = AnnotationStore(tmp_path / "annotations.json", reader=FakeReader({"m.py": ORIGINAL}))
    assert reopened.get(ann.id).conversation_ref == "thread-42"


def test_open_conversation_rejects_empty(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    ann = store.create_annotation("m.py", 5, 5, "x")
    with pytest.raises(ValueError):
        store.open_conversation(ann.id, "")


# ---------------------------------------------------------------------------
# (4) emit a source diff -- valid unified diff that APPLIES the suggested edit
# ---------------------------------------------------------------------------


def test_emit_diff_applies_suggested_edit_at_anchor(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    ann = store.create_annotation(
        "m.py",
        5,
        5,
        "rename for clarity",
        suggested_edit="    x = compute_total()",
    )
    diff = store.emit_diff(ann.id)

    # Valid unified-diff shape.
    assert diff.startswith("--- a/m.py")
    assert "+++ b/m.py" in diff
    assert "@@" in diff
    assert "-    x = compute()" in diff
    assert "+    x = compute_total()" in diff

    # And it actually applies to produce exactly the intended file.
    expected = ORIGINAL.replace("    x = compute()", "    x = compute_total()")
    assert apply_unified_diff(ORIGINAL, diff) == expected


def test_emit_diff_multiline_replacement_applies(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    ann = store.create_annotation(
        "m.py",
        5,
        6,
        "inline the return",
        suggested_edit="    return compute()",
    )
    diff = store.emit_diff(ann.id)
    expected = ORIGINAL.replace("    x = compute()\n    return x", "    return compute()")
    assert apply_unified_diff(ORIGINAL, diff) == expected


def test_emit_diff_targets_current_lines_after_edit_above(tmp_path):
    reader = FakeReader({"m.py": ORIGINAL})
    store = AnnotationStore(
        tmp_path / "s.json",
        reader=reader,
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    ann = store.create_annotation("m.py", 5, 5, "note", suggested_edit="    x = compute_total()")
    edited = "# header\n# banner\n" + ORIGINAL
    reader.files["m.py"] = edited
    diff = store.emit_diff(ann.id)
    # Diff targets the CURRENT text: applying it to the edited file (where the
    # region now lives on line 7) yields exactly the intended replacement.
    assert "-    x = compute()" in diff
    assert "+    x = compute_total()" in diff
    expected = edited.replace("    x = compute()", "    x = compute_total()")
    assert apply_unified_diff(edited, diff) == expected


def test_emit_diff_without_suggested_edit_raises(tmp_path):
    store = build_store(tmp_path, {"m.py": ORIGINAL})
    ann = store.create_annotation("m.py", 5, 5, "just a note")
    with pytest.raises(NoSuggestedEditError):
        store.emit_diff(ann.id)


def test_emit_diff_orphaned_raises(tmp_path):
    reader = FakeReader({"m.py": ORIGINAL})
    store = AnnotationStore(
        tmp_path / "s.json",
        reader=reader,
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    ann = store.create_annotation("m.py", 5, 5, "note", suggested_edit="    x = compute_total()")
    reader.files["m.py"] = ORIGINAL.replace("    x = compute()\n", "")
    with pytest.raises(OrphanedAnchorError):
        store.emit_diff(ann.id)


# ---------------------------------------------------------------------------
# round-trip persistence + determinism
# ---------------------------------------------------------------------------


def test_round_trip_persistence(tmp_path):
    path = tmp_path / "annotations.json"
    store = AnnotationStore(
        path,
        reader=FakeReader({"m.py": ORIGINAL}),
        clock=make_clock(),
        id_factory=make_id_factory(),
    )
    ann = store.create_annotation(
        "m.py", 5, 5, "note", suggested_edit="    x = compute_total()", conversation_ref="t-1"
    )

    reopened = AnnotationStore(path, reader=FakeReader({"m.py": ORIGINAL}))
    got = reopened.get(ann.id)
    assert got.to_dict() == ann.to_dict()
    assert got.anchor.region_lines == ["    x = compute()"]
    assert got.suggested_edit == "    x = compute_total()"
    assert got.conversation_ref == "t-1"


def test_determinism_same_inputs_same_bytes(tmp_path):
    def run(path):
        store = AnnotationStore(
            path,
            reader=FakeReader({"m.py": ORIGINAL}),
            clock=make_clock(),
            id_factory=make_id_factory(),
        )
        store.create_annotation("m.py", 2, 2, "a", suggested_edit="    return 11")
        store.create_annotation("m.py", 5, 5, "b")
        return path.read_text(encoding="utf-8")

    first = run(tmp_path / "a.json")
    second = run(tmp_path / "b.json")
    assert first == second


def test_emit_diff_is_deterministic(tmp_path):
    def diff_once():
        s = AnnotationStore(
            tmp_path / "x.json",
            reader=FakeReader({"m.py": ORIGINAL}),
            clock=make_clock(),
            id_factory=make_id_factory(),
        )
        a = s.create_annotation("m.py", 5, 5, "n", suggested_edit="    x = q()")
        return s.emit_diff(a.id)

    assert diff_once() == diff_once()
