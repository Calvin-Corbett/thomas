"""The repo summary writer must not use the old fixed temporary name.

Measured 2026-10-03: `presence gate failed: [Errno 13] Permission denied:
...presence\repo-summary.json.tmp` when two agents ran `collect_presence` at once.
Occupying the OLD fixed name with a directory reproduces it without a race.
"""

from __future__ import annotations

import json
from pathlib import Path

from thomas.core import agent_presence


def test_the_summary_writer_does_not_use_the_old_fixed_temp_name(tmp_path: Path) -> None:
    target = tmp_path / "presence" / "repo-summary.json"
    (target.with_suffix(target.suffix + ".tmp")).mkdir(parents=True)
    agent_presence._write_json(target, {"k": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}
