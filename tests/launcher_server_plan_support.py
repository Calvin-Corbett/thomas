"""Stand-in servers and the launcher's plan for each, shared by the tests of Get-ExistingServerPlan.

run-ui.ps1 decides what to do about a Thomas already on its port from what that
server answers on /api/health and /api/evolve/agent/status. These helpers start
small servers that answer those two routes and ask the launcher's own decision
function about each, without running the launcher or stopping any process.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.launcher_powershell_support import RUN_UI, closed_port, run_functions, stand_in_server

FUNCTIONS = [
    "Test-PortListening",
    "ConvertTo-ComparablePath",
    "Get-ThomasBuildLabel",
    "Get-ThomasRunningInstance",
    "Test-CodeNewerThanServer",
    "Get-ThomasActiveRuns",
    "Get-ExistingServerPlan",
]
LOCAL_VERSION = "9.9.9"
LOCAL_ROOT = "C:\\Apps\\Thomas"
LOCAL_COMMIT = "aaaa1111"
ELSEWHERE = "D:\\Work\\Thomas"
IDLE = {"ok": True, "running": False, "recording": False, "runs": []}
BUSY = {
    "ok": True,
    "running": True,
    "recording": False,
    "runs": [{"run_id": "run_1", "conversation_id": "c1", "running": True, "recording": False}],
}
# The status route builds its top-level flags from the legacy single session and runs[] from the
# registry, so a server can be running with no runs listed.
LEGACY_BUSY = {"ok": True, "running": True, "recording": False, "runs": []}
LEGACY_RECORDING = {"ok": True, "running": False, "recording": True, "runs": []}


def health(
    *,
    version: str = LOCAL_VERSION,
    status: str = "ok",
    root: str = LOCAL_ROOT,
    commit: str = LOCAL_COMMIT,
    build: bool = True,
    dirty: bool = False,
    uptime: float | str | None = None,
    degraded: list[str] | None = None,
) -> dict:
    """What /api/health answers, with or without the build block and the uptime older servers lack.

    *degraded* is the list of what the server says is degraded; None leaves the field out, as an older server does.
    """
    payload: dict = {"status": status, "version": version, "pid": 1}
    if degraded is not None:
        payload["degraded"] = degraded
    if uptime is not None:
        payload["uptime_s"] = uptime
    if build:
        payload["build"] = {"version": version, "commit": commit, "branch": "dev", "dirty": dirty, "root": root}
    return payload


def plan_lines(
    cases: dict[str, tuple[dict, dict | int | str | None]], work: Path, roots: dict[str, str] | None = None
) -> dict[str, str]:
    """The plan for each case without and with a replacement asked for, keyed ``name`` or ``name -ReplaceIt``.

    *cases* maps a name to (what /api/health says, what /api/evolve/agent/status says: a dict, an HTTP error
    status, a raw body, or None for no such route); *roots* names the folder a case is launched from when it is not LOCAL_ROOT. Each value is
    ``name|action|message``; ``left:<key>`` holds 1 or 0 for whether the plan left a Thomas running that is
    not what was launched, ``degraded:<key>`` for whether the one it attached to reports degraded, ``ports`` the port of each case and ``raw`` everything the run printed.
    """
    servers = {name: stand_in_server(*case) for name, case in cases.items()}
    ports = {name: server.server_address[1] for name, server in servers.items()}
    ports["nothing there"] = closed_port()
    body = f"function Get-LocalGitCommit {{ '{LOCAL_COMMIT}' }}\n"
    for name, port in ports.items():
        root = (roots or {}).get(name, LOCAL_ROOT).replace("'", "''")
        for flag in ("", " -ReplaceIt"):
            body += (
                f"$p = Get-ExistingServerPlan -P {port} -LocalVersion '{LOCAL_VERSION}' -LocalRoot '{root}'{flag}\n"
                f"'{name}{flag}|' + $p.Action + '|' + $p.Message\n"
                f"'left:{name}{flag}=' + [int]($p.Left -eq $true)\n"
                f"'degraded:{name}{flag}=' + [int]($p.Degraded -eq $true)\n"
            )
    try:
        out = run_functions(RUN_UI, FUNCTIONS, body, work)
    finally:
        for server in servers.values():
            server.shutdown()
            server.server_close()
    got = {line.split("|", 1)[0]: line for line in out.splitlines() if "|" in line}
    got.update(
        {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in out.splitlines()
            if line.startswith(("left:", "degraded:"))
        }
    )
    got["ports"] = json.dumps(ports)
    got["raw"] = out
    return got


def port_of(plans: dict[str, str], name: str) -> int:
    return json.loads(plans["ports"])[name]
