import thomas.tools.git_conflicts as gc


def _mk_conflict(ours: str, theirs: str, tail: str = ">>>>>>> branch") -> str:
    return (
        "<<<<<<< HEAD\n"
        + ours
        + "=======\n"
        + theirs
        + tail
        + "\n"
    )


def test_marker_auto_whitespace_only_takes_ours():
    ours = "a = 1\n"
    theirs = "a    =    1\n"
    txt = "a\n" + _mk_conflict(ours, theirs) + "b\n"
    new, total, unresolved, items, decisions = gc._apply_marker_based_resolution(txt, "auto", "a.py")
    assert total == 1 and unresolved == 0
    assert ours in new
    assert decisions[0].reason == "whitespace_only_take_ours"


def test_marker_auto_needs_manual_keeps_markers():
    ours = "print('hi')\n"
    theirs = "print('bye')\n"
    txt = "a\n" + _mk_conflict(ours, theirs) + "b\n"
    new, total, unresolved, items, decisions = gc._apply_marker_based_resolution(txt, "auto", "a.py")
    assert total == 1 and unresolved == 1
    assert "<<<<<<<" in new and "=======" in new and ">>>>>>>" in new
    assert items and items[0]["ours"] == ours and items[0]["theirs"] == theirs
    assert decisions[0].reason == "needs_manual"


def test_json_merge3_disjoint_keys_merges():
    base = {"a": 1, "b": 1}
    ours = {"a": 2, "b": 1}
    theirs = {"a": 1, "b": 3}
    merged, conflicts = gc._json_merge3(base, ours, theirs, ())
    assert conflicts == []
    assert merged["a"] == 2
    assert merged["b"] == 3


def test_json_merge3_same_key_conflict():
    base = {"a": 1}
    ours = {"a": 2}
    theirs = {"a": 3}
    merged, conflicts = gc._json_merge3(base, ours, theirs, ())
    assert conflicts != []


def test_report_builder_runs():
    md = gc._build_markdown_report([{"file":"x","total_conflicts":1,"auto_resolved":1,"unresolved":0,"fully_resolved":True,"would_write":True,"would_stage":True,"decisions":[{"conflict_index":0,"reason":"identical_deduplicate","chosen":"ours","confidence":0.99}],"diff":"@@\n"}])
    assert "Git conflict resolver preview" in md
    assert "identical_deduplicate" in md
