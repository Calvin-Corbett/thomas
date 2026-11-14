"""A page shipped to a stranger must not show a real folder from the machine it was built on.

The My Stuff import form's example folder was a real project on one drive, shown to
everyone who opens the form. Rather than list the names that must never come back, this
pins the other side: every drive path a shipped page shows is one of the neutral
examples below. A new example has to be added here on purpose, so it gets looked at.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web"

# Made-up folders that belong to nobody. Add an entry only for another made-up folder.
NEUTRAL_EXAMPLES = frozenset(
    {
        "C:\\Users\\you\\projects\\my-app",
        "C:\\VMs\\ThomasWorkerTemplate.vhdx",
    }
)
_DRIVE_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s\"'<>]*")


def _drive_paths() -> list[tuple[str, int, str]]:
    found = []
    for page in sorted(WEB.rglob("*.html")):
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            found.extend((str(page.relative_to(WEB)), number, hit) for hit in _DRIVE_PATH.findall(line))
    return found


def test_every_drive_path_a_shipped_page_shows_is_a_neutral_example() -> None:
    assert sorted(WEB.rglob("*.html")), "expected web pages under thomas/server/web"
    hits = _drive_paths()
    assert hits, "the pages no longer show any example path; check the pattern"
    real = [f"{page}:{number} {path}" for page, number, path in hits if path not in NEUTRAL_EXAMPLES]
    assert not real, f"pages that show a path that is not a neutral example: {real}"


def test_the_import_form_still_gives_an_example_path_and_name() -> None:
    text = (WEB / "static" / "my_stuff.html").read_text(encoding="utf-8")
    for field in ("projectPathInput", "projectNameInput"):
        match = re.search(rf'id="{field}"[^>]*placeholder="([^"]+)"', text)
        assert match, f"{field} lost its example"
    path = re.search(r'id="projectPathInput"[^>]*placeholder="([^"]+)"', text).group(1)
    assert path in NEUTRAL_EXAMPLES, path
