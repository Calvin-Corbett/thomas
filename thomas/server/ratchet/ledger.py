"""Every candidate's history: one JSON line per event, appended, never rewritten.

A candidate is keyed by its tip commit. Ancestry cannot say whether it landed:
the promoter lands a new single-parent commit, so the candidate's own commit
never becomes an ancestor of dev. The ledger line linking the two is the record.

When a candidate is proven again:

* never, once it ``landed``, is ``already_on_dev`` or ``not_for_ratchet``, or you declined it;
* never while it waits for your card, or while a hand-off to the promoter is unaccounted for (``settling``);
* never while a Build team is repairing it: a run takes that repair up again in the green it is in
  (``repair.resume``), because starting over would discard the team's work;
* after a report, only once dev has moved, and at most ``MAX_REPORTS`` reports;
* ``queued`` (waiting on something outside it, including a hand-in withdrawn before your card) or an
  attempt a restart cut short: at the next run. A withdrawal is never a report. What a candidate waits on
  is checked before any green is spent, so waiting costs a screen, not a proof.

A halt (``halt.json`` beside the ledger) is not a candidate's state: a landing
broke a test, and every run stops until the tests it names pass on dev.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.server import self_change_status
from thomas.server.ratchet.candidates import Candidate

ROOT_ENV = "THOMAS_RATCHET_ROOT"
MAX_REPORTS = 3
STATES = (
    "queued",
    "proving",
    "repairing",
    "settling",
    "awaiting_card",
    "landed",
    "already_on_dev",
    "reported",
    "not_for_ratchet",
)
TERMINAL = frozenset({"landed", "already_on_dev", "not_for_ratchet"})
DECLINED = "declined by you"
WITHDRAWN = "the hand-in was withdrawn before your card; you were never asked"
HALT_NAME = "halt.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ratchet_root() -> Path:
    """``<Thomas data dir>/ratchet`` unless ``THOMAS_RATCHET_ROOT`` says otherwise."""
    raw = str(os.environ.get(ROOT_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    from thomas.core.config import resolve_thomas_data_dir

    return resolve_thomas_data_dir() / "ratchet"


class Ledger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ratchet_root() / "ledger.jsonl"
        self._lock = threading.Lock()

    def record(
        self,
        *,
        dev_sha: str,
        state: str,
        reason: str = "",
        candidate: Candidate | None = None,
        sha: str = "",
        refs: Sequence[str] = (),
        landed_commit: str = "",
        proof: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        if state not in STATES:
            raise ValueError(f"not a ratchet state: {state}")
        names = list(candidate.refs if candidate is not None else refs)
        event = {
            "at": _now(),
            "candidate_ref": names[0] if names else "",
            "candidate_sha": candidate.sha if candidate is not None else sha,
            "dev_sha": dev_sha,
            "state": state,
            "reason": reason,
            "landed_commit": landed_commit,
            "proof": dict(proof or {}),
            "refs": names,
            **extra,
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            separator = self._separator()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(separator + line + "\n")
        return event

    def _separator(self) -> str:
        """A newline first when a crash left the last line unfinished, so the new line stays whole."""
        try:
            with self.path.open("rb") as fh:
                fh.seek(-1, os.SEEK_END)
                return "" if fh.read(1) == b"\n" else "\n"
        except OSError:  # missing or empty
            return ""

    def events(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a line a crash left unfinished
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def latest(self) -> dict[str, dict[str, Any]]:
        last: dict[str, dict[str, Any]] = {}
        for row in self.events():
            sha = str(row.get("candidate_sha") or "")
            if sha:
                last[sha] = row
        return last

    def reports(self, sha: str) -> int:
        return sum(1 for row in self.events() if row.get("candidate_sha") == sha and row.get("state") == "reported")

    def withdrawals(self, sha: str) -> int:
        return sum(1 for row in self.events() if row.get("candidate_sha") == sha and row.get("reason") == WITHDRAWN)

    def awaiting(self) -> list[dict[str, Any]]:
        return [row for row in self.latest().values() if row.get("state") == "awaiting_card"]

    def repairing(self) -> list[dict[str, Any]]:
        """Every candidate a Build team was last recorded repairing: a restart leaves one behind (``repair.resume``)."""
        return [row for row in self.latest().values() if row.get("state") == "repairing"]

    def should_prove(self, sha: str, dev_sha: str) -> tuple[bool, str]:
        """(True, "") when *sha* is proven on *dev_sha* now; otherwise (False, why not)."""
        last = self.latest().get(sha)
        if last is None:
            return True, ""
        state, reason = str(last.get("state") or ""), str(last.get("reason") or "")
        if state in TERMINAL:
            return False, f"{state.replace('_', ' ')}: {reason}"
        if state == "awaiting_card":
            sid = str(last.get("submission") or "")
            if sid and (self_change_status.read_hand_in_state(sid) or {}).get("status") == "withdrawn":
                return False, f"{WITHDRAWN}; the next run proves it again"
            return False, "waiting for your card"
        if state == "settling":
            return False, "a hand-off to the promoter was cut short; the next run looks for it first"
        if state == "repairing":
            # A run resumes a repair (``repair.resume``) before it proves anything, so this is
            # reached only when that could not happen; the green still holds the team's work.
            return False, "a Build team is repairing it; the next run takes that repair up again"
        if state == "reported" and reason.startswith(DECLINED):
            return False, "you declined it; it is proposed again only if it changes"
        if state == "reported":
            if self.reports(sha) >= MAX_REPORTS:
                return False, f"reported {MAX_REPORTS} times; the last reason: {reason}"
            if last.get("dev_sha") == dev_sha:
                return False, "reported on this dev; it is proven again when dev moves"
        return True, ""

    def gave_up(self, sha: str) -> str:
        """Why *sha* will never be proven again for its own sake ("" when it may be): a stacked candidate above
        it is then reported instead of waiting forever."""
        last = self.latest().get(sha)
        if last is None:
            return ""
        state, reason = str(last.get("state") or ""), str(last.get("reason") or "")
        if state == "not_for_ratchet":
            return f"not for the ratchet: {reason}"
        if state == "reported" and reason.startswith(DECLINED):
            return reason
        if state == "reported" and self.reports(sha) >= MAX_REPORTS:
            return f"reported {MAX_REPORTS} times: {reason}"
        return ""

    def halt(self, **detail: Any) -> dict[str, Any]:
        """Stop every later run: a landing broke a test (``landing.conclude``). Written whole, kept until cleared."""
        record = {"at": _now(), **detail}
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{HALT_NAME}.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, folder / HALT_NAME)
        return record

    def halted(self) -> dict[str, Any] | None:
        """The halt, or None. A halt file that cannot be read still halts: a damaged stop is still a stop."""
        path = self.path.parent / HALT_NAME
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            return data
        return {"reason": f"a halt is recorded in {path} but cannot be read; remove it once dev is checked"}

    def clear_halt(self, reason: str) -> None:
        """Keep the halt beside the ledger as ``halt-cleared-<time>.json``, with why it was cleared, and lift it."""
        record = {**(self.halted() or {}), "cleared_at": _now(), "cleared": reason}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        kept = self.path.parent / f"halt-cleared-{stamp}.json"
        kept.write_text(json.dumps(record, default=str), encoding="utf-8")
        (self.path.parent / HALT_NAME).unlink(missing_ok=True)


__all__ = [
    "DECLINED",
    "HALT_NAME",
    "MAX_REPORTS",
    "ROOT_ENV",
    "STATES",
    "TERMINAL",
    "WITHDRAWN",
    "Ledger",
    "ratchet_root",
]
