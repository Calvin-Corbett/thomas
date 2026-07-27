"""Enforce Thomas's structured chat-control protocol.

Ordinary message text belongs to the frontier model. Runtime settings may change
only through typed UI/API fields or a structured model capability; the server must
not infer a control action from prompt wording.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHAT_REQUEST_SETUP = ROOT / "thomas" / "server" / "routes" / "chat_request_setup.py"
CHAT_V2 = ROOT / "thomas" / "server" / "routes" / "chat_v2.py"
CHAT_AIOHTTP = ROOT / "thomas" / "server" / "routes" / "chat_aiohttp.py"
CHAT_HANDLERS = ROOT / "thomas" / "server" / "routes" / "chat_aiohttp_handlers.py"
CHAT_V2_UI_CONTROL = ROOT / "thomas" / "server" / "routes" / "chat_v2_ui_control.py"
APP_CORE = ROOT / "thomas" / "server" / "app_core.py"
APP_MIDDLEWARE_HANDLERS = ROOT / "thomas" / "server" / "app_middleware_handlers.py"
WEB_INDEX = ROOT / "thomas" / "server" / "web" / "index.html"
WEB_LOADER = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_loader.js"
WEB_CHAT_REQUESTS = ROOT / "thomas" / "server" / "web" / "js" / "runtime" / "008_easy_setup_onboarding_06.js"

RETIRED_PROMPT_CLASSIFIERS: Sequence[Path] = (
    ROOT / "thomas" / "models" / "chat_controls.py",
    ROOT / "thomas" / "models" / "switching.py",
    ROOT / "thomas" / "server" / "chat_control_mode.py",
)

REQUIRED_FILES: Sequence[Path] = (
    ROOT / "docs" / "CHAT_CONTROL_PROTOCOL.md",
    ROOT / "tests" / "test_server_chat_controls.py",
    ROOT / "tests" / "test_server_batch_mode.py",
    ROOT / "tests" / "test_server_session_locking.py",
    ROOT / "tests" / "test_semantic_intent_ownership.py",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require_substrings(path: Path, needles: Iterable[str]) -> list[str]:
    if not path.exists():
        return [f"{path}: missing file"]
    text = _read(path)
    return [f"{path}: missing `{needle}`" for needle in needles if needle not in text]


def _forbid_substrings(path: Path, needles: Iterable[str]) -> list[str]:
    if not path.exists():
        return [f"{path}: missing file"]
    text = _read(path)
    return [f"{path}: forbidden `{needle}`" for needle in needles if needle in text]


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check structured chat-control wiring.")
    _ = parser.parse_args(argv)

    errors: list[str] = []
    errors.extend(
        _require_substrings(
            CHAT_REQUEST_SETUP,
            (
                'payload.get("model")',
                'payload.get("model_id")',
                '"autonomy_level" in payload',
                'payload.get("mode")',
            ),
        )
    )
    errors.extend(
        _require_substrings(
            CHAT_V2,
            (
                "_LEGACY_MODE_MIGRATIONS",
                'payload.get("mode")',
                'payload.get("message"',
            ),
        )
    )
    errors.extend(
        _forbid_substrings(
            CHAT_HANDLERS,
            (
                "resolve_ui_control_request",
                "handle_ui_control_chat",
                "control_req",
            ),
        )
    )
    errors.extend(
        _forbid_substrings(
            CHAT_AIOHTTP,
            (
                "control_req",
                "handle_ui_control_chat",
            ),
        )
    )
    errors.extend(
        _forbid_substrings(
            APP_CORE,
            (
                "resolve_ui_control_request",
                "handle_ui_control_chat",
            ),
        )
    )
    errors.extend(
        _forbid_substrings(
            CHAT_V2_UI_CONTROL,
            (
                "handle_ui_control_turn",
                "control_parser",
                '"type": "ui_state_patch"',
            ),
        )
    )
    errors.extend(
        _forbid_substrings(
            APP_MIDDLEWARE_HANDLERS,
            (
                "thomas.models.switching",
                "_resolve_natural_model_switch_request",
            ),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_INDEX,
            ('src="/static/js/app_runtime_loader.js',),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_LOADER,
            (
                "RUNTIME_SCRIPTS",
                "'008_easy_setup_onboarding_06.js'",
            ),
        )
    )
    errors.extend(
        _require_substrings(
            WEB_CHAT_REQUESTS,
            (
                "function buildChatRequestPayload(",
                "model_id:",
                "autonomy_level:",
            ),
        )
    )

    for classifier in RETIRED_PROMPT_CLASSIFIERS:
        if classifier.exists():
            errors.append(f"{classifier}: retired prompt classifier must stay deleted")

    for required in REQUIRED_FILES:
        if not required.exists():
            errors.append(f"{required}: missing required protocol artifact")

    if errors:
        print("Structured chat-control protocol check failed:")
        for line in errors:
            print(f"  - {line}")
        return 1

    print("Structured chat-control protocol check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
