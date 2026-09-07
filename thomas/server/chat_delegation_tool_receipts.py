"""Ordered tool evidence for completion, without retaining raw tool arguments."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def tool_action_id(name: str, arguments: Any, *, workspace: str | Path | None = None) -> str:
    """Identify the actual invocation; incomplete arguments cannot prove recovery."""
    if not name or not isinstance(arguments, dict):
        return ""
    # A corrected relative spelling can retry the same filesystem action after
    # an absolute-path refusal. Normalize only known file targets confined to
    # this worker's sandbox; preserve every other argument and tool identity.
    if workspace is not None and name in {"fs.read_file", "fs.write_file"}:
        raw_path = arguments.get("path")
        if isinstance(raw_path, str) and raw_path:
            try:
                root = Path(workspace).resolve()
                target = Path(raw_path)
                target = (target if target.is_absolute() else root / target).resolve()
                if target.is_relative_to(root):
                    arguments = {**arguments, "path": os.path.normcase(str(target))}
            except (OSError, ValueError, RuntimeError):
                # Unresolvable paths retain exact-argument identity. Never use
                # their basename to connect them with a different valid target.
                pass
    try:
        canonical = json.dumps([name, arguments], sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ToolReceiptLog:
    """A retry must start after the failed result and repeat the same invocation.

    Tool names alone cannot connect two actions. Missing IDs, starts, or action
    identities leave a failure unresolved, including legacy bridge receipts.
    """

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self._sequence = 0
        self._starts: dict[str, tuple[int, str]] = {}
        self._receipts: list[dict[str, Any]] = []
        for event in events or []:
            self.observe(event)

    def observe(self, event: dict[str, Any]) -> None:
        self._sequence += 1
        kind = str(event.get("type") or "")
        name = str(event.get("name") or "tool")
        call_id = str(event.get("call_id") or "")
        if kind == "tool_start" and call_id:
            self._starts[call_id] = (self._sequence, name)
        elif kind == "tool_output":
            start = self._starts.pop(call_id, None) if call_id else None
            self._receipts.append(
                {
                    "name": name,
                    "call_id": call_id,
                    "action_id": str(event.get("action_id") or ""),
                    "ok": event.get("ok") if isinstance(event.get("ok"), bool) else None,
                    "started": start[0] if start and start[1] == name else None,
                    "finished": self._sequence,
                }
            )

    def unrecovered_failures(self, failed_tools: list[str]) -> list[str]:
        """Return unresolved names; absent per-call failure evidence fails closed."""
        failures = [receipt for receipt in self._receipts if receipt["ok"] is False]
        names = dict.fromkeys([*failed_tools, *(receipt["name"] for receipt in failures)])
        unresolved: list[str] = []
        for name in names:
            calls = [receipt for receipt in failures if receipt["name"] == name]
            if not calls or any(not self._recovered(receipt) for receipt in calls):
                unresolved.append(name)
        return unresolved

    def _recovered(self, failure: dict[str, Any]) -> bool:
        if not failure["call_id"] or not failure["action_id"] or failure["started"] is None:
            return False
        return any(
            receipt["ok"]
            and receipt["call_id"]
            and receipt["call_id"] != failure["call_id"]
            and receipt["name"] == failure["name"]
            and receipt["action_id"] == failure["action_id"]
            and receipt["started"] is not None
            and receipt["started"] > failure["finished"]
            for receipt in self._receipts
        )
