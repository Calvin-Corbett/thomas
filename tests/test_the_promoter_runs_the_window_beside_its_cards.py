"""The promoter's process runs your window on a thread of its own, and one sign-in prompt at a time (spec 8.3-8.4).

Nothing real starts: no egress proxy, no search broker, no Windows prompt, no checker. Every folder is tmp.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from scripts.cage import promoter_service as ps
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_loop as wl

from tests.green_support import git, make_blue
from thomas.tools import trusted_card


class Stop(BaseException):
    """Ends the service's loop from inside a test."""


def test_the_service_starts_the_window_beside_the_cards_with_one_shared_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: dict[str, object] = {}
    monkeypatch.setattr(ps.egress_proxy, "start_in_thread", lambda **_kw: None)
    monkeypatch.setattr(ps._BrokerKeeper, "start", lambda self: None)
    monkeypatch.setattr(ps.window_loop, "start", lambda **kw: started.update(kw))

    def one_pass(self: sp.Promoter) -> None:
        raise Stop

    monkeypatch.setattr(sp.Promoter, "run_once", one_pass)

    with pytest.raises(Stop):
        ps.main(["--cage-root", str(tmp_path / "cage"), "--repo", str(tmp_path)])

    assert isinstance(started["card"], sp.Promoter) and isinstance(started["ask"], wl.OnePrompt)
    assert started["card"].ask is started["ask"], "the cards and the window share one prompt"


def test_a_window_that_cannot_start_leaves_every_change_on_its_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tampered() -> object:
        raise trusted_card.CatalogueTampered("the cards do not match their pin")

    monkeypatch.setattr(trusted_card, "load_catalogue", tampered)
    card = sp.Promoter(repo=tmp_path, cage_root=tmp_path / "cage", ask=lambda a, r: False)

    loop = wl.start(repo=tmp_path, cage_root=tmp_path / "cage", card=card, ask=card.ask, stop=threading.Event(),
                    check_root=tmp_path / "check", record_root=tmp_path / "record")  # fmt: skip

    assert loop is None and card.skip() == frozenset()


def test_the_window_thread_starts_hands_the_card_loop_its_skip_and_stops_with_the_service(tmp_path: Path) -> None:
    repo = make_blue(tmp_path)
    git(repo, "checkout", "-q", "-b", "dev")
    (tmp_path / "record").mkdir()
    card = sp.Promoter(repo=repo, cage_root=tmp_path / "cage", ask=lambda a, r: False)
    stop = threading.Event()

    loop = wl.start(repo=repo, cage_root=tmp_path / "cage", card=card, ask=card.ask, stop=stop,
                    check_root=tmp_path / "check", record_root=tmp_path / "record")  # fmt: skip

    assert loop is not None and card.skip == loop.card_skip
    names = [thread.name for thread in threading.enumerate()]
    assert "window-loop" in names
    stop.set()
    for _ in range(50):
        if "window-loop" not in [thread.name for thread in threading.enumerate()]:
            break
        time.sleep(0.1)
    assert "window-loop" not in [thread.name for thread in threading.enumerate()]
