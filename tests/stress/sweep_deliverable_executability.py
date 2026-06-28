"""SWEEP: deliverable executability — does a generated multi-file app actually
RENDER when the user opens it, or does the server block its own assets?

This is the dimension the rest of the harness is blind to. The existing probes
confirm a task is "completed" and that a *.html deliverable gets a clickable URL,
but NONE of them check that opening that URL yields a *working* app. A multi-file
app (index.html + styles.css + src/app.js) served from /deliverable/ under
`Cross-Origin-Resource-Policy: same-site` has its CSS and JS BLOCKED by Chromium
on a bare-IP host (127.0.0.1) as ERR_BLOCKED_BY_RESPONSE.NotSameSite -> a blank
white page. That is the real-world "the game is just all white" defect.

Frontier standard (Claude Code): a delivered app opens and runs; the server never
blocks the app's own first-party assets. This sweep drives the REAL security-
headers middleware and asserts the CORP header on a /deliverable/ asset is one a
browser will actually load.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from _harness import Recorder
from aiohttp import web

A = "deliverable-executability"

# CORP values a browser will NOT block for a first-party sub-resource on an IP
# host. `same-site` is the one that breaks (NotSameSite on 127.0.0.1).
BROWSER_SAFE_CORP = {"cross-origin", "same-origin"}


def _extract_security_middleware():
    """Attach the REAL middleware stack to a throwaway app and return the
    security_headers middleware so we can drive it deterministically."""
    from thomas.core.config import AppConfig
    from thomas.server.app_middleware_handlers import setup_middleware_and_handlers

    app = web.Application()
    cfg = AppConfig()
    with tempfile.TemporaryDirectory() as td:
        web_dir = Path(td)
        (web_dir / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
        setup_middleware_and_handlers(app, cfg, web_dir, web_dir, asyncio.Lock())
    for mw in app.middlewares:
        if getattr(mw, "__name__", "") == "security_headers":
            return mw
    return None


async def _corp_for(mw, path: str) -> str:
    class _Req:
        def __init__(self, p: str) -> None:
            self.path = p
            self.method = "GET"
            self.remote = "127.0.0.1"
            self.headers: dict = {}

    async def handler(_req):
        return web.Response(body=b"x", content_type="text/css")

    resp = await mw(_Req(path), handler)
    return str(resp.headers.get("Cross-Origin-Resource-Policy", "")).strip().lower()


def run() -> Recorder:
    rec = Recorder("deliverable_executability")
    try:
        mw = _extract_security_middleware()
    except Exception as e:  # noqa: BLE001 — record the failure as a probe result
        rec.add(
            case="construct real security_headers middleware",
            dimension=A,
            expected="middleware stack builds without error",
            actual=f"setup raised {type(e).__name__}: {e}",
            passed=False,
            severity="high",
            evidence="app_middleware_handlers.setup_middleware_and_handlers",
        )
        return rec

    if mw is None:
        rec.add(
            case="locate security_headers middleware",
            dimension=A,
            expected="security_headers middleware present in app.middlewares",
            actual="not found",
            passed=False,
            severity="high",
            evidence="app.middlewares",
        )
        return rec

    # A real multi-file generated app: index.html pulls in these first-party
    # sub-resources. Each must be served with a browser-loadable CORP.
    sub_resources = [
        "/deliverable/exec-demo/styles.css",
        "/deliverable/exec-demo/src/game.js",
    ]
    for asset in sub_resources:
        corp = asyncio.run(_corp_for(mw, asset))
        passed = corp in BROWSER_SAFE_CORP
        rec.add(
            case=f"multi-file app sub-resource '{asset}' is not browser-blocked",
            dimension=A,
            expected=f"Cross-Origin-Resource-Policy in {sorted(BROWSER_SAFE_CORP)} (loads on 127.0.0.1)",
            actual=f"Cross-Origin-Resource-Policy={corp!r}",
            passed=passed,
            severity="critical",
            evidence="same-site CORP -> ERR_BLOCKED_BY_RESPONSE.NotSameSite on IP host (app_middleware_handlers.py security_headers)",
        )

    # Negative control: a normal app page (NOT under /deliverable/) keeps the
    # strict same-site default — we only relax for generated deliverables.
    main_corp = asyncio.run(_corp_for(mw, "/static/css/components.css"))
    rec.add(
        case="main-app asset keeps strict same-site CORP (fix is scoped)",
        dimension=A,
        expected="Cross-Origin-Resource-Policy='same-site' for non-deliverable paths",
        actual=f"Cross-Origin-Resource-Policy={main_corp!r}",
        passed=(main_corp == "same-site"),
        severity="low",
        evidence="the /deliverable relaxation must not weaken the main app's headers",
    )

    # --- Pre-flight deliverable verification (the "verify before you claim done"
    # capability Claude Code has and Thomas historically lacked). Drive the REAL
    # verifier against the exact broken shapes that shipped as white screens. ---
    _verify_probes(rec)
    return rec


def _verify_probes(rec: Recorder) -> None:
    try:
        from thomas.server.deliverable_verify import verify_web_deliverable
    except Exception as e:  # noqa: BLE001 — capability absent is itself the finding
        rec.add(
            case="a deliverable verifier capability exists (verify before 'done')",
            dimension=A,
            expected="thomas.server.deliverable_verify.verify_web_deliverable importable",
            actual=f"not available: {type(e).__name__}: {e}",
            passed=False,
            severity="critical",
            evidence="no pre-flight check => broken/empty apps ship as 'completed'",
        )
        return

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # (a) A real multi-file app whose assets all resolve -> must verify OK.
        good = base / "good"
        (good / "src").mkdir(parents=True)
        (good / "index.html").write_text(
            '<!doctype html><link rel="stylesheet" href="styles.css"><script src="src/game.js"></script><h1>Game</h1>',
            encoding="utf-8",
        )
        (good / "styles.css").write_text("body{}", encoding="utf-8")
        (good / "src" / "game.js").write_text("console.log(1)", encoding="utf-8")
        r_good = verify_web_deliverable(good)
        rec.add(
            case="verifier passes a complete, runnable multi-file app",
            dimension=A,
            expected="ok=True (entry non-empty, all first-party refs resolve)",
            actual=f"ok={r_good.ok} checked={r_good.checked_refs} problems={r_good.problems}",
            passed=r_good.ok and r_good.checked_refs == 2,
            severity="high",
            evidence="verify_web_deliverable",
        )

        # (b) An empty entry document -> must be caught (this is a hollow ship).
        empty = base / "empty"
        empty.mkdir()
        (empty / "index.html").write_text("   \n  ", encoding="utf-8")
        r_empty = verify_web_deliverable(empty)
        rec.add(
            case="verifier catches an empty index.html (hollow 'completed')",
            dimension=A,
            expected="ok=False with an 'empty' reason",
            actual=f"ok={r_empty.ok} problems={r_empty.problems}",
            passed=(not r_empty.ok) and any("empty" in p for p in r_empty.problems),
            severity="critical",
            evidence="empty deliverable must never be reported as completed",
        )

        # (c) The actual white-screen shape: index.html references a JS file that
        # was never created -> must be caught BEFORE claiming done.
        broken = base / "broken"
        broken.mkdir()
        (broken / "index.html").write_text(
            '<!doctype html><link rel="stylesheet" href="styles.css"><script src="src/game.js"></script>',
            encoding="utf-8",
        )
        (broken / "styles.css").write_text("body{}", encoding="utf-8")
        # NOTE: src/game.js intentionally NOT created.
        r_broken = verify_web_deliverable(broken)
        rec.add(
            case="verifier catches a missing referenced asset (white-screen shape)",
            dimension=A,
            expected="ok=False, src/game.js flagged missing",
            actual=f"ok={r_broken.ok} missing={r_broken.missing_refs}",
            passed=(not r_broken.ok) and any("game.js" in m for m in r_broken.missing_refs),
            severity="critical",
            evidence="a referenced-but-absent asset is the classic broken deliverable",
        )

        # (d) A non-empty but content-empty stub (valid HTML, no app, no text) must
        # be caught — it opens as a blank page (white-screen-adjacent hollow ship).
        stub = base / "stub"
        stub.mkdir()
        (stub / "index.html").write_text(
            "<!doctype html><html><head><title>TODO</title></head><body><!-- coming soon --></body></html>",
            encoding="utf-8",
        )
        r_stub = verify_web_deliverable(stub)
        rec.add(
            case="verifier catches a placeholder/stub entry (renders blank)",
            dimension=A,
            expected="ok=False with a 'placeholder/stub' reason",
            actual=f"ok={r_stub.ok} problems={r_stub.problems}",
            passed=(not r_stub.ok) and any("stub" in p for p in r_stub.problems),
            severity="high",
            evidence="non-empty file that renders nothing is still a hollow deliverable",
        )

        # (e) FALSE-POSITIVE GUARD: a real JS/canvas app has near-empty body text but
        # is clearly a working app — it must NOT be flagged as a stub.
        canvas = base / "canvas"
        canvas.mkdir()
        (canvas / "index.html").write_text(
            '<!doctype html><html><body><canvas id="c"></canvas><script src="game.js"></script></body></html>',
            encoding="utf-8",
        )
        (canvas / "game.js").write_text("/* game */", encoding="utf-8")
        r_canvas = verify_web_deliverable(canvas)
        rec.add(
            case="verifier does NOT false-flag a real canvas/JS app as a stub",
            dimension=A,
            expected="ok=True (canvas + script == a real app despite little body text)",
            actual=f"ok={r_canvas.ok} problems={r_canvas.problems}",
            passed=r_canvas.ok,
            severity="high",
            evidence="stub heuristic must be guarded by app-element + body-text signals",
        )

        # INTEGRATION: the verifier must be wired into the REAL finalize path, so a
        # broken web deliverable produces a user-facing warning on the result line
        # instead of a clean false "Created index.html". Drive the actual hook.
        try:
            from thomas.server.chat_delegation_deliverable import executability_warning

            warn_broken = executability_warning(broken, ["index.html", "styles.css"])
            warn_good = executability_warning(good, ["index.html", "styles.css", "src/game.js"])
            wired = bool(warn_broken) and ("game.js" in warn_broken) and (warn_good == "")
            actual = f"broken_warning={warn_broken!r} good_warning={warn_good!r}"
        except Exception as e:  # noqa: BLE001
            wired = False
            actual = f"not wired: {type(e).__name__}: {e}"
        rec.add(
            case="finalize path warns on a broken web deliverable (verify-before-done is wired)",
            dimension=A,
            expected="executability_warning() flags the broken app and stays silent on the good one",
            actual=actual,
            passed=wired,
            severity="critical",
            evidence="chat_delegation.py finalize -> executability_warning (wired both terminal exits)",
        )


if __name__ == "__main__":
    r = run()
    for row in r.rows:
        print(("PASS" if row.passed else "FAIL"), "|", row.case, "->", row.actual)
