import re
from pathlib import Path

import scripts.forge.publish.preflight as preflight
import scripts.forge.publish.private_markers as private_markers
import scripts.forge.publish.snapshot as snapshot

ROOT = Path(__file__).resolve().parent.parent


def test_bible_trash_marker_link_resolves_and_documents_contract() -> None:
    bible = (ROOT / "docs" / "THOMAS_BIBLE.md").read_text(encoding="utf-8")
    marker_doc = ROOT / "docs" / "trash_marker.md"

    assert "[`docs/trash_marker.md`](trash_marker.md)" in bible
    assert "has_private_marker" not in bible
    assert "No current marker enforcement helper" not in bible
    assert "preflight.py` rejects tracked" in bible
    assert "snapshot.py` removes marker files" in bible
    assert "[`scripts/_trash_markers.py`](../scripts/_trash_markers.py)" not in bible
    assert "[`scripts/forge/publish/private_markers.py`](../scripts/forge/publish/private_markers.py)" in bible
    assert "| marker enforcement helper | n/a |" not in bible
    assert marker_doc.is_file()

    text = marker_doc.read_text(encoding="utf-8")
    assert "[Thomas Bible](THOMAS_BIBLE.md)" in text
    delete_after_values = re.findall(r"delete-after: (\d{4}-\d{2}-\d{2}|YYYY-MM-DD)", text)
    assert "YYYY-MM-DD" in delete_after_values
    assert any(value != "YYYY-MM-DD" for value in delete_after_values)
    assert preflight.ACCEPTED_PRIVATE_MARKER_LINES == private_markers.ACCEPTED_PRIVATE_MARKER_LINES
    assert preflight.ACCEPTED_PRIVATE_MARKER_LINES == snapshot.ACCEPTED_PRIVATE_MARKER_LINES

    for required in (
        "THOMAS_TRASH",
        "THOMAS_PRIVATE",
        "delete-after: YYYY-MM-DD",
        "reason:",
        "owner:",
        "checked-in convention source",
        "scripts/forge/publish/private_markers.py",
        "scripts/forge/publish/preflight.py",
        "scripts/forge/publish/snapshot.py",
        "Public publish preflight rejects tracked files",
        "Public snapshot generation strips files",
    ):
        assert required in text

    private_section = text.split("## THOMAS_PRIVATE", maxsplit=1)[1]
    for private_example in (
        "Preferred format in JavaScript",
        "Preferred format in CSS",
        "Preferred format in HTML",
    ):
        assert private_example in private_section

    for marker_line in preflight.ACCEPTED_PRIVATE_MARKER_LINES:
        assert marker_line in text
        assert marker_line in bible
