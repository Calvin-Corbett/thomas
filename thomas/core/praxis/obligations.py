"""Hash-chained manager obligations with epochs for restart and stale-action fencing.

Each append verifies the prior JSONL chain, records the current manager epoch,
and fsyncs the new event. A corrupt or torn line fails closed. Rebuild derives
open obligations solely from this file so a replacement manager can resume.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

OWED = ("verdict", "repair", "feedback_delivery", "evaluation", "acceptance")
IDENTITY_FIELDS = ("owner", "role", "generation", "candidate_hash", "requirements_version", "acceptance_version")


class CorruptRecords(ValueError):
    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"obligation records corrupt at line {line}: {reason}")
        self.line = line
        self.reason = reason


class StaleEpoch(RuntimeError):
    def __init__(self, epoch: Any, current: int) -> None:
        super().__init__(f"stale manager epoch {epoch!r}; the current epoch is {current}")
        self.epoch = epoch
        self.current = current


class ObligationRefused(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def record_digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({key: value for key, value in record.items() if key != "sha256"})).hexdigest()


def seal_record(fields: dict[str, Any], *, seq: int, prev_sha256: str | None) -> dict[str, Any]:
    record = {**fields, "seq": seq, "prev_sha256": prev_sha256}
    record["sha256"] = record_digest(record)
    return record


def read_records(path: Any) -> list[dict[str, Any]]:
    path = Path(path)
    raw = path.read_bytes() if path.is_file() else b""
    if not raw:
        return []
    lines = raw.split(b"\n")
    if raw and not raw.endswith(b"\n"):
        raise CorruptRecords(len(lines), "torn_tail: the last record has no line end")
    records: list[dict[str, Any]] = []
    prev = None
    for number, line in enumerate(lines[:-1], start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise CorruptRecords(number, "unparseable") from None
        if not isinstance(record, dict) or record.get("sha256") != record_digest(record):
            raise CorruptRecords(number, "digest_mismatch")
        if record.get("prev_sha256") != prev or record.get("seq") != number:
            raise CorruptRecords(number, "chain_break")
        prev = record["sha256"]
        records.append(record)
    return records


def apply_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    epoch, manager_id = 0, None
    obligations: dict[str, dict[str, Any]] = {}
    stale: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    for record in records:
        event, seq = record.get("event"), record.get("seq")
        if event == "manager_epoch":
            if record.get("epoch") != epoch + 1:
                raise CorruptRecords(seq, "epoch_not_monotonic")
            epoch, manager_id = record["epoch"], record.get("manager_id")
            continue
        if record.get("epoch") != epoch:
            stale.append(
                {
                    "seq": seq,
                    "event": event,
                    "epoch": record.get("epoch"),
                    "current_epoch": epoch,
                    "obligation_id": record.get("obligation_id"),
                }
            )
            continue
        obligation_id = record.get("obligation_id")
        if event == "obligation_opened":
            obligations[obligation_id] = {
                "obligation_id": obligation_id,
                **{name: record.get(name) for name in IDENTITY_FIELDS},
                "owed": record.get("owed"),
                "status": "open",
                "opened_epoch": epoch,
                "opened_seq": seq,
                "verdicts": [],
            }
        elif event == "verdict_issued" and obligation_id in obligations:
            obligations[obligation_id]["verdicts"].append(
                {"outcome": record.get("outcome"), "epoch": epoch, "seq": seq}
            )
        elif event == "obligation_discharged" and obligation_id in obligations:
            obligations[obligation_id].update(
                status="discharged", how=record.get("how"), discharged_epoch=epoch, discharged_seq=seq
            )
        elif event == "stale_action_refused":
            refusals.append(
                {
                    "seq": seq,
                    "epoch": epoch,
                    **{key: record.get(key) for key in ("refused_epoch", "action", "obligation_id", "detail")},
                }
            )
    return {
        "epoch": epoch,
        "manager_id": manager_id,
        "records": len(records),
        "obligations": obligations,
        "open": {key: value for key, value in obligations.items() if value["status"] == "open"},
        "stale_rejected": stale,
        "refusals": refusals,
    }


def rebuild(path: Any) -> dict[str, Any]:
    """The obligation state rebuilt from the records alone."""
    return apply_records(read_records(path))


class ObligationLog:
    def __init__(self, path: Any) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def state(self) -> dict[str, Any]:
        return rebuild(self.path)

    def _append(self, fields: dict[str, Any], *, epoch: Any, check: Any = None) -> dict[str, Any]:
        with self._lock:
            records = read_records(self.path)
            current = apply_records(records)
            if fields.get("event") != "manager_epoch":
                if epoch != current["epoch"] or current["epoch"] == 0:
                    raise StaleEpoch(epoch, current["epoch"])
                fields = {**fields, "epoch": epoch}
            if check is not None:
                fields = check(current, fields)
            record = seal_record(fields, seq=len(records) + 1, prev_sha256=records[-1]["sha256"] if records else None)
            with self.path.open("ab") as handle:
                handle.write(_canonical(record) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            return record

    def open_epoch(self, manager_id: str) -> int:
        if not isinstance(manager_id, str) or not manager_id:
            raise ObligationRefused("manager_id must be a non-empty string")
        current = apply_records(read_records(self.path))["epoch"]
        record = self._append(
            {"event": "manager_epoch", "manager_id": manager_id, "epoch": current + 1},
            epoch=None,
            check=lambda state, fields: {**fields, "epoch": state["epoch"] + 1},
        )
        return record["epoch"]

    def open_obligation(
        self,
        *,
        epoch: int,
        obligation_id: str,
        owner: str,
        role: str,
        generation: int,
        candidate_hash: str,
        requirements_version: str,
        acceptance_version: str,
        owed: str,
    ) -> dict[str, Any]:
        fields = {
            "event": "obligation_opened",
            "obligation_id": obligation_id,
            "owner": owner,
            "role": role,
            "generation": generation,
            "candidate_hash": candidate_hash,
            "requirements_version": requirements_version,
            "acceptance_version": acceptance_version,
            "owed": owed,
        }
        problems = [
            name
            for name in (
                "obligation_id",
                "owner",
                "role",
                "candidate_hash",
                "requirements_version",
                "acceptance_version",
            )
            if not isinstance(fields[name], str) or not fields[name]
        ]
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            problems.append("generation")
        if owed not in OWED:
            problems.append("owed")
        if problems:
            raise ObligationRefused(f"bad obligation fields: {problems}")

        def check(state: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
            if obligation_id in state["obligations"]:
                raise ObligationRefused(f"obligation {obligation_id} already exists")
            return fields

        return self._append(fields, epoch=epoch, check=check)

    def _open_obligation(self, state: dict[str, Any], obligation_id: str) -> dict[str, Any]:
        obligation = state["open"].get(obligation_id)
        if obligation is None:
            raise ObligationRefused(f"obligation {obligation_id} is not open")
        return obligation

    def issue_verdict(self, *, epoch: int, obligation_id: str, outcome: str) -> dict[str, Any]:
        def check(state: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
            obligation = self._open_obligation(state, obligation_id)
            return {**fields, **{name: obligation[name] for name in IDENTITY_FIELDS}}

        return self._append(
            {"event": "verdict_issued", "obligation_id": obligation_id, "outcome": outcome}, epoch=epoch, check=check
        )

    def discharge(self, *, epoch: int, obligation_id: str, how: str) -> dict[str, Any]:
        def check(state: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
            self._open_obligation(state, obligation_id)
            return fields

        return self._append(
            {"event": "obligation_discharged", "obligation_id": obligation_id, "how": how}, epoch=epoch, check=check
        )

    def record_refusal(
        self,
        *,
        epoch: int,
        refused_epoch: Any,
        action: str,
        obligation_id: str | None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record, at the current epoch, that an action from a fenced (older) manager epoch was refused and not applied."""
        return self._append(
            {
                "event": "stale_action_refused",
                "refused_epoch": refused_epoch,
                "action": action,
                "obligation_id": obligation_id,
                "detail": dict(detail or {}),
            },
            epoch=epoch,
        )


__all__ = [
    "IDENTITY_FIELDS",
    "OWED",
    "CorruptRecords",
    "ObligationLog",
    "ObligationRefused",
    "StaleEpoch",
    "apply_records",
    "read_records",
    "rebuild",
    "record_digest",
    "seal_record",
]
