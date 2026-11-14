"""What the caged Thomas is running: every process of the cage's account, what each one is and what it costs.

Part of the read-only window into the cage (``thomas.core.cage_inspector`` has the runs and the self-fix copies).
Windows hides the command lines of the cage account from yours, so the cage's own server reads its processes and
answers. Nothing here writes or runs a command, and anything shaped like a password or key is hidden.
"""

from __future__ import annotations

import collections
import re
import time
from typing import Any

_SECRET_ARG = re.compile(
    r"((?:--?(?:token|key|secret|password|api[-_]?key|auth)[=\s]+)|(?:bearer\s+)|(?:(?:password|token|secret|api_key)=))\S+",
    re.I,
)
_KEY_SHAPED = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})\b")


def redact(text: str) -> str:
    """Hide what looks like a credential in a command line or a log line."""
    return _KEY_SHAPED.sub("[redacted]", _SECRET_ARG.sub(lambda m: m.group(1) + "[redacted]", text))


def _times(owner: str) -> dict[int, tuple[float, Any]]:
    """Processor seconds used so far by each process of this account, with the process, for a second reading."""
    import psutil

    found: dict[int, tuple[float, Any]] = {}
    for proc in psutil.process_iter(["pid", "ppid", "name", "username", "create_time", "memory_info"]):
        if owner and proc.info.get("username") != owner:
            continue
        try:
            used = proc.cpu_times()
            found[proc.pid] = (used.user + used.system, proc)
        except (psutil.Error, OSError):
            continue
    return found


def label(rows: list[dict[str, Any]], *, server_pid: int) -> list[dict[str, Any]]:
    """Say what each process is, from its name, its command line and its parent. Rows are changed and returned.

    A program started from the project's environment shows as two processes: its ``python.exe`` only starts the real
    interpreter as its child and waits. That half is named for what it starts, so twelve Build agents read as twelve.
    """
    by_parent: dict[Any, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_parent[row.get("ppid")].append(row)

    def plain(row: dict[str, Any]) -> str:
        name, cmd = str(row.get("name") or "").lower(), str(row.get("cmd") or "").lower()
        if row.get("pid") == server_pid:
            return "the server"
        if "forge_code_runner" in cmd:
            return "Build agent"
        if "pytest" in cmd:
            return "test run"
        if name.startswith("chrome"):
            return "browser a test or playtest opened"
        if name == "conhost.exe":
            return "console host"
        if name == "git.exe":
            return "git"
        return "other"

    for row in rows:
        row["kind"] = plain(row)
    for row in rows:
        name = str(row.get("name") or "").lower()
        twins = [child for child in by_parent.get(row.get("pid"), ()) if str(child.get("name") or "").lower() == name]
        if name.startswith("python") and len(twins) == 1 and row["kind"] == twins[0]["kind"] != "other":
            if row.get("pid") != server_pid and abs((row.get("age_s") or 0) - (twins[0].get("age_s") or 0)) <= 3:
                row["kind"] = f"launcher half of a {twins[0]['kind']}"
    return rows


def processes(limit: int = 400, sample_s: float = 1.0) -> dict[str, Any]:
    """The processes this server's account runs: what each is, its parent, memory, command line (credentials hidden)
    and the share of the whole PC's processor it used over *sample_s* seconds."""
    try:
        import psutil
    except ImportError:
        return {"ok": False, "error": "psutil is not installed"}
    me = psutil.Process()
    try:
        owner = me.username()
    except (psutil.Error, OSError):
        owner = ""
    cores = psutil.cpu_count() or 1
    before = _times(owner)
    sample_s = max(0.05, min(float(sample_s), 5.0))
    time.sleep(sample_s)
    rows: list[dict[str, Any]] = []
    for pid, (used, proc) in _times(owner).items():
        info = proc.info
        try:
            cmd = redact(" ".join(proc.cmdline()))[:240]
        except (psutil.Error, OSError):
            cmd = ""
        earlier = before.get(pid)
        mem = info.get("memory_info")
        rows.append(
            {
                "pid": pid,
                "ppid": info.get("ppid"),
                "name": info.get("name"),
                # None for a process that started inside the sample: there is no first reading to compare with.
                "cpu_percent": round(max(0.0, used - earlier[0]) / sample_s * 100 / cores, 2) if earlier else None,
                "rss_mb": round(mem.rss / 1048576, 1) if mem else None,
                "age_s": int(time.time() - info["create_time"]) if info.get("create_time") else None,
                "cmd": cmd,
            }
        )
    label(rows, server_pid=me.pid)
    kinds: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = kinds.setdefault(row["kind"], {"count": 0, "cpu_percent": 0.0})
        entry["count"] += 1
        entry["cpu_percent"] = round(entry["cpu_percent"] + (row["cpu_percent"] or 0.0), 2)
    rows.sort(key=lambda r: (-(r["cpu_percent"] or 0), -(r["rss_mb"] or 0)))
    return {
        "ok": True,
        "account": owner,
        "server_pid": me.pid,
        "count": len(rows),
        "cores": cores,
        "sample_s": sample_s,
        "cpu_percent": round(sum(row["cpu_percent"] or 0.0 for row in rows), 2),
        "kinds": kinds,
        "processes": rows[:limit],
    }


__all__ = ["label", "processes", "redact"]
