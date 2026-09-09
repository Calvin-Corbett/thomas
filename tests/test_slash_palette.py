"""The "/" command palette only offers what the page can do (frontier parity: Claude Code, Codex, ChatGPT)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "thomas" / "server" / "web" / "js" / "slash_palette.js"
DRIVER = ROOT / "tests" / "web_node" / "slash_palette.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_palette_lists_only_commands_whose_control_exists_and_resolves_actions() -> None:
    out = subprocess.run(["node", str(DRIVER), str(MODULE)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["all_present"] == ["new", "model", "export", "retry", "fast", "help"]
    assert report["narrowed"] == ["model"]
    assert report["none"] == []
    assert report["hidden_without_control"] == ["new", "help"]
    assert report["export_url"] == "/api/chats/chat_abc123/export?format=md&title=R4%20chart"
    assert report["click_kind"] == "click"
    assert report["missing_resolves_null"] is True
    assert report["retry_kind"] == "retry"
    assert report["retry_hidden_without_edit"] == []
    # /help needs no control on the page and lists every command with its hint (frontier parity: Claude Code /help)
    assert report["help_always_present"] == ["help"]
    assert report["help_kind"] == "help"
    # a name prefix outranks a label substring: "/he" + Enter must run help, not "Regenerate the last reply"
    assert report["prefix_first"][0] == "help"
    listed = report["help_lists_every_command"]
    assert listed[0].startswith("new: ") and any(item.startswith("fast: ") for item in listed) and listed[-1].startswith("help: ")
