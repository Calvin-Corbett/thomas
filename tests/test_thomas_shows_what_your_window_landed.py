"""Thomas shows a change that landed in your window as such, and what each window landed (spec section 8.4).

Its own tmp record folder; never C:\\ProgramData\\ThomasWindow. The route is registered by ``window_records`` for the
``thomas.server.rows.windows`` row, which tests/test_turning_windows_off_touches_only_its_routes.py holds.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from thomas.server import self_change_cards, window_records

ROW = Path(__file__).resolve().parents[1] / "thomas" / "server" / "rows" / "windows.py"


def test_a_change_that_landed_in_your_window_says_so_and_names_no_card() -> None:
    verdict = {"status": "landed", "window": {"window_id": "w1", "opened_at": "2026-10-15T14:02:00+00:00",
                                              "pairing_code": "ABC-DEF"}}  # fmt: skip
    field = self_change_cards.landed_on(verdict)
    assert field == {
        "label": "Landed in",
        "value": "your window opened at 2026-10-15T14:02:00+00:00 (pairing code ABC-DEF), with no card",
    }
    assert self_change_cards.landed_on({**verdict, "status": "refused"}) is None
    shared = {"status": "landed", "card": {"pairing_code": "XYZ-123", "position": 1, "of": 2}}
    assert self_change_cards.landed_on(shared)["label"] == "Approved on"  # type: ignore[index]


def _event(root: Path, seq: int, name: str, **fields: object) -> None:
    (root / f"{seq:08d}-{name}.json").write_text(json.dumps({"seq": seq, "name": name, **fields}), encoding="utf-8")


def test_the_windows_are_read_newest_first_with_what_each_landed(tmp_path: Path) -> None:
    _event(tmp_path, 1, "window_opened", window_id="w1", opened_at="t1", minutes=60, ends="15:02", pairing_code="AAA")
    row = {"sid": "self-thomas-a", "commit": "c" * 40, "files": ["thomas/x.py"], "added": 3, "deleted": 1}
    _event(tmp_path, 2, "window_closed", window_id="w1", reason="its time is up", landed=[row])
    _event(tmp_path, 3, "window_opened", window_id="w2", opened_at="t2", minutes=30, ends="16:00", pairing_code="BBB")
    (tmp_path / "00000004-window_closed.json").write_text("{torn", encoding="utf-8")

    windows = window_records.read_windows(tmp_path)

    assert [w["window_id"] for w in windows] == ["w2", "w1"]
    assert windows[1]["ended"] == "its time is up" and windows[1]["landed"] == [row]
    assert windows[0]["pairing_code"] == "BBB" and windows[0]["landed"] == []
    assert window_records.read_windows(tmp_path / "missing") == []


def test_the_route_is_registered_behind_the_loopback_guard() -> None:
    tree = ast.parse(Path(window_records.__file__).read_text(encoding="utf-8"))
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "register_window_routes"]
    assert len(found) == 1
    handler = next(n for n in ast.walk(found[0]) if isinstance(n, ast.AsyncFunctionDef))
    calls = [ast.unparse(n.func) for n in ast.walk(handler) if isinstance(n, ast.Call)]
    assert calls.index("require_loopback") < calls.index("read_windows")
    # The row hands the registrar the server's loopback guard, and nothing else registers the route.
    row = ast.unparse(ast.parse(ROW.read_text(encoding="utf-8")))
    assert "register_window_routes(service.view(ctx), require_loopback=service.require_loopback)" in row
