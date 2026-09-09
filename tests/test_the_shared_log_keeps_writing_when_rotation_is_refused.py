"""The log keeps its records when another process holds the file (2026-09-06).

Two Thomas servers on one data dir share thomas.log. When the file reached
its cap, every rotation attempt failed with WinError 32 (the other process
holds the file), and Python's handler then printed a rotation traceback to
stderr and DROPPED the record. Every line of the night's access log became a
traceback, and the one line that mattered, a handler's 500, never reached the
file at all.

Rotation being refused is not a reason to lose the record. The shared handler
writes the record to the current file anyway, notes once that rotation was
skipped and why, and does not retry rotation for a while, so the file grows
past its cap only until the holder lets go.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from thomas.server.log_handlers import SharedRotatingFileHandler


def _handler(path: Path, max_bytes: int = 200) -> SharedRotatingFileHandler:
    handler = SharedRotatingFileHandler(path, maxBytes=max_bytes, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    return handler


def _record(text: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.ERROR, __file__, 1, text, None, None)


def test_a_refused_rotation_keeps_the_record_and_says_so_once(tmp_path: Path, monkeypatch, capsys) -> None:
    log = tmp_path / "thomas.log"
    log.write_text("x" * 300, encoding="utf-8")  # already past the cap: the next record wants a rotation
    handler = _handler(log)

    def held(*_a, **_k):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(os, "rename", held)
    handler.emit(_record("Error handling request: the traceback that must survive"))
    handler.emit(_record("second record"))
    handler.close()

    text = log.read_text(encoding="utf-8")
    assert "the traceback that must survive" in text
    assert "second record" in text
    assert text.count("rotation skipped") == 1, text
    assert "another process" in text
    assert not list(tmp_path.glob("thomas.log.*"))
    assert "Traceback" not in capsys.readouterr().err


def test_rotation_still_happens_when_nothing_holds_the_file(tmp_path: Path) -> None:
    log = tmp_path / "thomas.log"
    log.write_text("x" * 300, encoding="utf-8")
    handler = _handler(log)
    handler.emit(_record("after the cap"))
    handler.close()
    assert (tmp_path / "thomas.log.1").exists()
    assert "after the cap" in log.read_text(encoding="utf-8")
    assert "rotation skipped" not in log.read_text(encoding="utf-8")
