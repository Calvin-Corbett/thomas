"""A source walk cut short holds the run, and only Thomas's runtime tree is skipped at the top (2026-10-14).

The walk behind the parse check, the honest-page check and the data-field check stops at a stall guard and raises
``SourceScanIncomplete`` with the files it had read. What those files show still decides: a broken file or a page
that detects automation still fails. A check those files cannot settle is not met, with the reason, so the run is
held: the verdict counts only checked items, so an unchecked one would have let the run finish.

``runtime`` is skipped only at the top of a Thomas checkout (``pyproject.toml`` and a ``thomas/`` package, the rule
``doppelganger.find_project_root`` uses), or where it holds the doppelganger. A project's own top-level ``runtime/``
is read, and so is ``thomas/server/web/js/runtime``, which holds 100 of Thomas's own scripts.
"""

from __future__ import annotations

import itertools
import time
from pathlib import Path
from types import SimpleNamespace

from thomas.core import acceptance_contract as ac

DETECTS = "if (navigator.webdriver) { hide(); }\n"
BROKEN = "def broken(:\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _items(out_dir: Path, data: str) -> list[ac.ContractItem]:
    return [
        ac.ContractItem("field:data.json:speed", ac.KIND_DATA_FIELD, "speed is used", data, "speed"),
        ac.ContractItem("output:out.txt", ac.KIND_OUTPUT_PATH, "out.txt exists", "prompt", str(out_dir / "out.txt")),
        ac.ContractItem("compiles", ac.KIND_COMPILES, "changed files parse", "workspace"),
        ac.ContractItem("honest_page", ac.KIND_HONEST_PAGE, "no page hides", "workspace"),
    ]


def _workspace(tmp_path: Path) -> list[ac.ContractItem]:
    _write(tmp_path / "data.json", '{"speed": 1}')
    _write(tmp_path / "app.py", "speed = 1\n")
    _write(tmp_path / "bad.py", BROKEN)
    _write(tmp_path / "page.js", DETECTS)
    _write(tmp_path / "out.txt", "done\n")
    return _items(tmp_path, "data.json")


def _by_id(items: list[ac.ContractItem]) -> dict[str, ac.ContractItem]:
    return {it.item_id: it for it in items}


def test_a_finished_walk_judges_every_check(tmp_path: Path) -> None:
    got = _by_id(ac.evaluate_contract(_workspace(tmp_path), workspace=tmp_path, started_at=0.0))
    assert got["field:data.json:speed"].checked and got["field:data.json:speed"].satisfied
    assert got["compiles"].checked and not got["compiles"].satisfied
    assert "bad.py" in got["compiles"].detail
    assert got["honest_page"].checked and not got["honest_page"].satisfied
    assert got["output:out.txt"].checked and got["output:out.txt"].satisfied


def test_a_walk_cut_short_holds_the_run(tmp_path: Path, monkeypatch) -> None:
    items = _workspace(tmp_path)
    monkeypatch.setattr(ac, "_WALK_BUDGET_SECONDS", 0.0)
    evaluated = ac.evaluate_contract(items, workspace=tmp_path, started_at=0.0)
    got = _by_id(evaluated)
    walked = ("field:data.json:speed", "compiles", "honest_page")
    for item_id in walked:
        item = got[item_id]
        assert item.checked and not item.satisfied, item
        assert item.detail.startswith("not verified: the source walk stopped"), item.detail
    assert got["output:out.txt"].checked and got["output:out.txt"].satisfied
    verdict = ac.contract_verdict(evaluated)
    assert not verdict.met
    assert set(verdict.unmet) == set(walked)
    assert verdict.unchecked == ()
    assert ac.verification_trailer(evaluated).count("- FAILED:") == 3
    assert "not verified: the source walk stopped" in ac.verification_trailer(evaluated)


def test_what_a_cut_short_walk_already_read_still_decides(tmp_path: Path, monkeypatch) -> None:
    # Only bad.py and page.js sit at the top, so every walk reads both before it reaches more/, where a clock that
    # ticks one second per look runs out of its 2.5 s on the third file.
    _write(tmp_path / "bad.py", BROKEN)
    _write(tmp_path / "page.js", "if (navigator.webdriver) { hide(speed); }\n")
    _write(tmp_path / "more" / "data.json", '{"speed": 1, "range": 2}')
    _write(tmp_path / "more" / "app.py", "limits = {'speed': 1, 'range': 2}\n")
    _write(tmp_path / "more" / "out.txt", "done\n")
    items = _items(tmp_path / "more", "more/data.json")
    items.append(
        ac.ContractItem("field:data.json:range", ac.KIND_DATA_FIELD, "range is used", "more/data.json", "range")
    )
    ticks = itertools.count()
    monkeypatch.setattr(ac, "time", SimpleNamespace(monotonic=lambda: float(next(ticks)), time=time.time))
    monkeypatch.setattr(ac, "_WALK_BUDGET_SECONDS", 2.5)
    got = _by_id(ac.evaluate_contract(items, workspace=tmp_path, started_at=0.0))
    assert got["compiles"].checked and not got["compiles"].satisfied
    assert "bad.py" in got["compiles"].detail
    assert got["honest_page"].checked and not got["honest_page"].satisfied
    assert "page.js detects automated browsers" in got["honest_page"].detail
    assert got["field:data.json:speed"].satisfied and got["field:data.json:speed"].detail == "referenced in page.js"
    assert got["field:data.json:range"].checked and not got["field:data.json:range"].satisfied
    assert got["field:data.json:range"].detail.startswith("not verified: the source walk stopped")


def _walk_checks(tmp_path: Path) -> dict[str, ac.ContractItem]:
    items = [
        ac.ContractItem("compiles", ac.KIND_COMPILES, "changed files parse", "workspace"),
        ac.ContractItem("honest_page", ac.KIND_HONEST_PAGE, "no page hides", "workspace"),
    ]
    return _by_id(ac.evaluate_contract(items, workspace=tmp_path, started_at=0.0))


def test_a_thomas_checkout_skips_its_runtime_tree_and_nothing_else(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname = 'thomas'\n")
    _write(tmp_path / "thomas" / "__init__.py", "")
    _write(tmp_path / "runtime" / "benchmarks" / "run" / "broken.py", BROKEN)
    _write(tmp_path / ".thomas" / "sessions" / "broken.py", BROKEN)
    _write(tmp_path / "Node_Modules" / "pkg" / "broken.py", BROKEN)
    _write(tmp_path / "thomas" / "server" / "web" / "js" / "runtime" / "boot.js", DETECTS)
    got = _walk_checks(tmp_path)
    assert got["compiles"].checked and got["compiles"].satisfied, got["compiles"].detail
    assert got["honest_page"].checked and not got["honest_page"].satisfied
    assert "boot.js" in got["honest_page"].detail


def test_a_projects_own_runtime_folder_is_read(tmp_path: Path) -> None:
    _write(tmp_path / "runtime" / "core.py", BROKEN)
    _write(tmp_path / "runtime" / "boot.js", DETECTS)
    got = _walk_checks(tmp_path)
    assert got["compiles"].checked and not got["compiles"].satisfied
    assert "core.py" in got["compiles"].detail
    assert got["honest_page"].checked and not got["honest_page"].satisfied
    assert "boot.js" in got["honest_page"].detail
