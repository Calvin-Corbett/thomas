from __future__ import annotations

from typing import Any


def severity_route(*, score: float, reason: str) -> tuple[str, str]:
    s = float(max(0.0, min(1.0, score)))
    why = str(reason or "").lower()
    if s >= 0.85 or "polarity_conflict" in why or "numeric_mismatch" in why:
        return "high", "urgent"
    if s >= 0.62 or "profile_hint_value_change" in why:
        return "medium", "standard"
    return "low", "standard"


def upsert_review_state(
    db: Any,
    *,
    cid: int,
    severity: str,
    route: str,
    status: str = "pending",
    actor: str = "system",
    note: str = "",
) -> None:
    now = db.now_ms()
    with db.transact() as conn:
        conn.execute(
            """
            INSERT INTO contradiction_reviews(
              contradiction_id,
              severity,
              route,
              status,
              actor,
              note,
              created_at_ms,
              updated_at_ms
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(contradiction_id) DO UPDATE SET
              severity=excluded.severity,
              route=excluded.route,
              status=excluded.status,
              actor=excluded.actor,
              note=excluded.note,
              updated_at_ms=excluded.updated_at_ms
            """,
            (
                int(cid),
                str(severity or "medium"),
                str(route or "standard"),
                str(status or "pending"),
                str(actor or "system"),
                str(note or ""),
                now,
                now,
            ),
        )


def list_contradictions(
    db: Any,
    *,
    only_open: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    lim = max(1, min(500, int(limit)))
    if only_open:
        cur = db.execute(
            """
            SELECT
              c.*,
              r.severity AS review_severity,
              r.route AS review_route,
              r.status AS review_status,
              r.actor AS review_actor,
              r.note AS review_note,
              r.updated_at_ms AS review_updated_at_ms
            FROM contradictions c
            LEFT JOIN contradiction_reviews r ON r.contradiction_id=c.id
            WHERE c.resolved=0
            ORDER BY c.score DESC, c.created_at_ms DESC
            LIMIT ?
            """,
            (lim,),
        )
    else:
        cur = db.execute(
            """
            SELECT
              c.*,
              r.severity AS review_severity,
              r.route AS review_route,
              r.status AS review_status,
              r.actor AS review_actor,
              r.note AS review_note,
              r.updated_at_ms AS review_updated_at_ms
            FROM contradictions c
            LEFT JOIN contradiction_reviews r ON r.contradiction_id=c.id
            ORDER BY c.created_at_ms DESC
            LIMIT ?
            """,
            (lim,),
        )
    rows = [dict(r) for r in cur.fetchall()]
    for row in rows:
        sev = str(row.get("review_severity") or "").strip().lower()
        route = str(row.get("review_route") or "").strip().lower()
        if not sev or not route:
            d_sev, d_route = severity_route(
                score=float(row.get("score", 0.0) or 0.0),
                reason=str(row.get("reason", "")),
            )
            if not sev:
                sev = d_sev
            if not route:
                route = d_route
        row["severity"] = sev
        row["review_route"] = route
        row["review_status"] = str(row.get("review_status") or "pending").strip().lower()
    return rows


def list_contradictions_for_review(
    db: Any,
    *,
    status: str | None = None,
    severity: str | None = None,
    route: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    lim = max(1, min(500, int(limit)))
    where: list[str] = []
    args: list[Any] = []
    st = str(status or "").strip().lower()
    sev = str(severity or "").strip().lower()
    rt = str(route or "").strip().lower()
    if st:
        where.append("COALESCE(r.status,'pending')=?")
        args.append(st)
    if sev:
        where.append("COALESCE(r.severity,'medium')=?")
        args.append(sev)
    if rt:
        where.append("COALESCE(r.route,'standard')=?")
        args.append(rt)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.execute(
        f"""
        SELECT
          c.*,
          r.severity AS review_severity,
          r.route AS review_route,
          r.status AS review_status,
          r.actor AS review_actor,
          r.note AS review_note,
          r.updated_at_ms AS review_updated_at_ms
        FROM contradictions c
        LEFT JOIN contradiction_reviews r ON r.contradiction_id=c.id
        {where_sql}
        ORDER BY COALESCE(r.updated_at_ms, c.created_at_ms) DESC, c.score DESC
        LIMIT ?
        """,
        (*args, lim),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["severity"] = str(rec.get("review_severity") or "medium").strip().lower()
        rec["review_route"] = str(rec.get("review_route") or "standard").strip().lower()
        rec["review_status"] = str(rec.get("review_status") or "pending").strip().lower()
        out.append(rec)
    return out


def review_contradiction(
    db: Any,
    cid: int,
    *,
    decision: str,
    actor: str = "system",
    reason: str = "",
) -> bool:
    cid_i = int(cid)
    row = db.execute(
        "SELECT score, reason FROM contradictions WHERE id=?",
        (cid_i,),
    ).fetchone()
    if row is None:
        return False
    sev, route = severity_route(
        score=float(row["score"]),
        reason=str(row["reason"]),
    )
    action = str(decision or "").strip().lower()
    if action in ("approve", "resolve"):
        status = "approved"
        resolved = 1
    elif action in ("dismiss", "reject"):
        status = "dismissed"
        resolved = 1
    elif action in ("reopen", "open", "pending"):
        status = "pending"
        resolved = 0
    elif action in ("escalate",):
        status = "escalated"
        route = "urgent"
        resolved = 0
    else:
        return False

    with db.transact() as conn:
        conn.execute(
            "UPDATE contradictions SET resolved=? WHERE id=?",
            (resolved, cid_i),
        )
    upsert_review_state(
        db,
        cid=cid_i,
        severity=sev,
        route=route,
        status=status,
        actor=actor,
        note=reason,
    )
    return True
