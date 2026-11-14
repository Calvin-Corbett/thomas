"""The two threads that read one verdict never write through one temporary file.

``verdict_reached`` says it plainly: "the chat's card and the card mirror both read the verdict". Each does so on its
own thread, and the temporary name was the same for every thread in the server, so one's rename took the file from
under the other's. A full run on 2026-10-30 logged it as "could not record the verdict", with a FileNotFoundError.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from thomas.server import green_handoff

THREADS = 2  # the chat's card and the card mirror
SAVES = 400


def test_saving_from_many_threads_at_once_never_loses_the_file(tmp_path: Path) -> None:
    green = SimpleNamespace(git_dir=tmp_path)
    together = threading.Barrier(THREADS)
    failed: list[OSError] = []

    def save(reader: int) -> None:
        together.wait()
        for n in range(SAVES):
            try:
                green_handoff._save(green, {"status": "refused", "reader": reader, "n": n})
            except OSError as exc:
                failed.append(exc)

    threads = [threading.Thread(target=save, args=(reader,)) for reader in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failed, failed[:3]
    assert [path.name for path in tmp_path.iterdir()] == [green_handoff.HANDOFF_NAME], "nothing stranded beside it"
    assert green_handoff._read_state(tmp_path)["status"] == "refused"
