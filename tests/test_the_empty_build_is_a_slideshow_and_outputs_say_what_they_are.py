"""An empty Build shows a slowly turning slideshow, and the drawer's Outputs say what they are and open on a click."""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def _read(relative: str) -> str:
    return (WEB / relative).read_text(encoding="utf-8")


def test_the_slideshow_is_loaded_and_replaces_the_question():
    html = _read("chat.html")
    assert "/static/js/unified_code_home.js" in html and "/static/css/unified_code_home.css" in html
    events = _read("js/unified_code_events.js")
    assert "window.ThomasCodeHome.html(esc, CODE_STARTERS" in events
    assert "ThomasCodeHome" in events.split("function emptyStateHtml")[1].split("const cards")[0]


def test_the_slideshow_has_every_slide_arrows_dots_and_the_starters_last():
    source = _read("js/unified_code_home.js")
    for key in ("stats", "perf", "perday", "tokens", "noticed", "recent", "ideas"):
        assert f"{key}(data)" in source, key
    assert "ORDER = ['stats', 'perf', 'perday', 'tokens', 'noticed', 'recent', 'ideas']" in source
    assert "data-home-step" in source and "data-home-go" in source and "'ArrowLeft'" in source
    # Each slide that suggests something does it with a button that fills the composer; recent tasks open the task.
    assert "data-home-fill" in source and "data-home-open" in source and "fillComposer" in source
    css = _read("css/unified_code_home.css")
    assert ".tc-home:hover .tc-home-arrow" in css  # arrows show on hover


def test_a_slide_never_shows_a_number_it_does_not_have():
    source = _read("js/unified_code_home.js")
    assert "No usage recorded yet." in source  # no runs have recorded tokens: say so, do not draw an empty graph
    assert "Reading your tasks." in source  # an empty list while the server still reads it is "not yet"
    assert "data-pending" in source or "dataset.pending" in source  # and the show passes over a slide that is waiting
    assert "/api/evolve/agent/performance" in source  # tokens and speed come from what each run recorded
    assert "not yet" in source  # a speed figure with no data says so instead of a zero


def test_outputs_explain_keep_and_revert_and_open_on_a_click():
    drawer = _read("js/unified_code_drawer.js")
    assert "tc-agents-explain" in drawer and "puts the file back as it was before this task" in drawer
    assert 'class="tc-agents-path" data-dash-open=' in drawer
