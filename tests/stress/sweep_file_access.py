"""SWEEP: scalable file-access permission ladder (read_only -> workspace -> project
-> pc -> full), like Codex sandbox modes / Claude Code permission tiers.

Proves the ladder both ENABLES (higher levels can write to your PC) and CONSTRAINS
(lower levels can't; OS system dirs and Thomas's own code are protected at EVERY
level). Drives the REAL WriteFileTool + the real authorize_write model against
isolated temp dirs — no real files touched outside tempdirs.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from _harness import Recorder

from thomas.core.file_access import FULL, PC, PROJECT, READ_ONLY, WORKSPACE, authorize_write
from thomas.tools.filesystem import WriteFileTool

D = "file-access-ladder"


async def _write(level, target, *, workspace, project, home):
    tool = WriteFileTool(workspace, file_access=level, project_root=project, home_dir=home)
    res = await tool.execute({"path": str(target), "content": "hello"})
    return bool(res.ok), str(res.error or "")


def run() -> Recorder:
    rec = Recorder("file_access")

    with tempfile.TemporaryDirectory() as wd, tempfile.TemporaryDirectory() as hd, tempfile.TemporaryDirectory() as pd:
        workspace = Path(wd)
        home = Path(hd)
        project = Path(pd)
        desktop = home / "Desktop"
        desktop.mkdir()
        # a temp dir that is NOT under workspace/project/home (simulates "elsewhere on PC")
        with tempfile.TemporaryDirectory() as ed:
            elsewhere = Path(ed)

            # (case, level, target, should_write)
            cases = [
                ("read_only blocks workspace write", READ_ONLY, workspace / "a.txt", False),
                ("workspace allows workspace write", WORKSPACE, "note.txt", True),
                ("workspace blocks Desktop write", WORKSPACE, desktop / "hello.txt", False),
                ("project allows project write", PROJECT, project / "out.txt", True),
                ("project blocks Desktop write", PROJECT, desktop / "hello.txt", False),
                ("pc allows Desktop write", PC, desktop / "hello.txt", True),
                ("pc blocks elsewhere-on-disk write", PC, elsewhere / "x.txt", False),
                ("full allows elsewhere write", FULL, elsewhere / "x.txt", True),
            ]
            for name, level, target, should in cases:
                ok, err = asyncio.run(_write(level, target, workspace=workspace, project=project, home=home))
                rec.add(
                    case=name,
                    dimension=D,
                    expected=("write allowed" if should else "write refused"),
                    actual=(f"ok={ok}" + ("" if ok else f" ({err[:80]})")),
                    passed=(ok == should),
                    severity="high",
                    evidence=f"level={level}",
                )

            # System dir is denied even at FULL (model-level check; no real write attempted).
            sys_target = Path("C:/Windows/System32/evil.txt") if Path("C:/Windows").exists() else Path("/etc/evil.txt")
            allowed, reason = authorize_write(
                FULL, sys_target, workspace_root=workspace, project_root=project, home_dir=home
            )
            rec.add(
                case="full STILL blocks OS system dirs",
                dimension=D,
                expected="system dir never writable at any level",
                actual=f"allowed={allowed} ({reason[:80]})",
                passed=(not allowed),
                severity="critical",
                evidence="system deny-list enforced regardless of level",
            )

            # Thomas's own runtime code is protected even at FULL (write into project/thomas/tools).
            runtime_target = project / "thomas" / "tools" / "filesystem.py"
            ok, err = asyncio.run(_write(FULL, runtime_target, workspace=workspace, project=project, home=home))
            rec.add(
                case="full STILL blocks Thomas's own runtime code",
                dimension=D,
                expected="thomas/tools etc. never writable by the worker",
                actual=(f"ok={ok}" + ("" if ok else f" ({err[:70]})")),
                passed=(not ok),
                severity="critical",
                evidence="_is_protected_runtime_path enforced against the project root at every level",
            )
    return rec


if __name__ == "__main__":
    run().console()
