"""``bootdoctor check``: test thomas.toml, the data folders and every database.

The check does not change what is stored in a database or config file (see
``thomas.core.boot_checks`` for the two small side effects). ``--quarantine`` is
the one thing that moves a file, and it renames a damaged database aside rather
than deleting it.

The exit code is what scripts/repair.ps1 acts on:

* 0 -- nothing wrong.
* 1 -- a problem a repair cannot move aside (a thomas.toml that will not parse,
  a folder Thomas cannot write to). The lines above name the file and the reason.
* 3 -- damaged database file(s) that ``--quarantine`` can move aside.
"""

from __future__ import annotations

import sys
from pathlib import Path

from thomas.core.boot_checks import Row, quarantine_corrupt, run_offline_checks

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_DAMAGED_DATABASE = 3


def _print_rows(rows: list[Row]) -> None:
    for check, status, detail in rows:
        print(f"[{status}] {check}: {detail}")


def run_check(*, root: Path, memory_root: Path | None, config_path: str = "", quarantine: bool = False) -> int:
    # A console in a legacy code page would otherwise raise on a path with unusual characters.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    rows, damaged = run_offline_checks(root, memory_root=memory_root, config_path=config_path or None)
    _print_rows(rows)
    if quarantine and damaged:
        print("[bootdoctor] moving damaged database file(s) aside (renamed, not deleted):")
        for note in quarantine_corrupt(damaged):
            print(f"[bootdoctor] {note}")
        rows, damaged = run_offline_checks(root, memory_root=memory_root, config_path=config_path or None)
        print("[bootdoctor] checked again after the move:")
        _print_rows(rows)

    if damaged:
        return EXIT_DAMAGED_DATABASE
    return EXIT_PROBLEM if any(status == "fail" for _check, status, _detail in rows) else EXIT_OK
