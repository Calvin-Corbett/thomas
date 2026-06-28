"""Contract tests for Forge Code robustness + perf polish (047_evolve_agent_chat.js).

These guard the two behaviours added in the robustness pass:

1. Build errors render a PLAIN-LANGUAGE cause with a working Retry, and a
   mid-stream SSE drop attempts a BOUNDED reconnect instead of dying silently.
2. A huge diff is windowed (virtualized) to a bounded DOM node count, while
   small diffs render every row exactly as before.

The runtime JS lives inside one IIFE and is not importable, so -- like the other
`tests/test_web_*` source-contract tests -- we assert against the concatenated
runtime source and the diff-window MATH (mirrored in Python) rather than driving
a browser. The operator runs `node --check` + a live browser pass on top.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
EVOLUTION_CSS = ROOT / "thomas" / "server" / "web" / "css" / "evolution.css"
CHAT_JS = RUNTIME_DIR / "047_evolve_agent_chat.js"


def _read_all_runtime_js() -> str:
    parts = sorted(RUNTIME_DIR.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


def _chat_js() -> str:
    return CHAT_JS.read_text(encoding="utf-8")


def _int_const(source: str, name: str) -> int:
    m = re.search(r"\bvar\s+" + re.escape(name) + r"\s*=\s*(\d+)", source)
    assert m, f"expected numeric const {name} in source"
    return int(m.group(1))


# -- 1. build error: plain-language cause + retry-capable descriptor --------


def test_build_error_descriptor_is_retry_capable() -> None:
    js = _chat_js()
    # A plain-language cause classifier maps raw provider/git/permission strings
    # to an actionable sentence, and the descriptor carries the raw detail + a
    # retryable flag derived from a stored last message.
    assert "function plainCause(" in js
    assert "function buildErrorDescriptor(" in js
    assert "retryable: !!lastSentMessage" in js
    # The descriptor keeps the raw detail (never discards it) alongside the cause.
    assert "cause: plainCause(detail, rc)" in js
    assert "detail: String(detail == null ? '' : detail)" in js
    # An error EVENT yields the retry-capable card: appendError delegates to the
    # rich build-error renderer, which renders a Retry that re-sends the turn.
    assert "function appendError(text) { return appendBuildError(text, null); }" in js
    assert "function retryLastTurn(" in js
    assert "void sendToBuild(msg)" in js  # retry re-sends the same turn
    assert "lastSentMessage = msg;" in js  # the turn is remembered at send time


def test_build_error_has_plain_cause_and_retry_dom() -> None:
    js = _chat_js()
    assert "fc-error-cause" in js  # plain-language cause line leads the card
    assert "fc-error-detail" in js  # raw detail kept available but secondary
    assert "fc-error-retry" in js  # a Retry action
    # A non-zero build exit renders the actionable error (with Retry), not a bare
    # dead-end pill.
    assert "appendBuildError('The build process exited with code ' + rc + '.', rc)" in js


def test_build_error_styles_present() -> None:
    css = EVOLUTION_CSS.read_text(encoding="utf-8")
    assert ".fc-error.is-build" in css
    assert ".fc-error-cause" in css
    assert ".fc-error-retry" in css


# -- 2. bounded SSE reconnect (no silent death, no spam) --------------------


def test_sse_reconnect_is_bounded_and_data_governed() -> None:
    js = _chat_js()
    # A bounded budget of reconnect attempts with short backoff.
    assert _int_const(js, "MAX_RECONNECT") == 3
    assert "function connectStream(" in js  # reused by the reconnect path
    assert "reconnectAttempts++" in js
    assert "if (reconnectAttempts < MAX_RECONNECT)" in js
    assert "setTimeout(" in js and "connectStream();" in js  # backoff -> reconnect
    # The budget resets only when a reconnected stream actually DELIVERS data
    # (governed by received frames, not connection opens) -> a dead endpoint that
    # accepts-then-closes cannot spam.
    assert "if (reconnectAttempts) { clearReconnect(); setStatus('working', true); }" in js
    # A transient "Reconnecting…" surface, not a silent death.
    assert "Reconnecting…" in js
    assert "function showReconnecting(" in js
    # Only AFTER the budget is exhausted do we fall back to an honest error.
    assert "could not be restored after ' + MAX_RECONNECT" in js
    # The reopened stream replays from the top, so the in-progress turn is reset
    # to re-render exactly once (no duplication).
    assert "function resetCurrentAgentTurn(" in js
    assert "resetCurrentAgentTurn(); // replay re-renders this turn exactly once" in js


def test_clean_done_is_not_treated_as_a_drop() -> None:
    js = _chat_js()
    # onerror after a clean done (es === null) must NOT trigger a reconnect.
    assert "if (!es) return;" in js
    # A manual Stop cancels any pending reconnect.
    assert "clearReconnect(); // a manual Stop cancels any pending reconnect attempt" in js


def test_reconnect_styles_present() -> None:
    css = EVOLUTION_CSS.read_text(encoding="utf-8")
    assert ".fc-reconnect" in css
    assert ".fc-reconnect-ic" in css


# -- 3. diff virtualization: bounded node count for huge diffs --------------


def test_small_diff_renders_every_row_unchanged() -> None:
    js = _chat_js()
    # Below the threshold the body is filled with every row exactly as before.
    assert "function renderDiffRows(" in js
    assert "if (rows.length <= DIFF_VIRTUALIZE_THRESHOLD) {" in js
    assert "for (var i = 0; i < rows.length; i++) html += rowHtml(rows[i], lang);" in js
    assert "body.innerHTML = html;" in js


def test_huge_diff_renders_a_bounded_node_count() -> None:
    js = _chat_js()
    assert "function virtualizeDiffBody(" in js
    assert "body.classList.add('fc-diff-virt');" in js
    # Copy / Keep / Revert act on the FULL diff regardless of what is rendered:
    # they never read the windowed rows.
    assert "navigator.clipboard.writeText(String(diff || ''))" in js

    # Mirror the JS windowing math in Python and prove the realized node count for
    # a 5000-row diff is bounded (a tiny constant), not ~5000.
    threshold = _int_const(js, "DIFF_VIRTUALIZE_THRESHOLD")
    buffer = _int_const(js, "DIFF_WINDOW_BUFFER")
    row_fallback_h = _int_const(js, "DIFF_ROW_FALLBACK_H")

    total_rows = 5000
    assert total_rows > threshold  # this diff IS virtualized

    view_h = 360  # .fc-diff-body max-height in CSS
    scroll_top = 2000  # somewhere mid-scroll
    start = max(0, math.floor(scroll_top / row_fallback_h) - buffer)
    end = min(total_rows, math.ceil((scroll_top + view_h) / row_fallback_h) + buffer)
    realized = end - start

    visible = math.ceil(view_h / row_fallback_h)
    # window == visible rows + a buffer on each side, and far, far below 5000.
    assert realized <= visible + 2 * buffer + 2
    assert realized < 120
    assert realized < total_rows / 10


def test_virtualization_styles_present() -> None:
    css = EVOLUTION_CSS.read_text(encoding="utf-8")
    assert ".fc-diff-body.fc-diff-virt" in css
    assert ".fc-diff-sizer" in css
    assert ".fc-diff-window" in css


def test_runtime_concatenation_includes_the_chat_module() -> None:
    # Guard that the module is actually part of the shipped runtime bundle.
    all_js = _read_all_runtime_js()
    assert "function virtualizeDiffBody(" in all_js
    assert "function buildErrorDescriptor(" in all_js
