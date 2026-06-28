"""SWEEP: runtime load verification — does Thomas actually OPEN a generated app
and confirm it runs, the way Claude Code does (build -> run -> observe)?

Static verification (sweep_deliverable_executability) confirms files exist and refs
resolve. This sweep proves the STRONGER capability: a headless browser load that
catches failures static checks are blind to — an uncaught JS error on load, or a
page that renders blank despite every file being present. The discriminating probe
builds an app whose files ALL exist (static = ok) but whose script throws on load
(runtime = fail).

Skips cleanly (counts as pass) when no browser is available, so the harness stays
green on headless CI without Chromium.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Recorder

A = "runtime-load-verification"


def _mk(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def run() -> Recorder:
    rec = Recorder("runtime_executability")
    try:
        from thomas.server.deliverable_runtime_verify import runtime_smoke_load
        from thomas.server.deliverable_verify import verify_web_deliverable
    except Exception as e:  # noqa: BLE001
        rec.add(
            case="runtime smoke-load capability exists",
            dimension=A,
            expected="thomas.server.deliverable_runtime_verify importable",
            actual=f"not available: {type(e).__name__}: {e}",
            passed=False,
            severity="critical",
            evidence="no runtime verification => JS-crash/blank apps ship as 'done'",
        )
        return rec

    # Probe a trivial good page first; if the browser can't launch here, skip the
    # behavioural probes (pass) rather than fail the harness on a browserless host.
    probe = runtime_smoke_load(_mk({"index.html": "<!doctype html><body><h1>hello world</h1></body>"}))
    if probe.skipped:
        rec.add(
            case="runtime verification available (browser present)",
            dimension=A,
            expected="headless Chromium available OR cleanly skipped",
            actual=f"skipped: {probe.reason}",
            passed=True,  # graceful skip — capability exists, environment lacks a browser
            severity="low",
            evidence="runtime_smoke_load returns skipped when Playwright/browser absent",
        )
        return rec

    # THE DISCRIMINATOR: all files present (static passes) but JS throws on load.
    crash = _mk(
        {
            "index.html": '<!doctype html><body><canvas id="c" width="300" height="150"></canvas>'
            '<script src="app.js"></script></body>',
            "app.js": 'document.getElementById("c").getContext("2d"); boom.draw();',  # ReferenceError
        }
    )
    s_crash = verify_web_deliverable(crash)
    r_crash = runtime_smoke_load(crash)
    rec.add(
        case="runtime catches a JS crash that static verification passes",
        dimension=A,
        expected="static ok=True BUT runtime ok=False (uncaught JS error on load)",
        actual=f"static_ok={s_crash.ok} runtime_ok={r_crash.ok} reason={r_crash.reason!r}",
        passed=(s_crash.ok and not r_crash.ok and bool(r_crash.page_errors)),
        severity="critical",
        evidence="files-exist != app-runs; only opening it catches the crash",
    )

    # A genuinely working canvas app must pass runtime verification (no false alarm).
    good = _mk(
        {
            "index.html": '<!doctype html><body><canvas id="c" width="300" height="150"></canvas>'
            '<script src="app.js"></script></body>',
            "app.js": 'const x=document.getElementById("c").getContext("2d");x.fillStyle="#0a8";x.fillRect(10,10,120,80);',
        }
    )
    r_good = runtime_smoke_load(good)
    rec.add(
        case="runtime does NOT false-flag a working canvas app",
        dimension=A,
        expected="runtime ok=True (canvas drawn, no errors)",
        actual=f"runtime_ok={r_good.ok} canvas_drawn={r_good.canvas_drawn} errors={r_good.page_errors}",
        passed=r_good.ok,
        severity="high",
        evidence="runtime check must accept a real app, not just reject broken ones",
    )

    # Wiring: the runtime check is reachable from the finalize path (opt-in flag).
    try:
        from thomas.server.chat_delegation_deliverable import runtime_executability_warning

        wired = callable(runtime_executability_warning)
        actual = f"runtime_executability_warning callable={wired}"
    except Exception as e:  # noqa: BLE001
        wired = False
        actual = f"not wired: {type(e).__name__}: {e}"
    rec.add(
        case="runtime verification is wired into the finalize path (opt-in)",
        dimension=A,
        expected="runtime_executability_warning importable from the deliverable module",
        actual=actual,
        passed=wired,
        severity="high",
        evidence="chat_delegation.py _finalize_worker_completion -> await to_thread(runtime_executability_warning)",
    )
    return rec


if __name__ == "__main__":
    r = run()
    for row in r.rows:
        print(("PASS" if row.passed else "FAIL"), "|", row.case, "->", row.actual)
