"""Enforce the conversation-driven UI control protocol.

This guard ensures chat-controlled settings stay generic (not one-off hacks):
- resolver exists and is wired in server chat flow
- server emits `ui_state_patch`
- web chat handles `ui_state_patch` and persists settings patches
- required protocol tests/docs exist
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
CHAT_CONTROLS = ROOT / "thomas" / "models" / "chat_controls.py"
# Server-side wiring was split across modules during the rename arc:
# - resolve_ui_control_request lives in app_core.py
# - "type": "ui_state_patch" is emitted from chat_control_mode.py
SERVER_APP_CORE = ROOT / "thomas" / "server" / "app_core.py"
SERVER_CHAT_CONTROL_MODE = ROOT / "thomas" / "server" / "chat_control_mode.py"
# Frontend was consolidated into a single primary runtime module:
WEB_RUNTIME_PRIMARY = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_primary.mjs"

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
            SERVER_APP_CORE,
            ("resolve_ui_control_request",),
        )
    )
    errors.extend(
        _require_substrings(
            SERVER_CHAT_CONTROL_MODE,
            ('"type": "ui_state_patch"',),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_RUNTIME_PRIMARY,
            (
                "ui_state_patch",
                "autonomyLevel",
            ),
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
