"""Your chats, memory and settings move into the caged Thomas intact, and nothing dangerous moves.

scripts/cage/move_owner_data_to_cage.py stages your stores as you and installs them
as the cage account. The two hazards it exists to avoid: losing recent writes that
are still in a SQLite WAL file, and carrying a lock whose PID the caged server
would kill on startup.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.cage import move_owner_data_to_cage as move


def _owner(tmp_path: Path) -> tuple[Path, Path, sqlite3.Connection]:
    data, memory = tmp_path / "owner-data", tmp_path / "owner-memory"
    (memory / "sessions_v2").mkdir(parents=True)
    (memory / "sessions_v2" / "chat_aaaa.json").write_text('{"id": "a", "from": "you"}', encoding="utf-8")
    (memory / "sessions_v2" / "chat_shared.json").write_text('{"id": "s", "from": "you"}', encoding="utf-8")
    (memory / "serve.lock").write_text('{"pid": 37924, "port": 8899}', encoding="utf-8")
    (memory / "schedules.json").write_text("[]", encoding="utf-8")
    fabric = sqlite3.connect(memory / "memory_fabric_v2.sqlite3")
    fabric.execute("pragma journal_mode=wal")
    fabric.execute("create table episodes(text)")
    fabric.execute("insert into episodes values ('still in the WAL')")
    fabric.commit()  # left open: the row lives only in the -wal file for now
    (data / ".thomas").mkdir(parents=True)
    (data / ".thomas" / "linked_projects.json").write_text('{"projects": []}', encoding="utf-8")
    prefs = sqlite3.connect(data / "thomas.db")
    prefs.execute("create table preferences(user_id, data_json)")
    prefs.execute("insert into preferences values ('local', '{\"theme\": \"dark\"}')")
    prefs.commit()
    prefs.close()
    return data, memory, fabric


def test_your_stores_arrive_and_the_caged_ones_are_kept_or_backed_up(tmp_path: Path) -> None:
    owner_data, owner_memory, fabric = _owner(tmp_path)
    staging = tmp_path / "staging"
    cage_data, cage_memory = tmp_path / "cage-data", tmp_path / "cage-memory"
    (cage_memory / "sessions_v2").mkdir(parents=True)
    (cage_memory / "sessions_v2" / "chat_shared.json").write_text('{"id": "s", "from": "cage"}', encoding="utf-8")
    cage_data.mkdir()
    (cage_data / "thomas.db").write_bytes(b"the cage's own preferences")

    staged = move.stage(owner_data, owner_memory, staging)
    fabric.close()
    installed = move.install(cage_data, cage_memory, staging)

    assert staged["databases"] == 2 and installed["kept"] == 1
    assert json.loads((cage_memory / "sessions_v2" / "chat_aaaa.json").read_text(encoding="utf-8"))["from"] == "you"
    assert json.loads((cage_memory / "sessions_v2" / "chat_shared.json").read_text(encoding="utf-8"))["from"] == "cage"
    rows = sqlite3.connect(cage_memory / "memory_fabric_v2.sqlite3").execute("select text from episodes").fetchall()
    assert rows == [("still in the WAL",)], "a write still in the WAL must survive the move"
    prefs = sqlite3.connect(cage_data / "thomas.db").execute("select data_json from preferences").fetchall()
    assert prefs == [('{"theme": "dark"}',)]
    assert (cage_data / "pre-move-backup" / "data" / "thomas.db").read_bytes() == b"the cage's own preferences"
    assert (cage_data / ".thomas" / "linked_projects.json").is_file()
    assert not (cage_memory / "serve.lock").exists(), "a copied serve.lock makes the caged server kill yours"
    assert not list(staging.rglob("serve.lock"))
