"""Three leftover run files are gone from the repo root, and nothing reads a file with those names there.

Proves scripts.forge.publish.public_tree (tracked_files) and thomas.server.capacity_ledger (the one place that names
``reservations.json``). ``importers.json`` said the importer harness was stopped and pointed at ``run.json``, which held
the numbers of one old check run; ``reservations.json`` held an empty list. Each was committed by a self-fix by accident.
The reservation ledger of the same name lives in the catalog's ``.thomas/evolve/agent`` folder and is unrelated.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.forge.publish.public_tree import tracked_files

REPO_ROOT = Path(__file__).resolve().parents[1]
LEFTOVERS = ("importers.json", "run.json", "reservations.json")
CODE_FOLDERS = ("thomas/", "scripts/", "apps/", "extensions/", "web/", "installer/", "desktop/")
CODE_SUFFIXES = (".py", ".js", ".mjs", ".ts", ".html", ".cmd", ".ps1", ".sh", ".vbs", ".toml", ".yml", ".yaml")
# ``latest_run.json`` and ``runtime/run.json`` are other files that share the ending.
_NAMED = {name: re.compile(rf"(?<![\w/\\.-]){re.escape(name)}\b") for name in LEFTOVERS}


def _code_files() -> list[Path]:
    paths = [p for p in tracked_files(REPO_ROOT) if p.startswith(CODE_FOLDERS) and p.endswith(CODE_SUFFIXES)]
    return [REPO_ROOT / p for p in paths if (REPO_ROOT / p).is_file()]


def test_the_three_leftovers_are_not_tracked_at_the_root() -> None:
    tracked = set(tracked_files(REPO_ROOT))

    assert not [name for name in LEFTOVERS if name in tracked]
    assert not [name for name in LEFTOVERS if (REPO_ROOT / name).exists()]


def _naming(name: str) -> list[str]:
    return [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _code_files()
        if _NAMED[name].search(path.read_text(encoding="utf-8", errors="ignore"))
    ]


def test_no_code_reads_importers_json() -> None:
    assert _naming("importers.json") == []


def test_run_json_is_named_only_inside_a_research_run_folder_and_an_exported_zip() -> None:
    store = (REPO_ROOT / "thomas/library/research_store.py").read_text(encoding="utf-8")

    assert _naming("run.json") == ["thomas/library/research_store.py", "thomas/server/routes/runs.py"]
    assert [m for m in re.findall(r"\w+ / RUN_JSON|\*/\{RUN_JSON\}", store)] == [
        "run_dir / RUN_JSON",
        "run_dir / RUN_JSON",
        "*/{RUN_JSON}",
    ]


def test_only_the_reservation_ledger_files_name_reservations_json_and_it_looks_in_the_catalog() -> None:
    readers = _naming("reservations.json")
    ledger = (REPO_ROOT / "thomas/server/capacity_ledger.py").read_text(encoding="utf-8")

    # The second file only says so in a sentence about a power cut.
    assert readers == ["thomas/server/capacity_ledger.py", "thomas/server/capacity_ledger_file.py"]
    assert '_catalog_root() / ".thomas" / "evolve" / "agent"' in ledger
