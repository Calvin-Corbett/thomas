"""The running build must be able to say which build it is."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from thomas.core import build_info as build_info_module
from thomas.core.build_info import build_info, build_label

WEB = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web"
CHAT_HTML = WEB / "chat.html"
# The badge's style block moved verbatim out of chat.html's inline <style> into
# css/chat_shell.css when the page was cut back under its line ceiling (commit
# 248c0d93, "without behavior change" -- the rules are byte-identical). The
# markup still lives in chat.html. Both files are read for the STYLE rules, so
# the guard survives the block moving back or being split across the two: a
# check pointed at one file alone stopped seeing the rules it was written to
# protect and would have passed just as happily if they had been deleted.
CHAT_SHELL_CSS = WEB / "css" / "chat_shell.css"
BADGE_STYLE_SOURCES = (CHAT_HTML, CHAT_SHELL_CSS)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    build_info.cache_clear()
    yield
    build_info.cache_clear()


def test_build_info_names_the_commit_not_just_the_version() -> None:
    """A dozen worktrees of this repo can be checked out at once and report the
    same version string, so the version alone cannot answer "which Thomas is
    this". The commit is the part that actually tells two instances apart."""
    info = build_info()

    assert info["version"]
    assert re.fullmatch(r"[0-9a-f]{8}", str(info["commit"])), info["commit"]
    assert info["root"]


def test_identity_survives_a_missing_git() -> None:
    """An installed copy has no repository. It still knows its version, and
    reporting that must never raise -- health depends on this call."""

    def no_git(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("git is not installed")

    original = subprocess.run
    subprocess.run = no_git  # type: ignore[assignment]
    try:
        info = build_info()
    finally:
        subprocess.run = original  # type: ignore[assignment]

    assert info["version"]
    assert info["commit"] == ""
    assert info["branch"] == ""
    assert info["dirty"] is False


def test_identity_survives_a_git_that_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identity is a display nicety. It must never be why the server is slow to
    answer that it is alive."""

    def timed_out(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="git", timeout=2.0)

    monkeypatch.setattr(build_info_module.subprocess, "run", timed_out)
    info = build_info()

    assert info["version"]
    assert info["commit"] == ""


def test_build_info_is_resolved_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boot-time identity cannot change while the process runs, and no health
    check should be paying for a subprocess."""
    calls = {"n": 0}
    original = build_info_module.subprocess.run

    def counted(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(build_info_module.subprocess, "run", counted)
    build_info()
    after_first = calls["n"]
    for _ in range(5):
        build_info()

    assert after_first > 0
    assert calls["n"] == after_first


def test_build_label_is_comparable_at_a_glance() -> None:
    label = build_label()

    assert label.startswith("v")
    assert build_info()["commit"] in label


def test_the_badge_is_not_styled_inline() -> None:
    """The state styling has to be able to win the cascade.

    Styling the base state with a `style` attribute silently killed both the
    hover state and the uncommitted-tree state: an inline `color` outranks any
    stylesheet rule without !important, so the attribute flipped and nothing
    changed colour. Measured in the browser -- data-dirty was set while the text
    stayed muted.
    """
    markup = CHAT_HTML.read_text(encoding="utf-8")
    styles = "\n".join(path.read_text(encoding="utf-8") for path in BADGE_STYLE_SOURCES)
    badge = re.search(r"<button id=\"tc-build-badge\"[^>]*>", markup)

    assert badge, "the build badge is missing from the chat UI"
    assert "style=" not in badge.group(0), "inline style would outrank the state rules"
    assert '#tc-build-badge[data-dirty="1"]' in styles
    assert "#tc-build-badge:hover" in styles


def test_the_badge_reports_the_commit_and_the_port() -> None:
    """The port is how someone refers to an instance ("I'm on 8899"); the commit
    is what makes two instances on the same version distinguishable."""
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "mountBuildBadge" in text
    assert "location.port" in text
    assert "build.commit" in text
    assert "uncommitted" in text
