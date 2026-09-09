"""SWEEP: result artifact surfacing (can the user OPEN what was made?).

Drives the REAL deliverable resolver
(`thomas.server.routes.deliverable_aiohttp.deliverable_url`) against real temp
workspaces of different file types, plus the proof path in task_bot_runtime.

KEY FINDING THIS SWEEP PROVES: only *.html deliverables ever get a clickable
URL. A worker that creates report.pdf / data.csv / hello.txt / chart.png gives
the user a bare text path and no way to open/reveal/download it. And the normal
completion path never populates proof.artifacts, so there is no structured
artifact list to render at all.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Recorder

from thomas.server.routes import deliverable_aiohttp as dl

A = "result-artifacts"

# (extension, filename, should_be_openable_in_a_good_system)
FILE_TYPES = [
    ("html", "index.html", True),
    ("txt", "hello.txt", True),
    ("pdf", "report.pdf", True),
    ("csv", "data.csv", True),
    ("png", "chart.png", True),
    ("md", "notes.md", True),
    ("docx", "memo.docx", True),
    ("xlsx", "budget.xlsx", True),
]


def run() -> Recorder:
    rec = Recorder("artifacts")
    base = dl._WORKSPACES_BASE
    base.mkdir(parents=True, exist_ok=True)
    created_dirs: list[Path] = []
    try:
        for ext, fname, should_open in FILE_TYPES:
            exec_id = f"strstest-{ext}"
            safe = dl._safe_id(exec_id)
            wd = base / safe
            wd.mkdir(parents=True, exist_ok=True)
            created_dirs.append(wd)
            (wd / fname).write_text("x", encoding="utf-8")

            url = dl.deliverable_url(exec_id)
            openable = bool(url)
            # Frontier expectation: ANY produced file is openable/revealable.
            passed = openable == should_open
            rec.add(
                case=f"deliverable .{ext} ({fname}) is openable from chat",
                dimension=A,
                expected="every produced file should offer open/reveal/download",
                actual=(f"url={url!r}" if openable else "no clickable affordance (bare text path only)"),
                passed=passed,
                severity="high" if (should_open and not openable) else "low",
                evidence="deliverable_entry() scans *.html only (deliverable_aiohttp.py:47)",
            )

        # The completion path must produce a STRUCTURED artifact list ({path,type,
        # actions}) and attach it to the execution proof — this is the real mechanism
        # the worker finalize now uses (_artifacts_from_created -> attach_proof ->
        # complete_execution with evidence). Exercise that exact chain.
        with tempfile.TemporaryDirectory() as td:
            from thomas.core import task_bot_runtime as tbr
            from thomas.server.chat_delegation_deliverable import _artifacts_from_created

            root = Path(td)
            created = ["report.pdf", "data/notes.txt"]
            arts = _artifacts_from_created(created)
            ex = tbr.create_execution(session_id="s", summary="make files", repo_root=root)
            tbr.attach_proof(ex["execution_id"], artifacts=arts, status="verified", repo_root=root)
            tbr.complete_execution(
                ex["execution_id"], summary="Created report.pdf, data/notes.txt", repo_root=root, verified_success=True
            )
            r = tbr.get_execution(ex["execution_id"], root) or {}
            artifacts = (r.get("proof") or {}).get("artifacts") or []
            well_formed = bool(artifacts) and all(("path" in a and "type" in a and "actions" in a) for a in artifacts)
            rec.add(
                case="completion path populates a structured artifact list",
                dimension=A,
                expected="proof.artifacts carries {path,type,actions} for the UI to render open/download",
                actual=f"proof.artifacts={artifacts!r} (well_formed={well_formed}, state={r.get('state')!r})",
                passed=well_formed and r.get("state") == "completed",
                severity="high",
                evidence="worker finalize now: _artifacts_from_created -> attach_proof -> complete_execution(verified_success)",
            )
    finally:
        for d in created_dirs:
            try:
                for p in d.iterdir():
                    p.unlink()
                d.rmdir()
            except OSError:
                pass
    return rec


if __name__ == "__main__":
    run().console()
