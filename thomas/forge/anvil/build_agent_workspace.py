"""Private current-content snapshots and guarded one-file Build integration."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import forge_code_manifest as manifest

_BOOKKEEPING = ".thomas/evolve/agent/team"
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE)


def relative_file(root: Path, raw: str) -> str:
    """Only a plain relative project file, never a link, device or runtime path."""
    text = str(raw).replace("\\", "/")
    parts = text.split("/")
    if not text or any(
        not part
        or part in {".", ".."}
        or part.rstrip(". ") != part
        or re.search(r'[<>:"|?*]', part)
        or _RESERVED.match(part)
        or part.casefold() in manifest._SKIP_DIRS
        for part in parts
    ):
        raise ValueError("builder path must name one relative project file outside runtime/dependency folders")
    target = root / text
    if target.resolve() != target or not target.resolve().is_relative_to(root):
        raise ValueError("builder path cannot cross a link or leave the project")
    if target.exists() and not target.is_file():
        raise ValueError("builder path must be a file")
    if target.exists() and target.stat().st_nlink > 1:
        raise ValueError("builder path cannot be a hard-linked file")
    return text


def fingerprint(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}:{len(data)}"


def current_fingerprint(root: Path, path: str) -> str | None:
    relative_file(root, path)
    target = root / path
    return fingerprint(target.read_bytes()) if target.exists() else None


@dataclass
class BuildWorkspace:
    project: Path
    root: Path
    path: str
    base: dict[str, str]
    receipt: dict[str, Any]

    @classmethod
    def create(
        cls, project: Path, child_id: str, path: str, *, context_files: list[str] | None = None
    ) -> BuildWorkspace:
        project = project.resolve()
        path = relative_file(project, path)
        if not re.fullmatch(r"child_[a-f0-9]{12}", child_id):
            raise ValueError("invalid internal child identity")

        def snapshot_input():
            if context_files is None:
                return manifest.snapshot(project, max_files=2000, max_total_bytes=64 * 1024 * 1024)
            if not isinstance(context_files, list) or len(context_files) > 100:
                raise ValueError("context_files must contain at most 100 exact files")
            selected = {path}
            for name in context_files:
                if not isinstance(name, str):
                    raise ValueError("context_files must contain exact relative file names")
                relative = relative_file(project, name)
                if not (project / relative).is_file():
                    raise ValueError(f"context file does not exist: {name}")
                selected.add(relative)
            snapshot = {manifest.MARKER: "1"}
            total = 0
            for relative in sorted(selected):
                name = Path(relative).name.casefold()
                if (
                    name == ".env"
                    or name.startswith(".env.")
                    or name in {"credentials.json", "token.json", "secrets.json"}
                ):
                    raise ValueError("Secret files cannot be helper context")
                target = project / relative
                if not target.exists() and relative == path:
                    continue
                total += target.stat().st_size
                if total > 64 * 1024 * 1024:
                    raise manifest.ManifestTooLarge("selected helper context exceeds 64 MiB")
                snapshot[relative] = fingerprint(target.read_bytes())
            return snapshot

        base = snapshot_input()
        folder = project / _BOOKKEEPING / child_id
        if folder.resolve() != folder:
            raise ValueError("team artifact directory cannot cross a link")
        root = folder / "workspace"
        root.mkdir(parents=True, exist_ok=False)
        item = cls(project, root, path, base, {"child_id": child_id, "path": path, "state": "snapshotting"})
        item.receipt["context_files"] = (
            sorted(p for p in base if p != manifest.MARKER) if context_files is not None else None
        )
        item.receipt["snapshot_kind"] = "selected_files" if context_files is not None else "whole_project"
        item.record("snapshotting")
        try:
            for relative, expected in base.items():
                if relative == manifest.MARKER:
                    continue
                data = (project / relative).read_bytes()
                if fingerprint(data) != expected:
                    raise ValueError(f"project changed while creating the child snapshot: {relative}")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if snapshot_input() != base:
                raise ValueError("project changed while creating the child snapshot; retry from current files")
        except (OSError, ValueError, RuntimeError) as exc:
            item.record("failed", reason=str(exc))
            raise
        item.receipt["base_sha256"] = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()
        item.receipt["base_file"] = base.get(path)
        item.record("building")
        return item

    def record(self, state: str, **detail: Any) -> None:
        self.receipt.update(state=state, **detail)
        target = self.root.parent / "receipt.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.receipt, indent=2), encoding="utf-8")
        temporary.replace(target)

    def candidate(self, *, max_size: int = 5_000_000) -> str:
        """Reject collateral changes before handing any text to the parent writer."""
        after = manifest.snapshot(self.root, max_files=2000, max_total_bytes=64 * 1024 * 1024)
        changed = sorted(path for path in self.base.keys() | after.keys() if self.base.get(path) != after.get(path))
        if changed != [self.path]:
            raise ValueError(f"builder must change exactly its assigned file {self.path}; changed: {changed}")
        relative_file(self.root, self.path)
        target = self.root / self.path
        if not target.is_file():
            raise ValueError("builders cannot delete their assigned file")
        if target.stat().st_size > max_size:
            raise ValueError("assigned output exceeds the parent file-size limit")
        content = target.read_text(encoding="utf-8")
        if "\0" in content:
            raise ValueError("assigned output must be UTF-8 text without NUL bytes")
        self.record("candidate", candidate_file=after[self.path])
        return content

    def check_base(self) -> None:
        expected = self.base.get(self.path)
        target = self.project / self.path
        relative_file(self.project, self.path)
        size = target.stat().st_size if target.exists() else None
        expected_size = int(expected.rsplit(":", 1)[1]) if expected else None
        if size != expected_size or current_fingerprint(self.project, self.path) != expected:
            raise ValueError(
                f"integration conflict: {self.path} changed since this helper started; retry from current files"
            )


@asynccontextmanager
async def integration_guard(project: Path, deadline: float):
    """Cross-process lock, fail closed, with cancellation/deadline while waiting."""
    path = project / _BOOKKEEPING / "integration.lock"
    if path.resolve() != path:
        raise ValueError("integration lock cannot cross a link")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Build pass deadline reached before integration")
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                await asyncio.sleep(min(0.05, max(0.001, deadline - asyncio.get_running_loop().time())))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
