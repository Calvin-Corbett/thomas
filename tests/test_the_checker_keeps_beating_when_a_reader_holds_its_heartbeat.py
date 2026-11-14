"""A heartbeat that cannot be replaced once is tried again, never the end of the beat.

On Windows ``os.replace`` fails while another process has the heartbeat open. The beat thread died on that one error
three times (2026-10-23 09:05, 2026-10-24 04:57 and 11:37): the checker kept running, but with no beat the promoter
read it as gone and the express window could land nothing for five hours.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import checker_service as cs


def test_a_replace_refused_once_is_tried_again_on_the_next_beat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = tmp_path / cj.HEARTBEAT
    real_replace = os.replace
    calls: list[int] = []
    stop = threading.Event()

    def replace(src: object, dst: object) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        real_replace(src, dst)  # type: ignore[arg-type]
        stop.set()

    monkeypatch.setattr(cs.os, "replace", replace)
    cs._beat(beat, stop, every_s=0.01)
    assert len(calls) == 2, "the beat stopped at the first refused replace"
    assert float(beat.read_text(encoding="utf-8")) > 1.0
    assert [path.name for path in tmp_path.iterdir()] == [cj.HEARTBEAT], "no temporary file is left behind"


def test_a_beat_that_keeps_failing_still_ends_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    beat = tmp_path / cj.HEARTBEAT
    stop = threading.Event()
    calls: list[int] = []

    def replace(src: object, dst: object) -> None:
        calls.append(1)
        if len(calls) == 3:
            stop.set()
        raise PermissionError(13, "in use")

    monkeypatch.setattr(cs.os, "replace", replace)
    cs._beat(beat, stop, every_s=0.01)
    assert len(calls) == 3
