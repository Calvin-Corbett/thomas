"""Run single functions out of the Windows launcher scripts, never the scripts.

run-ui.ps1 rewrites the thomas:// handler in your registry and stops servers, so a
test that wants to know what one of its functions does cannot run it. This parses
the script with PowerShell's own parser, defines only the functions a test names
in a fresh ``powershell.exe``, and then runs the test's body against them. What the
body must not reach (the registry, ``Start-Process``, ``winget``) it replaces with
a function of the same name; a function shadows a cmdlet, so the launcher's call
lands on the stand-in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_UI = ROOT / "scripts" / "run-ui.ps1"
RUN_REPL = ROOT / "scripts" / "run-repl.ps1"

POWERSHELL = shutil.which("powershell") or shutil.which("powershell.exe")
needs_windows_powershell = pytest.mark.skipif(
    os.name != "nt" or not POWERSHELL, reason="the launchers are Windows PowerShell scripts"
)

_LOADER = """\
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {{ throw ('parse errors: ' + $errors.Count) }}
$wanted = @({names})
$found = @()
foreach ($fn in $ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }}, $true)) {{
  if ($wanted -contains $fn.Name) {{ . ([scriptblock]::Create($fn.Extent.Text)); $found += $fn.Name }}
}}
foreach ($name in $wanted) {{ if ($found -notcontains $name) {{ throw ('function not in script: ' + $name) }} }}
$markers = @({markers})
$topLevel = @()
foreach ($statement in $ast.EndBlock.Statements) {{
  if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {{ continue }}
  foreach ($marker in $markers) {{ if ($statement.Extent.Text.Contains($marker)) {{ $topLevel += $statement.Extent.Text; break }} }}
}}
"""


def run_functions(
    script: Path,
    names: list[str],
    body: str,
    workdir: Path,
    *,
    timeout: int = 180,
    top_level: tuple[str, ...] = (),
) -> str:
    """Define *names* from *script*, run *body*, and return stdout plus stderr.

    A script's own top-level statements (the ones that call its functions) are left
    out unless *top_level* names a marker they contain; those come back, in order, as
    the strings of ``$topLevel``. ``foreach ($s in $topLevel) { . ([scriptblock]::Create($s)) }``
    runs them, and an ``exit`` in one of them ends the run there.
    """
    assert POWERSHELL, "needs_windows_powershell should have skipped this test"
    quoted = ", ".join("'" + name + "'" for name in names)
    markers = ", ".join("'" + marker.replace("'", "''") + "'" for marker in top_level)
    program = _LOADER.format(script=str(script).replace("'", "''"), names=quoted, markers=markers) + "\n" + body
    path = workdir / "harness.ps1"
    # With a BOM: Windows PowerShell 5.1 reads a script without one as the ANSI code page, so
    # an accent in a path (a user name, say) would reach the body garbled.
    path.write_text(program, encoding="utf-8-sig")
    done = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(workdir),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.stdout + done.stderr


def ps_path(path: Path) -> str:
    """*path* as a single-quoted PowerShell literal."""
    return "'" + str(path).replace("'", "''") + "'"


def stand_in_server(health: dict | None, status: dict | int | str | None) -> ThreadingHTTPServer:
    """A server answering /api/health and /api/evolve/agent/status like Thomas does.

    For each route, None is "no such route" (404), a dict is the JSON answer, an int is
    that HTTP error status, and a str is sent as the body of a 200 as it is.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = {"/api/health": health, "/api/evolve/agent/status": status}.get(self.path)
            if payload is None or isinstance(payload, int):
                self.send_error(404 if payload is None else payload)
                return
            body = (payload if isinstance(payload, str) else json.dumps(payload)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def closed_port() -> int:
    """A port nothing is listening on."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.server_close()
    return port
