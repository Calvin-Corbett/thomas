"""A secret moves to the cage account through a pipe that only that account can open.

scripts/cage/move_secret_to_cage.py: your process decrypts, the cage account's
process encrypts again, and between them the value travels through a named pipe
whose permissions admit one account. Nothing is written to a file on the way.
"""

from __future__ import annotations

import getpass
import os
import secrets
import threading
from pathlib import Path

import pytest
from scripts.cage import move_secret_to_cage as mover

from thomas.server.secrets import SecretStore

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows named pipes and DPAPI")


def _pipe() -> str:
    return mover.PIPE_PREFIX + "test-" + secrets.token_hex(8)


def test_the_admitted_account_receives_the_secret_into_its_own_store(tmp_path: Path) -> None:
    pipe, done = _pipe(), threading.Event()
    me = mover._cage_sid(getpass.getuser())
    server = threading.Thread(
        target=mover.serve_once,
        args=(pipe, b'{"channels.discord.bot_token": "tok-123"}'),
        kwargs={"allow_sid": me, "done": done},
        daemon=True,
    )
    server.start()

    names = []
    for _attempt in range(50):  # the pipe appears once the thread has created it
        try:
            names = mover.receive(pipe, tmp_path)
            break
        except FileNotFoundError:
            threading.Event().wait(0.05)
    server.join(timeout=5)

    assert names == ["channels.discord.bot_token"] and done.is_set()
    assert SecretStore(tmp_path).get("channels.discord.bot_token") == "tok-123"
    assert "tok-123" not in (tmp_path / "secrets.json").read_text(encoding="utf-8"), "stored encrypted"


def test_an_account_the_pipe_does_not_admit_cannot_open_it(tmp_path: Path) -> None:
    pipe, done = _pipe(), threading.Event()
    guests = "S-1-5-32-546"
    threading.Thread(
        target=mover.serve_once, args=(pipe, b'{"x": "never"}'), kwargs={"allow_sid": guests, "done": done}, daemon=True
    ).start()

    refused = False
    for _attempt in range(50):
        try:
            mover.receive(pipe, tmp_path)
            break
        except PermissionError:
            refused = True
            break
        except FileNotFoundError:
            threading.Event().wait(0.05)

    assert refused and not done.is_set()
    assert not (tmp_path / "secrets.json").exists()
