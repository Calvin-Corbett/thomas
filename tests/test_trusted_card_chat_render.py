"""The chat card shows the pairing code and the real diff, both escaped.

The diff is the one field on a trusted card whose content comes straight from a
file Thomas proposes to write -- the most attacker-shaped text on the page. It
must be escaped like every other value, or a protected-write card becomes an
injection point on the one screen you use to decide. Rendering itself is checked
in the Browser pane; these pin the escaping in the source.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "ask_user_panel.js"


def _render_card_source() -> str:
    text = JS.read_text(encoding="utf-8")
    start = text.index("function renderCard(")
    return text[start : text.index("\n  }\n", start)]


def test_the_pairing_code_and_the_diff_are_rendered() -> None:
    src = _render_card_source()
    assert "tc-card-pair" in src and "d.pairing_code" in src
    assert "tc-card-diff" in src and "<pre" in src and "d.excerpt" in src


def test_both_are_escaped() -> None:
    src = _render_card_source()
    assert "esc(d.pairing_code)" in src
    assert "esc(d.excerpt)" in src


def test_no_detail_is_interpolated_raw() -> None:
    """Every ${...} holding card data goes through esc(). The only raw ones are
    the option markers, which the code builds itself from a boolean and an index."""
    src = _render_card_source()
    raw = [m.strip() for m in re.findall(r"\$\{([^}]*)\}", src) if not m.strip().startswith("esc(")]
    data_like = [m for m in raw if re.search(r"\bd\.\w+|\bf\.\w+|question\.", m)]
    assert not data_like, f"card data interpolated without esc(): {data_like}"
