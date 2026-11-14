"""The check keeps its choices and answers while overlapping scratch work and remembering imports."""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from thomas.server import green_checkout
from thomas.server.precard import check, scratch, slot
from thomas.server.proof import selection


def _parse_count(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    parsed: list[str] = []
    real_parse = ast.parse

    def count(text: str, *args: object, **kwargs: object) -> ast.AST:
        parsed.append(text)
        return real_parse(text, *args, **kwargs)

    monkeypatch.setattr(selection.ast, "parse", count)
    return parsed


def _green(part: str, root: Path) -> green_checkout.Green:
    return green_checkout.Green(part, root / part, root / f"{part}.git", "tip", root)


def _waiting_copies(monkeypatch: pytest.MonkeyPatch, root: Path) -> list[str]:
    started = threading.Barrier(2, timeout=5)
    finished: list[str] = []

    def make(blue: Path, tip: str, execution_id: str, part: str) -> green_checkout.Green:
        assert (blue, tip, execution_id) == (root, "tip", "job")
        started.wait()
        finished.append(part)
        return _green(part, root)

    monkeypatch.setattr(scratch, "copy_of_dev", make)
    return finished


def _waiting_removals(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    started = threading.Barrier(2, timeout=5)
    removed: list[str] = []

    def remove(green: green_checkout.Green) -> None:
        started.wait()
        removed.append(green.execution_id)

    monkeypatch.setattr(green_checkout, "remove_green", remove)
    return removed


def test_same_text_is_parsed_only_on_first_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection, "_PARSED", {})
    parsed = _parse_count(monkeypatch)
    texts = {
        "tests/test_a.py": "import os\n",
        "tests/test_b.py": "from pkg import widget\n",
        "tests/test_c.py": "this is invalid Python !!!\n",
    }
    first = selection.select_from(texts, ["pkg/widget.py"])
    assert parsed == [texts["tests/test_b.py"]]
    assert len(selection._PARSED) == 1
    assert all(isinstance(names, frozenset) for names in selection._PARSED.values())
    parsed.clear()
    assert selection.select_from(texts, ["pkg/widget.py"]) == first
    assert parsed == []


def test_changed_text_misses_memo_even_at_same_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection, "_PARSED", {})
    parsed = _parse_count(monkeypatch)
    texts = {"tests/test_a.py": "import os\n", "tests/test_b.py": "import sys\n"}
    before = selection.select_from(texts, ["pkg/widget.py"])
    parsed.clear()
    texts["tests/test_a.py"] = "import pkg.widget\n"
    after = selection.select_from(texts, ["pkg/widget.py"])
    assert parsed == ["import pkg.widget\n"]
    assert "tests/test_a.py" not in before.files
    assert "tests/test_a.py" in after.files


def test_small_memo_clears_before_reaching_three_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {f"tests/test_{i}.py": f"import pkg.widget  # {i}\n" for i in range(3)}
    monkeypatch.setattr(selection, "_PARSED", {})
    expected = selection.select_from(texts, ["pkg/widget.py"])
    assert len(selection._PARSED) == 3
    monkeypatch.setattr(selection, "_PARSED", {})
    monkeypatch.setattr(selection, "_PARSED_MAX", 2)
    assert selection.select_from(texts, ["pkg/widget.py"]) == expected
    assert len(selection._PARSED) == 1


@pytest.mark.parametrize(
    "changed",
    [
        ["thomas/server/precard/check.py", "thomas/server/proof/selection.py"],
        ["tests/conftest.py", "thomas/core/llm_client.py"],
    ],
)
def test_real_selection_agrees_with_warm_memo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed: list[str]
) -> None:
    root = Path(__file__).resolve().parents[1]
    # Use real importer sources without rescanning thousands of unrelated files four times.
    files = (
        "tests/test_architecture.py",
        "tests/test_the_check_before_the_card_starts_sooner.py",
        "tests/test_check_failures_and_lazy_copy_keep_their_clocks.py",
        "tests/test_a_failed_check_cancels_its_second_look.py",
        "tests/test_check_clocks_keep_failed_and_repeated_work.py",
    )
    for rel in files:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / rel).read_bytes())
    monkeypatch.setattr(selection, "_PARSED", {})
    parsed = _parse_count(monkeypatch)
    cold = selection.select(tmp_path, changed, cap=4)
    assert len(parsed) > 0
    parsed.clear()
    warm = selection.select(tmp_path, changed, cap=4)
    assert warm == cold
    assert (warm.files, warm.left_out) == (cold.files, cold.left_out)
    assert parsed == []
    if "tests/conftest.py" in changed:
        assert warm.left_out


@pytest.mark.parametrize(
    "changed",
    [
        ["thomas/server/precard/check.py", "thomas/server/proof/selection.py"],
        ["tests/conftest.py", "thomas/core/llm_client.py"],
    ],
)
def test_small_tree_selection_agrees_with_warm_memo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed: list[str]
) -> None:
    texts = {
        "tests/test_architecture.py": "def test_layers(): pass\n",
        "tests/test_direct.py": "from thomas.server.precard import check\nfrom thomas.core import llm_client\n",
        "tests/test_unicode.py": "from thomas.server.proof import \uff53election\nfrom thomas.core import llm_client\n",
        "tests/test_invalid.py": "broken !!! thomas.server.proof.selection thomas.core.llm_client\n",
        "tests/_inner.py": "from thomas.server.precard import check\nfrom thomas.core import llm_client\n",
        "tests/nested/_outer.py": "from tests import _inner\n",
        "tests/nested/test_helper.py": "from tests.nested import _outer\n",
        "outside/test_ignored.py": "from thomas.server.precard import check\n",
    }
    cap = 8
    unrelated = {f"tests/test_unrelated_{i:03}.py" for i in range(cap + 1)}
    texts.update(dict.fromkeys(unrelated, "import os\n"))
    for rel, text in texts.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    monkeypatch.setattr(selection, "_PARSED", {})
    parsed = _parse_count(monkeypatch)
    cold = selection.select(tmp_path, changed, cap=cap)
    required = {
        "tests/test_architecture.py",
        "tests/test_direct.py",
        "tests/test_unicode.py",
        "tests/test_invalid.py",
        "tests/nested/test_helper.py",
    }
    assert required <= set(cold.files)
    assert "outside/test_ignored.py" not in cold.files + cold.left_out
    assert len(parsed) > 0
    parsed.clear()
    warm = selection.select(tmp_path, changed, cap=cap)
    assert warm == cold
    assert parsed == []
    if "tests/conftest.py" in changed:
        assert len(warm.files) == cap
        assert set(warm.files + warm.left_out) == required | unrelated
        assert len(warm.left_out) == len(required) + 1
    else:
        assert set(warm.files) == required
        assert not warm.left_out


def test_two_copies_start_together_and_return_in_part_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started = _waiting_copies(monkeypatch, tmp_path)
    base, changed = scratch.copies_of_dev(tmp_path, "tip", "job")
    assert (base.execution_id, changed.execution_id) == (scratch.BASE, scratch.WITH_CHANGE)
    assert set(started) == {scratch.BASE, scratch.WITH_CHANGE}


def test_failed_change_copy_waits_for_base_and_removes_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    begun = threading.Barrier(2, timeout=5)
    events: list[str] = []
    failure = green_checkout.GreenUnavailable("cannot copy change")

    def make(blue: Path, tip: str, execution_id: str, part: str) -> green_checkout.Green:
        begun.wait()
        if part == scratch.WITH_CHANGE:
            raise failure
        time.sleep(0.3)
        events.append("base finished")
        return _green(part, tmp_path)

    def remove(green: green_checkout.Green) -> None:
        events.append(f"removed {green.execution_id}")

    monkeypatch.setattr(scratch, "copy_of_dev", make)
    monkeypatch.setattr(green_checkout, "remove_green", remove)
    with pytest.raises(green_checkout.GreenUnavailable) as raised:
        scratch.copies_of_dev(tmp_path, "tip", "job")
    assert raised.value is failure
    assert events == ["base finished", "removed base"]


def test_discard_all_waits_for_both_and_settles_a_failed_removal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    begun = threading.Barrier(2, timeout=5)
    events: list[str] = []

    def remove(green: green_checkout.Green) -> None:
        begun.wait()
        events.append(f"remove {green.execution_id}")
        if green.execution_id == scratch.BASE:
            raise OSError("in use")

    monkeypatch.setattr(green_checkout, "remove_green", remove)
    monkeypatch.setattr(green_checkout, "mark_settled", lambda green: events.append(f"settle {green.execution_id}"))
    scratch.discard_all(_green(scratch.BASE, tmp_path), None, _green(scratch.WITH_CHANGE, tmp_path))
    assert set(events) == {"remove base", "remove change", "settle base"}


def _check_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> green_checkout.Green:
    monkeypatch.setattr(slot, "clear_leftovers", lambda age: None)
    monkeypatch.setattr(slot, "too_little_room", lambda root, **_kw: "")
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    return _green("job", tmp_path)


def test_check_makes_and_removes_only_the_change_copy_when_dev_is_not_needed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    green = _check_setup(monkeypatch, tmp_path)
    made: list[str] = []
    removed: list[str] = []

    def make(blue: Path, tip: str, execution_id: str, part: str) -> green_checkout.Green:
        made.append(part)
        return _green(part, tmp_path)

    monkeypatch.setattr(scratch, "copy_of_dev", make)
    monkeypatch.setattr(green_checkout, "remove_green", lambda copy: removed.append(copy.execution_id))
    passed = check.Checked(check.PASSED, "passed")
    monkeypatch.setattr(check, "_steps", lambda *args: passed)
    assert check._against_dev(green, "tip", "patch", ["pkg/widget.py"], "python") is passed
    assert made == removed == [scratch.WITH_CHANGE]


def test_check_reports_unavailable_and_removes_base_after_change_copy_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    green = _check_setup(monkeypatch, tmp_path)
    removed: list[str] = []

    def make(blue: Path, tip: str, execution_id: str, part: str) -> green_checkout.Green:
        if part == scratch.WITH_CHANGE:
            raise green_checkout.GreenUnavailable("cannot make change")
        return _green(part, tmp_path)

    monkeypatch.setattr(scratch, "copy_of_dev", make)
    monkeypatch.setattr(green_checkout, "remove_green", lambda copy: removed.append(copy.execution_id))
    answer = check._against_dev(green, "tip", "patch", ["pkg/widget.py"], "python")
    assert answer.state == check.UNAVAILABLE
    assert "a scratch copy of dev could not be made" in answer.line
    assert removed == [], "no baseline was made before the patched copy failed"
