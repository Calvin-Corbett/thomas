"""A page must not be served under rules stricter than the ones it was checked under.

Thomas verifies a generated page in a real browser and then serves that same
page back to the owner from a different origin with a different Content-Security
-Policy. When the serving policy is the stricter of the two, a page can pass
every check and still be broken the moment it is opened -- and nothing reports
it, because both halves did exactly what they were told.

That is not hypothetical. The owner asked for a calculator app. Thomas built
`Nova`, verification returned `completed`, and opening it produced `Error` for
`12 + 8`. The cause was neither the maths nor the markup:

* the browser smoke serves pages with ``'unsafe-eval'`` allowed, so
  ``Function('return (12+8)')()`` -- the ordinary way a calculator evaluates a
  typed expression -- worked during verification;
* the deliverable preview served the same file **without** it, so the identical
  call threw ``EvalError: Evaluating a string as JavaScript violates the
  following Content Security Policy directive`` and the page's own catch block
  turned that into ``Error`` on screen.

Confirmed by injecting an inline ``<script>`` into the live preview, which is
subject to the page's CSP, rather than by evaluating from devtools, which is
not -- the devtools console bypasses CSP and reported success for the very call
the page could not make.

Blocking eval buys nothing here. Both policies already allow
``'unsafe-inline'``, so a hostile page can execute whatever JavaScript it likes
by simply writing it out; refusing to evaluate a *string* removes no capability
it does not already have. It only breaks honest pages -- calculators, formula
editors, graphing tools, anything that builds an expression at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_ASSETS = REPO_ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke_assets.py"
PREVIEW = REPO_ROOT / "thomas" / "server" / "routes" / "deliverable_aiohttp.py"
# The artifact route left evolve_agent_routes.py when that module was split for
# the 1500-line ceiling (2026-08-10). It took its Content-Security-Policy with
# it, unchanged; only the address moved. The old module now declares no CSP at
# all, so pointing here is what keeps this guard looking at the real header
# rather than passing against an empty file.
ARTIFACT_ROUTE = REPO_ROOT / "thomas" / "server" / "routes" / "evolve_agent_artifact_routes.py"

_SCRIPT_SRC_RE = re.compile(r"script-src(?P<sources>[^;\"']*(?:['\"][^;]*?)*?)(?=;|\"|')")


def _script_src_directives(path: Path) -> list[str]:
    """Every ``script-src`` directive written in a source file."""
    text = path.read_text(encoding="utf-8")
    return [match.group(0) for match in re.finditer(r"script-src[^;\"]*", text)]


def test_the_checker_allows_evaluating_an_expression() -> None:
    """The premise. If the smoke ever stops allowing it, this test is the wrong
    shape and the comparison below means something different."""
    directives = _script_src_directives(SMOKE_ASSETS)

    assert directives, "the browser smoke no longer declares a script-src"
    assert any("'unsafe-eval'" in directive for directive in directives)


def test_the_preview_serves_pages_the_checker_would_pass() -> None:
    """The bug: the viewer was stricter than the checker.

    A calculator that verification proved works must not fail on the screen it
    is handed to, for a reason that is entirely Thomas's own configuration.
    """
    directives = _script_src_directives(PREVIEW)

    assert directives, "the deliverable preview no longer declares a script-src"
    for directive in directives:
        assert "'unsafe-eval'" in directive, (
            "the deliverable preview refuses to run a page the browser smoke "
            f"just certified: {directive}"
        )


def test_the_artifact_route_serves_pages_the_checker_would_pass() -> None:
    """The other way the owner opens a build, and it had the same gap."""
    directives = [d for d in _script_src_directives(ARTIFACT_ROUTE) if "'self'" in d]

    assert directives, "the artifact route no longer declares a script-src"
    for directive in directives:
        assert "'unsafe-eval'" in directive, (
            f"the artifact route is stricter than the check the page passed: {directive}"
        )


def test_the_preview_still_refuses_the_things_that_actually_matter() -> None:
    """Widening one directive must not quietly widen the rest.

    These are the restrictions doing real work: a generated page cannot call
    out to the network, cannot be framed by an arbitrary site, cannot load
    plugins, and cannot retarget relative URLs.
    """
    text = PREVIEW.read_text(encoding="utf-8")

    assert "connect-src 'self'" in text
    assert "object-src 'none'" in text
    assert "base-uri 'none'" in text
    assert "form-action 'self'" in text
    assert "sandbox allow-scripts" in text
