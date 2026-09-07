"""A model id in the task is not a file the run must produce (2026-09-06).

The lanes ask named the local models by their Hugging Face ids. The contract's
path rule read "damo-vilab/text-to-video-ms-1.7b" as a path with the extension
".7b" and demanded that it exist and be non-empty in the workspace when the
work was done; it never could, and the run looped on a requirement nobody set.
A path token is an output only when its extension is a real file extension.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core import acceptance_contract as ac


def _outputs(text: str, ws: Path) -> list[str]:
    items = ac.build_contract(text, ws)
    return [i.item_id for i in items if i.kind == ac.KIND_OUTPUT_PATH]


def test_hugging_face_ids_are_not_outputs(tmp_path: Path) -> None:
    text = (
        "Use diffusers with stabilityai/sd-turbo for images, facebook/musicgen-small for music and "
        "damo-vilab/text-to-video-ms-1.7b for video; models are in the cache."
    )
    assert _outputs(text, tmp_path) == []


def test_a_real_file_path_is_still_an_output(tmp_path: Path) -> None:
    assert _outputs("Write the findings to report/summary.md and the raw rows to data/rows.csv", tmp_path) == [
        "output:report/summary.md",
        "output:data/rows.csv",
    ]
