from __future__ import annotations

import asyncio
import datetime as dt
import hmac
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from thomas.tools.base import ToolResult
from thomas.tools.filesystem import _runtime_signing_payload


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """Sandbox root mimicking the parts of Thomas the gate examines."""
    (tmp_path / "thomas" / "core").mkdir(parents=True)
    (tmp_path / "thomas" / "tools").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "agent_safety.toml").write_text("# stub\n")
    (tmp_path / "src").mkdir()
    return tmp_path


def _flag(sandbox: Path) -> Path:
    return sandbox / "runtime" / ".runtime_protection_disabled"


def _key(sandbox: Path) -> Path:
    return sandbox / "runtime" / ".runtime_protection_key"


def _default_issued_at() -> str:
    """Now, because break-glass is a window.

    A signed flag stops disabling protection once it ages out of its window
    (scripts/forge/gates/_runtime_guard.py::_within_disable_window, added
    2026-09-08 after a real flag sat open for two days switching off fourteen
    gates). A fixed timestamp here would age past that window, and every caller
    asserting "a signed flag IS honoured" would then fail for the wrong reason.
    """
    return dt.datetime.now(dt.UTC).isoformat()


def _write_signed_flag(
    sandbox: Path,
    *,
    key: bytes,
    issued_at: str | None = None,
    issued_by: str = "calvin",
    repo: str | None = None,
    version: int = 1,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a flag that the validator will accept."""
    if repo is None:
        repo = str(sandbox.resolve())
    if issued_at is None:
        issued_at = _default_issued_at()
    sig = hmac.new(
        key,
        _runtime_signing_payload(version, issued_at, issued_by, repo),
        sha256,
    ).hexdigest()
    doc: dict[str, Any] = {
        "version": version,
        "issued_at": issued_at,
        "issued_by": issued_by,
        "repo": repo,
        "signature": sig,
    }
    if extra:
        doc.update(extra)
    _flag(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _flag(sandbox).write_text(json.dumps(doc), encoding="utf-8")


def _plant_key(sandbox: Path) -> bytes:
    key = bytes(range(32))
    _key(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _key(sandbox).write_text(key.hex() + "\n", encoding="utf-8")
    return key


def _run(tool, args: dict[str, Any]) -> ToolResult:
    return asyncio.run(tool.execute(args))
