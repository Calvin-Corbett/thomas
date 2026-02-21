from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import Approval, AuditEvent, Job, RetryPolicy

ISO = "%Y-%m-%dT%H:%M:%S.%f%z"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime(ISO)


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    try:
        return datetime.strptime(s, ISO)
    except Exception:
        # Accept ISO-8601 variants from older codepaths
        return datetime.fromisoformat(s)


class AutonomyStore:
    """SQLite persistence for the autonomy engine.

    Goals:
    - Migration-safe (schema_version + incremental migrations)
    - Windows-friendly (WAL mode, stdlib only)
    - Single-process queue semantics (Thomas typically runs as one server process)
    - Crash recovery: stale running jobs are re-queued when their lock expires
    - Optional tamper-evident audit chain (HMAC/SHA256)
    """

    def __init__(self, db_path: str, *, integrity_key: Optional[bytes] = None):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we BEGIN explicitly
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row

        self._integrity_key: Optional[bytes] = integrity_key
        self._setup_pragmas()
        self.migrate()

    def set_integrity_key(self, key: Optional[bytes]) -> None:
        self._integrity_key = key

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------
    # SQLite setup & migrations
    # ---------------------------
    def _setup_pragmas(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=30000;")
        cur.close()

    def migrate(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);")
            rows = cur.execute("SELECT version FROM schema_version;").fetchall()
            if not rows:
                cur.execute("INSERT INTO schema_version(version) VALUES (0);")
                version = 0
            else:
                version = int(rows[0]["version"])
                if len(rows) > 1:
                    cur.execute("DELETE FROM schema_version WHERE rowid NOT IN (SELECT rowid FROM schema_version LIMIT 1);")
            cur.close()

        migrations = [
            self._migrate_1,
            self._migrate_2,
            self._migrate_3,
            self._migrate_4,
        ]
        target = len(migrations)
        while version < target:
            migrations[version]()
            version += 1
            with self._lock:
                cur = self._conn.cursor()
                cur.execute("UPDATE schema_version SET version=?;", (version,))
                cur.close()

    def _ensure_column(self, *, table: str, column: str, ddl: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cols = [r["name"] for r in cur.execute(f"PRAGMA table_info({table});").fetchall()]
            if column not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")
            cur.close()

    def _migrate_1(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        next_run_at TEXT,
                        parent_id TEXT,
                        session_id TEXT,
                        payload_json TEXT NOT NULL,
                        result_json TEXT,
                        error_json TEXT,
                        schedule_json TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        retry_policy_json TEXT NOT NULL,
                        risk_class TEXT NOT NULL DEFAULT 'low',
                        requires_approval INTEGER NOT NULL DEFAULT 0,
                        approved INTEGER,
                        cancelled INTEGER NOT NULL DEFAULT 0,
                        locked_by TEXT,
                        lock_token TEXT,
                        locked_at TEXT,
                        lock_expires_at TEXT
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(status, next_run_at);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_id, updated_at);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id, updated_at);")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approvals (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        action_json TEXT NOT NULL,
                        risk_class TEXT NOT NULL,
                        status TEXT NOT NULL,
                        requested_at TEXT NOT NULL,
                        decided_at TEXT,
                        decided_by TEXT,
                        decision_reason TEXT,
                        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, requested_at);")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit (
                        id TEXT PRIMARY KEY,
                        job_id TEXT,
                        ts TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        detail_json TEXT NOT NULL,
                        prev_sig TEXT,
                        sig TEXT
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_job_ts ON audit(job_id, ts);")

                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise
            finally:
                cur.close()

    def _migrate_2(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS autonomy_messages (
                        id TEXT PRIMARY KEY,
                        session_id TEXT,
                        ts TEXT NOT NULL,
                        level TEXT NOT NULL,
                        text TEXT NOT NULL
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_autonomy_messages_ts ON autonomy_messages(ts);")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS briefings (
                        id TEXT PRIMARY KEY,
                        ts TEXT NOT NULL,
                        content_json TEXT NOT NULL
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_briefings_ts ON briefings(ts);")
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise
            finally:
                cur.close()

    def _migrate_3(self) -> None:
        # Older DBs may not have parent_id/session_id columns.
        self._ensure_column(table="jobs", column="parent_id", ddl="parent_id TEXT")
        self._ensure_column(table="jobs", column="session_id", ddl="session_id TEXT")
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_id, updated_at);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id, updated_at);")
            cur.close()

    def _migrate_4(self) -> None:
        # Older DBs may have audit without integrity columns.
        self._ensure_column(table="audit", column="prev_sig", ddl="prev_sig TEXT")
        self._ensure_column(table="audit", column="sig", ddl="sig TEXT")

    # ---------------------------
    # Job CRUD
    # ---------------------------
    def create_job(
        self,
        *,
        name: str,
        kind: str,
        payload: Dict[str, Any],
        schedule: Optional[Dict[str, Any]],
        next_run_at: Optional[datetime],
        risk_class: str = "low",
        requires_approval: bool = False,
        retry_policy: Optional[RetryPolicy] = None,
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Job:
        now = _utcnow()
        job_id = uuid.uuid4().hex
        rp = retry_policy or RetryPolicy()

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO jobs(
                    id,name,kind,status,created_at,updated_at,next_run_at,
                    parent_id,session_id,
                    payload_json,schedule_json,attempts,retry_policy_json,
                    risk_class,requires_approval,approved,cancelled
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
                """
                ,
                (
                    job_id,
                    name,
                    kind,
                    "queued",
                    _dt_to_str(now),
                    _dt_to_str(now),
                    _dt_to_str(next_run_at),
                    parent_id,
                    session_id,
                    json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False),
                    json.dumps(schedule, separators=(",", ":"), ensure_ascii=False) if schedule else None,
                    0,
                    json.dumps(asdict(rp), separators=(",", ":"), ensure_ascii=False),
                    risk_class,
                    1 if requires_approval else 0,
                    None,
                    0,
                ),
            )
            cur.close()

        self.add_audit(job_id, "job.created", "system", {"kind": kind, "name": name, "risk_class": risk_class})
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job:
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute("SELECT * FROM jobs WHERE id=?;", (job_id,)).fetchone()
            cur.close()
        if row is None:
            raise KeyError(job_id)
        return self._row_to_job(row)

    def list_jobs(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Job]:
        q = "SELECT * FROM jobs"
        args: List[Any] = []
        conds: List[str] = []
        if status:
            conds.append("status=?")
            args.append(status)
        if kind:
            conds.append("kind=?")
            args.append(kind)
        if parent_id:
            conds.append("parent_id=?")
            args.append(parent_id)
        if session_id:
            conds.append("session_id=?")
            args.append(session_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY updated_at DESC LIMIT ? OFFSET ?;"
        args.extend([int(limit), int(offset)])

        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(args)).fetchall()
            cur.close()
        return [self._row_to_job(r) for r in rows]

    def update_job_payload(self, job_id: str, payload: Dict[str, Any]) -> None:
        now = _utcnow()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE jobs SET payload_json=?, updated_at=? WHERE id=?;",
                (json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False), _dt_to_str(now), job_id),
            )
            cur.close()

    def cancel_job(self, job_id: str, *, actor: str = "user") -> None:
        now = _utcnow()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE jobs SET status='cancelled', cancelled=1, updated_at=? WHERE id=?;",
                (_dt_to_str(now), job_id),
            )
            cur.close()
        self.add_audit(job_id, "job.cancelled", actor, {})

    def set_job_next_run(self, job_id: str, next_run_at: Optional[datetime]) -> None:
        now = _utcnow()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE jobs SET next_run_at=?, updated_at=? WHERE id=?;",
                (_dt_to_str(next_run_at), _dt_to_str(now), job_id),
            )
            cur.close()

    def set_job_status(
        self,
        job_id: str,
        status: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        attempts: Optional[int] = None,
        approved: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        lock_clear: bool = True,
        next_run_at: Optional[datetime] = None,
    ) -> None:
        now = _utcnow()
        sets = ["status=?", "updated_at=?"]
        args: List[Any] = [status, _dt_to_str(now)]
        if result is not None:
            sets.append("result_json=?")
            args.append(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        if error is not None:
            sets.append("error_json=?")
            args.append(json.dumps(error, separators=(",", ":"), ensure_ascii=False))
        if attempts is not None:
            sets.append("attempts=?")
            args.append(int(attempts))
        if approved is not None:
            sets.append("approved=?")
            args.append(1 if approved else 0)
        if requires_approval is not None:
            sets.append("requires_approval=?")
            args.append(1 if requires_approval else 0)
        if next_run_at is not None:
            sets.append("next_run_at=?")
            args.append(_dt_to_str(next_run_at))
        if lock_clear:
            sets.extend(["locked_by=NULL", "lock_token=NULL", "locked_at=NULL", "lock_expires_at=NULL"])

        q = "UPDATE jobs SET " + ", ".join(sets) + " WHERE id=?;"
        args.append(job_id)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(q, tuple(args))
            cur.close()

    # ---------------------------
    # Claim / lock / recovery
    # ---------------------------
    def claim_due_jobs(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
        lock_ttl_s: float,
    ) -> List[Tuple[Job, str]]:
        """Claim due queued jobs and mark them running. Returns (job, lock_token)."""
        now_s = _dt_to_str(now) or _dt_to_str(_utcnow())
        expires = _dt_to_str((now if now.tzinfo else now.replace(tzinfo=timezone.utc)) + timedelta(seconds=lock_ttl_s))

        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                rows = cur.execute(
                    """
                    SELECT id FROM jobs
                    WHERE status='queued'
                      AND cancelled=0
                      AND (next_run_at IS NULL OR next_run_at<=?)
                      AND (lock_expires_at IS NULL OR lock_expires_at<=?)
                    ORDER BY next_run_at ASC, created_at ASC
                    LIMIT ?;
                    """
                    ,
                    (now_s, now_s, int(limit)),
                ).fetchall()

                claimed: List[Tuple[str, str]] = []
                for r in rows:
                    jid = r["id"]
                    token = uuid.uuid4().hex
                    cur.execute(
                        """
                        UPDATE jobs SET
                            locked_by=?,
                            lock_token=?,
                            locked_at=?,
                            lock_expires_at=?,
                            status='running',
                            updated_at=?
                        WHERE id=?
                          AND status='queued'
                          AND (lock_expires_at IS NULL OR lock_expires_at<=?);
                        """
                        ,
                        (worker_id, token, now_s, expires, now_s, jid, now_s),
                    )
                    if cur.rowcount == 1:
                        claimed.append((jid, token))
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise
            finally:
                cur.close()

        return [(self.get_job(jid), token) for jid, token in claimed]

    def reap_stale_running(self, *, now: datetime, limit: int = 200) -> int:
        """Re-queue jobs stuck in running state past their lock expiry."""
        now_s = _dt_to_str(now) or _dt_to_str(_utcnow())
        ids: List[str] = []
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            try:
                rows = cur.execute(
                    """
                    SELECT id FROM jobs
                    WHERE status='running'
                      AND cancelled=0
                      AND lock_expires_at IS NOT NULL
                      AND lock_expires_at<=?
                    ORDER BY lock_expires_at ASC
                    LIMIT ?;
                    """
                    ,
                    (now_s, int(limit)),
                ).fetchall()
                ids = [r["id"] for r in rows]
                for jid in ids:
                    cur.execute(
                        """
                        UPDATE jobs SET
                            status='queued',
                            locked_by=NULL,
                            lock_token=NULL,
                            locked_at=NULL,
                            lock_expires_at=NULL,
                            updated_at=?
                        WHERE id=?;
                        """
                        ,
                        (now_s, jid),
                    )
                cur.execute("COMMIT;")
            except Exception:
                cur.execute("ROLLBACK;")
                raise
            finally:
                cur.close()

        for jid in ids:
            self.add_audit(jid, "job.requeued_stale_lock", "system", {"at": now_s})
        return len(ids)

    # ---------------------------
    # Approvals
    # ---------------------------
    def create_approval(self, *, job_id: str, action: Dict[str, Any], risk_class: str) -> Approval:
        now = _utcnow()
        ap_id = uuid.uuid4().hex
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO approvals(id,job_id,action_json,risk_class,status,requested_at)
                VALUES (?,?,?,?,?,?);
                """
                ,
                (
                    ap_id,
                    job_id,
                    json.dumps(action, separators=(",", ":"), ensure_ascii=False),
                    risk_class,
                    "pending",
                    _dt_to_str(now),
                ),
            )
            cur.close()
        self.add_audit(job_id, "approval.requested", "system", {"approval_id": ap_id, "risk_class": risk_class})
        return self.get_approval(ap_id)

    def get_approval(self, approval_id: str) -> Approval:
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute("SELECT * FROM approvals WHERE id=?;", (approval_id,)).fetchone()
            cur.close()
        if row is None:
            raise KeyError(approval_id)
        return self._row_to_approval(row)

    def list_approvals(self, *, status: Optional[str] = None, limit: int = 200) -> List[Approval]:
        q = "SELECT * FROM approvals"
        args: List[Any] = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY requested_at DESC LIMIT ?;"
        args.append(int(limit))
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(args)).fetchall()
            cur.close()
        return [self._row_to_approval(r) for r in rows]

    def list_job_approvals(self, job_id: str, *, status: Optional[str] = None) -> List[Approval]:
        q = "SELECT * FROM approvals WHERE job_id=?"
        args: List[Any] = [job_id]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY requested_at DESC;"
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(args)).fetchall()
            cur.close()
        return [self._row_to_approval(r) for r in rows]

    def decide_approval(self, *, approval_id: str, approve: bool, actor: str, reason: Optional[str] = None) -> Approval:
        now = _utcnow()
        status = "approved" if approve else "denied"

        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute("SELECT status FROM approvals WHERE id=?;", (approval_id,)).fetchone()
            if row is None:
                cur.close()
                raise KeyError(approval_id)
            if row["status"] != "pending":
                cur.close()
                return self.get_approval(approval_id)

            cur.execute(
                """
                UPDATE approvals
                SET status=?, decided_at=?, decided_by=?, decision_reason=?
                WHERE id=? AND status='pending';
                """
                ,
                (status, _dt_to_str(now), actor, reason, approval_id),
            )
            cur.close()

        ap = self.get_approval(approval_id)
        self.add_audit(ap.job_id, "approval.decided", actor, {"approval_id": approval_id, "status": status, "reason": reason})
        return ap

    # ---------------------------
    # Audit (with optional integrity chain)
    # ---------------------------
    def _compute_sig(self, prev_sig: str, payload: str) -> str:
        if self._integrity_key:
            return hmac.new(self._integrity_key, (prev_sig + payload).encode("utf-8"), hashlib.sha256).hexdigest()
        return hashlib.sha256((prev_sig + payload).encode("utf-8")).hexdigest()

    def add_audit(self, job_id: Optional[str], event_type: str, actor: str, detail: Dict[str, Any]) -> None:
        now = _utcnow()
        ev_id = uuid.uuid4().hex
        ts = _dt_to_str(now) or now.isoformat()
        detail_json = json.dumps(detail or {}, separators=(",", ":"), ensure_ascii=False)

        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute("SELECT sig FROM audit WHERE sig IS NOT NULL ORDER BY ts DESC LIMIT 1;").fetchone()
            prev_sig = (row["sig"] if row else "") or ""
            sig_payload = f"{ts}|{event_type}|{actor}|{detail_json}"
            sig = self._compute_sig(prev_sig, sig_payload)
            cur.execute(
                """
                INSERT INTO audit(id,job_id,ts,event_type,actor,detail_json,prev_sig,sig)
                VALUES (?,?,?,?,?,?,?,?);
                """
                ,
                (ev_id, job_id, ts, event_type, actor, detail_json, prev_sig or None, sig),
            )
            cur.close()

    def list_audit(self, *, job_id: Optional[str] = None, limit: int = 400) -> List[AuditEvent]:
        q = "SELECT * FROM audit"
        args: List[Any] = []
        if job_id:
            q += " WHERE job_id=?"
            args.append(job_id)
        q += " ORDER BY ts DESC LIMIT ?;"
        args.append(int(limit))

        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(args)).fetchall()
            cur.close()
        out: List[AuditEvent] = []
        for r in rows:
            out.append(AuditEvent(
                id=r["id"],
                job_id=r["job_id"],
                ts=_str_to_dt(r["ts"]) or _utcnow(),
                event_type=r["event_type"],
                actor=r["actor"],
                detail=json.loads(r["detail_json"] or "{}"),
                prev_sig=r["prev_sig"],
                sig=r["sig"],
            ))
        return out

    # ---------------------------
    # Messages + briefings (optional UX layer)
    # ---------------------------
    def add_message(self, *, session_id: Optional[str], level: str, text: str) -> str:
        now = _utcnow()
        mid = uuid.uuid4().hex
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO autonomy_messages(id,session_id,ts,level,text) VALUES (?,?,?,?,?);",
                (mid, session_id, _dt_to_str(now), level, text),
            )
            cur.close()
        return mid

    def list_messages(self, *, limit: int = 200, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM autonomy_messages"
        args: List[Any] = []
        if session_id:
            q += " WHERE session_id=?"
            args.append(session_id)
        q += " ORDER BY ts DESC LIMIT ?;"
        args.append(int(limit))

        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(args)).fetchall()
            cur.close()
        return [{"id": r["id"], "session_id": r["session_id"], "ts": r["ts"], "level": r["level"], "text": r["text"]} for r in rows]

    def add_briefing(self, *, content: Dict[str, Any]) -> str:
        now = _utcnow()
        bid = uuid.uuid4().hex
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO briefings(id,ts,content_json) VALUES (?,?,?);",
                (bid, _dt_to_str(now), json.dumps(content or {}, separators=(",", ":"), ensure_ascii=False)),
            )
            cur.close()
        return bid

    def list_briefings(self, *, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute("SELECT * FROM briefings ORDER BY ts DESC LIMIT ?;", (int(limit),)).fetchall()
            cur.close()
        return [{"id": r["id"], "ts": r["ts"], "content": json.loads(r["content_json"] or "{}")} for r in rows]

    # ---------------------------
    # Row mappers
    # ---------------------------
    def _row_to_job(self, r: sqlite3.Row) -> Job:
        rp = json.loads(r["retry_policy_json"] or "{}")
        retry = RetryPolicy(
            max_attempts=int(rp.get("max_attempts", 5)),
            base_delay_s=float(rp.get("base_delay_s", 2.0)),
            max_delay_s=float(rp.get("max_delay_s", 300.0)),
            jitter=float(rp.get("jitter", 0.15)),
            backoff=float(rp.get("backoff", 2.0)),
        )
        return Job(
            id=r["id"],
            name=r["name"],
            kind=r["kind"],
            status=r["status"],
            created_at=_str_to_dt(r["created_at"]) or _utcnow(),
            updated_at=_str_to_dt(r["updated_at"]) or _utcnow(),
            next_run_at=_str_to_dt(r["next_run_at"]),
            parent_id=r["parent_id"],
            session_id=r["session_id"],
            payload=json.loads(r["payload_json"] or "{}"),
            result=json.loads(r["result_json"]) if r["result_json"] else None,
            error=json.loads(r["error_json"]) if r["error_json"] else None,
            schedule=json.loads(r["schedule_json"]) if r["schedule_json"] else None,
            attempts=int(r["attempts"] or 0),
            retry_policy=retry,
            risk_class=r["risk_class"] or "low",
            requires_approval=bool(int(r["requires_approval"] or 0)),
            approved=(None if r["approved"] is None else bool(int(r["approved"]))),
            cancelled=bool(int(r["cancelled"] or 0)),
        )

    def _row_to_approval(self, r: sqlite3.Row) -> Approval:
        return Approval(
            id=r["id"],
            job_id=r["job_id"],
            action=json.loads(r["action_json"] or "{}"),
            risk_class=r["risk_class"] or "low",
            status=r["status"],
            requested_at=_str_to_dt(r["requested_at"]) or _utcnow(),
            decided_at=_str_to_dt(r["decided_at"]),
            decided_by=r["decided_by"],
            decision_reason=r["decision_reason"],
        )
