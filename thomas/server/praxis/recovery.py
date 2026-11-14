"""Durable child checkpoints for resuming an interrupted Praxis Build run.

The journal records the admitted plan before execution and checkpoints each
state transition. A recovered channel keeps completed receipts and starts only
children whose last durable state was nonterminal.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

TERMINAL = frozenset({"completed", "failed", "stopped", "interrupted"})


class PraxisRunJournal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "run_id TEXT PRIMARY KEY, instructions TEXT NOT NULL, "
                "launch_context TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL)"
            )
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            if "launch_context" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN launch_context TEXT NOT NULL DEFAULT '{}'")
            db.execute(
                "CREATE TABLE IF NOT EXISTS children ("
                "run_id TEXT NOT NULL, agent_id TEXT NOT NULL, plan_id TEXT NOT NULL, "
                "kind TEXT NOT NULL, title TEXT NOT NULL, brief TEXT NOT NULL, "
                "dependencies TEXT NOT NULL, model_choice TEXT NOT NULL DEFAULT '{}', "
                "execution_origin TEXT NOT NULL DEFAULT 'server', "
                "path TEXT NOT NULL DEFAULT '', "
                "state TEXT NOT NULL, model_used TEXT, "
                "attempts INTEGER NOT NULL DEFAULT 0, events TEXT NOT NULL, "
                "resume_at REAL, quota_credential TEXT, quota_reason TEXT, "
                "updated_at REAL NOT NULL, PRIMARY KEY (run_id, agent_id), "
                "FOREIGN KEY (run_id) REFERENCES runs(run_id))"
            )
            existing = {row[1] for row in db.execute("PRAGMA table_info(children)")}
            for name, sql_type in (
                ("model_choice", "TEXT NOT NULL DEFAULT '{}'"),
                ("execution_origin", "TEXT NOT NULL DEFAULT 'server'"),
                ("path", "TEXT NOT NULL DEFAULT ''"),
                ("resume_at", "REAL"),
                ("quota_credential", "TEXT"),
                ("quota_reason", "TEXT"),
            ):
                if name not in existing:
                    db.execute(f"ALTER TABLE children ADD COLUMN {name} {sql_type}")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def record_launch(self, run_id: str, context: dict[str, str]) -> None:
        """Freeze the non-secret runner identity needed after server restart."""
        required = {
            "project_root",
            "family",
            "model_id",
            "reviewer_model",
            "dispatch_model",
            "praxis_reviewer_profile",
            "praxis_reviewer_model",
        }
        if (
            not run_id
            # "agent" arrived with the Agent choice (bc982119); refusing it failed every Build start.
            or not required <= set(context) <= required | {"conversation_id", "agent"}
            or not all(isinstance(value, str) for value in context.values())
        ):
            raise ValueError("invalid Praxis launch context")
        if context["family"] not in {"gpt", "claude"} or not Path(context["project_root"]).is_absolute():
            raise ValueError("invalid Praxis launch context")
        encoded = json.dumps(context, sort_keys=True)
        with self._connect() as db:
            prior = db.execute("SELECT launch_context FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if prior is not None and prior["launch_context"] not in {"{}", encoded}:
                raise ValueError("Praxis run launch context changed")
            db.execute(
                "INSERT INTO runs (run_id, instructions, launch_context, updated_at) VALUES (?, '', ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET launch_context=excluded.launch_context, updated_at=excluded.updated_at",
                (run_id, encoded, time.time()),
            )

    def admit(
        self,
        run_id: str,
        instructions: str,
        children: list[dict[str, Any]],
    ) -> None:
        """Commit a whole admitted plan before any child is scheduled."""
        if not run_id or not children:
            raise ValueError("run id and children are required")
        now = time.time()
        with self._connect() as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "INSERT INTO runs (run_id, instructions, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "instructions=excluded.instructions, updated_at=excluded.updated_at",
                (run_id, instructions, now),
            )
            for child in children:
                db.execute(
                    "INSERT INTO children (run_id, agent_id, plan_id, kind, title, brief, "
                    "dependencies, model_choice, execution_origin, path, state, model_used, attempts, events, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(run_id, agent_id) DO NOTHING",
                    (
                        run_id,
                        str(child["agent_id"]),
                        str(child["plan_id"]),
                        str(child["kind"]),
                        str(child["title"]),
                        str(child["brief"]),
                        json.dumps(child.get("dependencies") or []),
                        json.dumps(child.get("model_choice") or {}),
                        str(child.get("execution_origin") or "server"),
                        str(child.get("path") or ""),
                        "starting",
                        None,
                        0,
                        "[]",
                        now,
                    ),
                )

    def checkpoint(self, run_id: str, child: dict[str, Any]) -> None:
        """Save one child's complete state; never turn a terminal row active."""
        child_id = str(child["agent_id"])
        state = str(child["state"])
        if state not in {"starting", "running", "retrying", "quota_wait", *TERMINAL}:
            raise ValueError("invalid child state")
        with self._connect() as db:
            prior = db.execute(
                "SELECT state FROM children WHERE run_id=? AND agent_id=?",
                (run_id, child_id),
            ).fetchone()
            if prior is None:
                raise ValueError("child was not admitted")
            if prior["state"] in TERMINAL and state != prior["state"]:
                raise ValueError("terminal child cannot change state")
            db.execute(
                "UPDATE children SET state=?, model_used=?, attempts=?, events=?, "
                "resume_at=?, quota_credential=?, quota_reason=?, updated_at=? "
                "WHERE run_id=? AND agent_id=?",
                (
                    state,
                    child.get("model_used"),
                    int(child.get("attempts") or 0),
                    json.dumps(child.get("events") or []),
                    child.get("resume_at"),
                    child.get("quota_credential"),
                    child.get("quota_reason"),
                    time.time(),
                    run_id,
                    child_id,
                ),
            )
            db.execute("UPDATE runs SET updated_at=? WHERE run_id=?", (time.time(), run_id))

    def load(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                return None
            rows = db.execute("SELECT * FROM children WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        return {
            "run_id": run_id,
            "instructions": run["instructions"],
            "launch_context": json.loads(run["launch_context"]),
            "children": [
                {
                    "agent_id": row["agent_id"],
                    "plan_id": row["plan_id"],
                    "kind": row["kind"],
                    "title": row["title"],
                    "brief": row["brief"],
                    "dependencies": json.loads(row["dependencies"]),
                    "model_choice": json.loads(row["model_choice"]),
                    "execution_origin": row["execution_origin"],
                    "path": row["path"],
                    "state": row["state"],
                    "model_used": row["model_used"],
                    "attempts": row["attempts"],
                    "events": json.loads(row["events"]),
                    "resume_at": row["resume_at"],
                    "quota_credential": row["quota_credential"],
                    "quota_reason": row["quota_reason"],
                }
                for row in rows
            ],
        }

    def interrupted_runs(self) -> list[str]:
        """Find runs with children that need to be rescheduled after restart."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT DISTINCT run_id FROM children WHERE state IN "
                "('starting','running','retrying','quota_wait') ORDER BY run_id"
            ).fetchall()
        return [row["run_id"] for row in rows]


def recover_channel(journal: PraxisRunJournal, run_id: str, run_child: Any) -> Any:
    """Rebuild handles and resume nonterminal children under a fresh run token.

    This is called on the running event loop after the prior process has exited.
    The caller must attach the returned channel to the run registry and save
    checkpoints on subsequent transitions.
    """
    from thomas.server.praxis.run_channel import RunChannel

    saved = journal.load(run_id)
    if saved is None:
        raise ValueError("unknown Praxis run")
    project_root = saved["launch_context"].get("project_root")
    channel = RunChannel(
        run_id,
        run_child,
        instructions=saved["instructions"],
        journal=journal,
        project_root=Path(project_root) if project_root else None,
    )
    for child in saved["children"]:
        child_id = child["agent_id"]
        state = child["state"]
        channel._children[child_id] = {
            "agent_id": child_id,
            "plan_id": child["plan_id"],
            "title": child["title"],
            "kind": child["kind"],
            "dependencies": child["dependencies"],
            "model_choice": child["model_choice"],
            "execution_origin": child["execution_origin"],
            "path": child["path"],
            "state": state if state in {*TERMINAL, "quota_wait"} else "starting",
            "events": child["events"],
            "model_used": child["model_used"],
            "started_at": None,
            "ended_at": None,
            "activity_intervals": [],
            "attempt_started_at": None,
            "attempts": child["attempts"],
            "resume_at": child["resume_at"],
            "quota_credential": child["quota_credential"],
            "quota_reason": child["quota_reason"],
        }
    # Completion placeholders allow dependent children to await their original
    # handles. These tasks do not call a model or alter completed receipts.
    for child in saved["children"]:
        if child["execution_origin"] == "external_builder" and child["state"] not in TERMINAL:
            row = channel._children[child["agent_id"]]
            row["state"] = "interrupted"
            row["events"].append({"type": "error", "error": "builder process interrupted; rerun Build to resume"})
            journal.checkpoint(run_id, row)
        if channel._children[child["agent_id"]]["state"] in TERMINAL:
            channel._tasks[child["agent_id"]] = asyncio.create_task(asyncio.sleep(0))
    for child in saved["children"]:
        if channel._children[child["agent_id"]]["state"] in TERMINAL:
            continue
        child_id = child["agent_id"]
        channel._tasks[child_id] = asyncio.create_task(
            channel._run_after_dependencies(
                child_id,
                child["dependencies"],
                child["kind"],
                child["title"],
                child["brief"],
            ),
            name=f"praxis:{child_id}:recovered",
        )
    return channel
