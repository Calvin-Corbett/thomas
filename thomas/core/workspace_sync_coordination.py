"""Active-folder coordination client used by WorkspaceSyncEngine."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)


def _truncate(text: str, limit: int = 800) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n... (truncated)"


def _normalize_rel_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    while text.startswith("/"):
        text = text[1:]
    return text


class WorkspaceSyncCoordinationClient:
    """Handles active-folder claim/release flows for workspace sync commits."""

    def __init__(
        self,
        *,
        repo_root: Path,
        enabled: bool,
        claim_ttl_s: int,
        note: str,
        timeout_s: float,
        script_path: Path,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._enabled = bool(enabled)
        self._claim_ttl_s = max(30, int(claim_ttl_s))
        self._note = str(note or "").strip() or "workspace sync auto-claim"
        self._timeout_s = max(1.0, float(timeout_s))
        self._script_path = Path(script_path).resolve()

    def enabled(self) -> bool:
        return bool(self._enabled and self._script_path.exists())

    def acquire(self, files: List[str]) -> Dict[str, Any]:
        if not self._enabled:
            return {"ok": True, "enabled": False, "reason": "disabled", "paths": []}
        if not self._script_path.exists():
            return {"ok": True, "enabled": False, "reason": "script_missing", "paths": []}

        claim_paths = self._coordination_paths(files)
        if not claim_paths:
            return {"ok": True, "enabled": True, "reason": "no_paths", "paths": []}

        cmd_args: List[str] = [
            "claim",
            "--ttl",
            str(self._claim_ttl_s),
            "--note",
            self._note,
        ]
        for path in claim_paths:
            cmd_args.extend(["--path", path])

        result = self._run(*cmd_args)
        payload = dict(result.get("payload") or {})
        if result.get("returncode") == 0 and bool(payload.get("ok", True)):
            return {
                "ok": True,
                "enabled": True,
                "reason": "claimed",
                "claim_id": str(payload.get("claim_id") or ""),
                "agent_id": str(payload.get("agent_id") or ""),
                "paths": claim_paths,
            }

        if str(payload.get("error") or "") == "folder_conflicts":
            conflicts = payload.get("conflicts") or []
            return {
                "ok": False,
                "enabled": True,
                "reason": "folder_conflicts",
                "paths": claim_paths,
                "conflicts": conflicts,
            }

        return {
            "ok": False,
            "enabled": True,
            "reason": "claim_failed",
            "paths": claim_paths,
            "stdout": _truncate(str(result.get("stdout") or "")),
            "stderr": _truncate(str(result.get("stderr") or "")),
        }

    def release(self, claim_id: str) -> None:
        claim = str(claim_id or "").strip()
        if not claim:
            return
        if not self._enabled or not self._script_path.exists():
            return

        result = self._run("release", "--claim-id", claim)
        if int(result.get("returncode") or 0) != 0:
            log.warning(
                "WorkspaceSyncEngine failed to release active-folder claim %s: %s",
                claim,
                _truncate(str(result.get("stderr") or result.get("stdout") or "")),
            )

    def _coordination_paths(self, files: List[str]) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for rel in files:
            normalized = _normalize_rel_path(rel)
            if not normalized:
                continue
            parent = Path(normalized).parent.as_posix()
            if parent in {"", "."}:
                claim_path = normalized
            else:
                claim_path = parent
            if claim_path in seen:
                continue
            seen.add(claim_path)
            out.append(claim_path)
        return sorted(out)

    def _run(self, *args: str) -> Dict[str, Any]:
        cmd = [os.environ.get("PYTHON", os.sys.executable), str(self._script_path), *[str(a) for a in args], "--json"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except Exception as exc:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "payload": {},
            }

        payload: Dict[str, Any] = {}
        stdout = str(proc.stdout or "").strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                payload = parsed

        return {
            "returncode": int(proc.returncode),
            "stdout": str(proc.stdout or ""),
            "stderr": str(proc.stderr or ""),
            "payload": payload,
        }
