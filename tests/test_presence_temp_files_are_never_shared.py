"""Two agents writing presence at once must not share a temporary file.

Measured 2026-10-03 (ten simulated agents): the claim tool failed 1 to 2 times
per run with `presence gate failed: [Errno 13] Permission denied:
...presence\\repo-summary.json.tmp`. Every writer used the same fixed temporary
name before the rename (`agent_presence._write_json`,
`agent_presence_sessions._write`).

The deterministic reproduction needs no race: occupy the OLD fixed temporary
name with a directory. A writer that still uses that name cannot write; a writer
with a unique name never notices.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from thomas.core import agent_presence_sessions, atomic_json
from thomas.core.atomic_json import temp_path_for, write_json_atomic


def _block_old_temp_name(target: Path) -> Path:
    old = target.with_suffix(target.suffix + ".tmp")
    old.mkdir(parents=True)
    return old


def test_the_session_writer_does_not_use_the_old_fixed_temp_name(tmp_path: Path) -> None:
    target = tmp_path / "presence" / "sess-1.json"
    _block_old_temp_name(target)
    agent_presence_sessions._write(target, {"k": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 2}


def test_temp_names_are_unique_per_call_and_stay_beside_the_target(tmp_path: Path) -> None:
    target = tmp_path / "repo-summary.json"
    names = {temp_path_for(target).name for _ in range(50)}
    assert len(names) == 50
    assert all(name.endswith(".tmp") and not name.endswith(".json") for name in names)
    assert temp_path_for(target).parent == target.parent


def test_concurrent_writers_never_fail_and_leave_valid_json_and_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "presence" / "repo-summary.json"
    errors: list[Exception] = []
    start = threading.Barrier(16)

    def writer(worker: int) -> None:
        start.wait()
        try:
            for i in range(25):
                write_json_atomic(target, {"worker": worker, "i": i})
        except (OSError, ValueError) as exc:  # recorded and asserted below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert set(json.loads(target.read_text(encoding="utf-8"))) == {"worker", "i"}
    assert [p.name for p in target.parent.iterdir()] == ["repo-summary.json"], "no stranded temp files"


def test_a_failed_rename_strands_no_temp_file(tmp_path: Path, monkeypatch) -> None:
    """The temp file exists by the time the rename fails, so cleanup is observable."""
    target = tmp_path / "presence" / "repo-summary.json"
    target.parent.mkdir()

    def broken(_src, _dst):
        raise OSError("disk went away")

    monkeypatch.setattr(atomic_json.os, "replace", broken)
    try:
        write_json_atomic(target, {"k": 1})
    except OSError:
        pass
    else:
        raise AssertionError("the rename failure must reach the caller")
    assert list(target.parent.iterdir()) == []
