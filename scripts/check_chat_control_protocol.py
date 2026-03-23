"""Enforce the conversation-driven UI control protocol.

This guard ensures chat-controlled settings stay generic (not one-off hacks):
- resolver exists and is wired in server chat flow
- server emits `ui_state_patch`
- web chat handles `ui_state_patch` and persists settings patches
- required protocol tests/docs exist
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHAT_CONTROLS = ROOT / "thomas" / "models" / "chat_controls.py"
SERVER_APP = ROOT / "thomas" / "server" / "app.py"
WEB_CHAT = ROOT / "thomas" / "server" / "web" / "js" / "chat.js"
WEB_APP = ROOT / "thomas" / "server" / "web" / "js" / "app.js"
WEB_STORE = ROOT / "thomas" / "server" / "web" / "js" / "store.js"

REQUIRED_FILES: Sequence[Path] = (
    ROOT / "docs" / "CHAT_CONTROL_PROTOCOL.md",
    ROOT / "tests" / "test_chat_controls.py",
    ROOT / "tests" / "test_server_chat_controls.py",
    ROOT / "tests" / "test_model_switching.py",
    ROOT / "tests" / "test_agent_loop_autonomy.py",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require_substrings(path: Path, needles: Iterable[str]) -> list[str]:
    if not path.exists():
        return [f"{path}: missing file"]
    text = _read(path)
    missing: list[str] = []
    for needle in needles:
        if needle not in text:
            missing.append(f"{path}: missing `{needle}`")
    return missing


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check chat control protocol wiring.")
    _ = parser.parse_args(argv)

    errors: list[str] = []

    errors.extend(
        _require_substrings(
            CHAT_CONTROLS,
            (
                "class UiControlResolution",
                "def resolve_ui_control_request(",
                "_BOOLEAN_SETTING_SPECS",
            ),
        )
    )
    errors.extend(
        _require_substrings(
            SERVER_APP,
            (
                "resolve_ui_control_request(",
                '"type": "ui_state_patch"',
            ),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_CHAT,
            (
                "function applyUiStatePatch(",
                "event.type === 'ui_state_patch'",
                "saveSetting(",
            ),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_APP,
            (
                "subscribe('mode', syncModeButtons);",
                "const autonomyToggle = document.getElementById('autonomyToggle');",
                "saveSetting('autonomyLevel', level);",
            ),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_STORE,
            ("autonomyLevel",),
        )
    )

    for req in REQUIRED_FILES:
        if not req.exists():
            errors.append(f"{req}: missing required protocol artifact")

    if errors:
        print("Chat control protocol check failed:")
        for line in errors:
            print(f"  - {line}")
        return 1

    print("Chat control protocol check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
