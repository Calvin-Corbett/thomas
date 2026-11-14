"""Run receipts stay cheap to save however many there are, and starting a run never saves them on the loop.

On 2026-10-23 the caged server froze again and again. Its freeze dumps (loop-freeze-*.txt) all showed the event
loop inside ``_start_run`` -> ``_save_action_receipt`` -> ``json.dump``: the receipts file held 2,071 runs (22.5 MB)
and every save read all of it and wrote it back indented, on the loop, twice per started run.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from thomas.server.routes import evolve_agent_receipts as receipts

ROUTES = Path(__file__).resolve().parents[1] / "thomas" / "server" / "routes" / "evolve_agent_routes.py"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(receipts, "_KNOWN", {})
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _parses(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    count: list[int] = []
    real = receipts.json.loads

    def counting(*args: Any, **kwargs: Any) -> Any:
        count.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(receipts.json, "loads", counting)
    return count


def test_a_saved_receipt_is_written_compact_and_reads_back(root: Path) -> None:
    receipts._save_action_receipt(root, "run", "request-1", {"state": "launching", "action_hash": "h"})
    key = receipts._receipt_key("run", "request-1")
    text = receipts._entry_path(receipts._receipt_path(root), key).read_text(encoding="utf-8")
    assert "\n" not in text and ": " not in text
    assert receipts._action_receipt(root, "run", "request-1") == {"state": "launching", "action_hash": "h"}


def test_saving_does_not_parse_history_and_reading_only_parses_one_receipt(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts._save_action_receipt(root, "run", "request-1", {"state": "launching"})
    parses = _parses(monkeypatch)
    receipts._save_action_receipt(root, "run", "request-1", {"state": "running"})
    assert parses == [1]
    assert receipts._action_receipt(root, "run", "request-1") == {"state": "running"}
    assert parses == [1, 1]


def test_a_file_another_process_wrote_is_read_again(root: Path) -> None:
    receipts._save_action_receipt(root, "run", "request-1", {"state": "running"})
    key = receipts._receipt_key("run", "request-1")
    path = receipts._entry_path(receipts._receipt_path(root), key)
    other = {key: {"state": "completed", "padding": "x" * 50}}
    path.write_text(json.dumps(other), encoding="utf-8")
    assert receipts._action_receipt(root, "run", "request-1") == other[key]


def test_a_corrupted_file_still_refuses_a_replay(root: Path) -> None:
    receipts._save_action_receipt(root, "run", "request-1", {"state": "running"})
    receipts._receipt_path(root).write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        receipts._action_receipt(root, "run", "request-1")


def test_changing_a_read_receipt_does_not_change_the_kept_one(root: Path) -> None:
    receipts._save_action_receipt(root, "run", "request-1", {"state": "running"})
    read = receipts._action_receipt(root, "run", "request-1")
    assert read is not None
    read.update({"state": "completed"})  # evolve_agent_runtime updates in place before saving
    assert receipts._action_receipt(root, "run", "request-1") == {"state": "running"}


@pytest.mark.parametrize(
    ("module", "function"),
    [(ROUTES, "_start_run"), (ROUTES.with_name("evolve_agent_runtime.py"), "_drain_and_record")],
)
def test_starting_or_ending_a_run_never_touches_receipts_on_the_loop(module: Path, function: str) -> None:
    # 17:13 on 2026-10-23, after the start was fixed: a dump showed the loop saving the receipt as a run ended.
    tree = ast.parse(module.read_text(encoding="utf-8"))
    body = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == function)
    direct = [
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"_action_receipt", "_save_action_receipt"}
    ]
    assert direct == [], f"receipt calls on the event loop at lines {direct} of {module.name}"
