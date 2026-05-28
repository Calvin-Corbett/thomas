from __future__ import annotations

import asyncio
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


def _write_signed_flag(
    sandbox: Path,
    *,
    key: bytes,
    issued_at: str = "2026-05-27T12:00:00Z",
    issued_by: str = "calvin",
    repo: str | None = None,
    version: int = 1,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a flag that the validator will accept."""
    if repo is None:
        repo = str(sandbox.resolve())
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
