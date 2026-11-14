"""Durable team receipts; an OS lease distinguishes active runs from abandoned ones."""

from __future__ import annotations

import errno
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .build_agent_workspace import _BOOKKEEPING, current_fingerprint, fingerprint


def _plain(path: Path) -> Path:
    if path.resolve() != path or (path.is_file() and path.stat().st_nlink > 1):
        raise ValueError("team receipt paths cannot cross links")
    return path


@contextmanager
def _lease(folder: Path):
    path = _plain(folder / "owner.lock")
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class TeamLedger:
    def __init__(self, folder: Path, data: dict[str, Any]) -> None:
        self.folder, self.data = folder, data

    @classmethod
    @contextmanager
    def start(cls, project: Path, jobs: list[dict[str, str]], model: str):
        team_id = "team_" + uuid.uuid4().hex
        folder = _plain(project / _BOOKKEEPING / team_id)
        folder.mkdir(parents=True, exist_ok=False)
        with _lease(folder) as acquired:
            if not acquired:
                raise RuntimeError("new team lease was unexpectedly occupied")
            ledger = cls(
                folder,
                {
                    "team_id": team_id,
                    "model": model,
                    "state": "running",
                    "children": [{**job, "state": "queued"} for job in jobs],
                },
            )
            ledger.save()
            yield ledger

    @classmethod
    @contextmanager
    def start_or_resume(cls, project: Path, jobs: list[dict[str, str]], model: str):
        """Continue the latest matching unfinished team under its OS lease."""
        root = _plain(project / _BOOKKEEPING)
        if root.exists():
            for folder in sorted(root.glob("team_*"), key=lambda path: path.stat().st_mtime, reverse=True):
                try:
                    _plain(folder)
                    target = _plain(folder / "team.json")
                    if not target.is_file() or target.stat().st_size > 2_000_000:
                        continue
                    with _lease(folder) as acquired:
                        if not acquired:
                            continue
                        data = json.loads(target.read_text(encoding="utf-8"))
                        children = data.get("children")
                        if data.get("model") != model or not isinstance(children, list):
                            continue
                        if [{key: child.get(key) for key in job} for child, job in zip(children, jobs)] != jobs:
                            continue
                        if len(children) != len(jobs) or data.get("state") not in {
                            "interrupted",
                            "failed",
                            "cancelled",
                        }:
                            continue
                        ledger = cls(folder, data)
                        for child in children:
                            expected = child.get("integrated_file")
                            if child.get("state") == "integrated":
                                receipt = child.get("receipt")
                                if not expected and isinstance(receipt, str):
                                    receipt_path = _plain(project / receipt)
                                    if (
                                        not Path(receipt).is_absolute()
                                        and receipt_path.is_relative_to(root)
                                        and receipt_path.is_file()
                                        and receipt_path.stat().st_size <= 100_000
                                    ):
                                        attempt = json.loads(receipt_path.read_text(encoding="utf-8"))
                                        if (
                                            attempt.get("state") == "integrated"
                                            and attempt.get("path") == child["path"]
                                        ):
                                            expected = attempt.get("integrated_file")
                                if not expected or current_fingerprint(project, child["path"]) != expected:
                                    raise ValueError(f"Previously integrated file changed: {child['path']}")
                                continue
                            receipt = child.get("receipt")
                            if isinstance(receipt, str):
                                receipt_path = _plain(project / receipt)
                                if (
                                    not Path(receipt).is_absolute()
                                    and receipt_path.is_relative_to(root)
                                    and receipt_path.is_file()
                                    and receipt_path.stat().st_size <= 100_000
                                ):
                                    attempt = json.loads(receipt_path.read_text(encoding="utf-8"))
                                    if attempt.get("path") == child["path"] and attempt.get("state") in {
                                        "candidate",
                                        "integrated",
                                        "failed",
                                        "cancelled",
                                    }:
                                        candidate = receipt_path.parent / "workspace" / child["path"]
                                        if candidate.is_file() and attempt.get("candidate_file") == fingerprint(
                                            candidate.read_bytes()
                                        ):
                                            target_file = project / child["path"]
                                            if target_file.is_file() and target_file.read_text(
                                                encoding="utf-8"
                                            ) == candidate.read_text(encoding="utf-8"):
                                                child.update(
                                                    state="integrated",
                                                    integrated_file=current_fingerprint(project, child["path"]),
                                                    error="",
                                                )
                                                continue
                            old_receipt = child.pop("receipt", None)
                            if old_receipt:
                                child.setdefault("prior_receipts", []).append(old_receipt)
                            child.pop("child_id", None)
                            child.update(state="queued", error="", attempts=int(child.get("attempts", 0)) + 1)
                        ledger.finish("running", resumed_at=datetime.now(timezone.utc).isoformat())
                        yield ledger
                        return
                except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
                    continue
        with cls.start(project, jobs, model) as ledger:
            yield ledger

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        target = _plain(self.folder / "team.json")
        temporary = _plain(self.folder / (uuid.uuid4().hex + ".tmp"))
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2)
        temporary.replace(target)

    def update(self, index: int, state: str, **details: Any) -> None:
        self.data["children"][index].update(state=state, **details)
        self.save()

    def finish(self, state: str, **details: Any) -> None:
        self.data.update(state=state, **details)
        self.save()

    def progress_snapshot(self) -> dict[str, int | str]:
        counts = {state: 0 for state in ("queued", "running", "integrated", "failed", "cancelled", "interrupted")}
        for child in self.data.get("children", []):
            state = child.get("state")
            if state in counts:
                counts[state] += 1
        return {"state": self.data.get("state", "running"), "total": len(self.data.get("children", [])), **counts}

    @classmethod
    def recover(cls, project: Path) -> list[str]:
        """Retain artifacts, never resume or apply an abandoned candidate."""
        root = _plain(project / _BOOKKEEPING)
        recovered = []
        if not root.exists():
            return recovered
        for folder in root.glob("team_*"):
            try:
                _plain(folder)
                target = _plain(folder / "team.json")
                if not target.is_file() or target.stat().st_size > 2_000_000:
                    continue
                with _lease(folder) as acquired:
                    if not acquired:
                        continue
                    data = json.loads(target.read_text(encoding="utf-8"))
                    if data.get("state") != "running":
                        continue
                    for child in data["children"]:
                        if child.get("state") in {"queued", "running"}:
                            child.update(
                                state="interrupted", error="Previous team owner exited; candidate was not resumed"
                            )
                    cls(folder, data).finish("interrupted")
                    recovered.append(str(data["team_id"]))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                # Damaged receipts stay available for inspection, never execution.
                continue
        return recovered
