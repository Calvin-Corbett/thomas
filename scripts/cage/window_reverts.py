"""A failed after-check keeps its revert request until its own undo finishes, including across a restart."""

from __future__ import annotations

from scripts.cage import checker_jobs as cj


class Reverts:
    def __init__(self, loop: object) -> None:
        self.loop = loop
        self.pending: list[dict[str, object]] = []
        self.active = False

    def add(self, sid: str, commit: str, failed: list[str], batch: list[str]) -> None:
        if any(row["commit"] == commit for row in self.pending):
            return
        fields = {"sid": sid, "commit": commit, "failed": failed, "batch": batch}
        self.loop.record.event("revert_pending", **fields)
        self.pending.append(fields)

    def recover(self) -> None:
        events = self.loop.record.events()
        finished = {row.get("commit") for row in events if row.get("name") == "revert_finished"}
        finished |= {row.get("undoes") for row in events if row.get("name") == "undo_landed"}
        for row in events:
            if row.get("commit") in finished:
                continue
            if row.get("name") == "revert_pending":
                if not any(item["commit"] == row.get("commit") for item in self.pending):
                    self.pending.append({key: row.get(key, []) for key in ("sid", "commit", "failed", "batch")})
            elif row.get("name") == "after_check" and row.get("verdict") == cj.FAILED:
                self.add(
                    str(row.get("sid")),
                    str(row.get("commit")),
                    list(row.get("findings") or []),
                    list(row.get("batch") or []),
                )

    def step(self) -> None:
        if not self.pending:
            return
        loop, request = self.loop, self.pending[0]
        if self.active:
            if loop.undoer.current is not None:
                return
            loop.record.event("revert_finished", **request, detail=loop.undoer.said)
            self.pending.pop(0)
            self.active = False
            return
        if loop.undoer.current is not None:
            return
        why = loop.undoer.start(request["sid"], kind="revert_change", failed=request["failed"], batch=request["batch"])
        if why:
            loop._note(f"the queued revert of {request['sid']} waits: {why}")
            return
        self.active = True  # retained even if recording this start fails; never start a duplicate undo
        loop.record.event("revert_started", **request)
        loop._note(f"the revert of {request['sid']} is being checked; then it is asked on its own card")


__all__ = ["Reverts"]
