from __future__ import annotations

import json
from pathlib import Path

from scripts import worker_make_note


def test_extract_note_text_handles_common_prompt_shapes():
    assert (
        worker_make_note.extract_note_text("please make a note that says verify api v2 route after restart")
        == "verify api v2 route after restart"
    )
    assert worker_make_note.extract_note_text('make a note that says "call mom".') == "call mom"
    assert worker_make_note.extract_note_text("make me a note buy milk") == "buy milk"


def test_run_writes_exact_note_text(tmp_path, capsys):
    repo_root = Path(tmp_path)

    rc = worker_make_note.run(
        [
            "--summary",
            "please make a note that says verify api chat route after restart",
            "--task-id",
            "chat-note-test",
            "--repo-root",
            str(repo_root),
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    entry = payload["entry"]
    entry_path = repo_root / "library" / str(entry["path"])
    assert entry_path.exists()
    text = entry_path.read_text(encoding="utf-8")
    assert "## Content\nverify api chat route after restart\n" in text
    assert "Reminder note saved." in text
