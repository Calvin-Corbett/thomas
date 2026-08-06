"""The standalone preview tab may call out to the web; the embedded frame may not.

Measured (w2-code-network, w2-code-impossible): a generated app that fetches a
live feed or loads Google sign-in worked exactly as written and still opened
into its own error state, because every surface it could be viewed on carried
``connect-src 'self'`` or ``'none'``. Codex-parity behavior is that the
standalone tab -- the one the owner deliberately opens via "open in a new tab"
-- allows outbound **secure** connections, while the frames embedded beside the
chat stay locked.

Why this is honest rather than a hole, concretely:

* Thomas itself listens on **plaintext** ``http://127.0.0.1:8899``, and every
  sibling preview grant is plaintext ``http://127.0.0.1:<port>`` too. Granting
  only the secure schemes (``https:`` ``wss:``) therefore structurally excludes
  Thomas's own API and every other preview origin -- the two things the
  isolation exists to protect -- without enumerating them.
* The preview capability cookie is HttpOnly and scoped to the grant's own
  origin's requests; an outbound https fetch carries no Thomas credential.
* The document's identity is unchanged: ``default-src``, ``script-src``,
  ``form-action 'self'``, ``base-uri 'none'`` and the sandbox are untouched, so
  this widens exactly one thing -- where a script may *connect* -- and only on
  the surface whose whole point is "run the app for real".

The router tells the two surfaces apart by ``Sec-Fetch-Dest``: ``document`` is
a top-level navigation (the standalone tab), anything else -- ``iframe``,
``frame``, an absent header on an old client -- stays locked. Locked is the
default; the loosening requires positive evidence of a top-level navigation.
"""

from __future__ import annotations

import asyncio
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from aiohttp import web

from thomas.server.routes.deliverable_aiohttp import DeliverablePreviewService

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROUTE = REPO_ROOT / "thomas" / "server" / "routes" / "evolve_agent_routes.py"


def _csp(*, top_level: bool) -> str:
    service = DeliverablePreviewService()
    service.configure(main_origin="http://127.0.0.1:8899")
    response = web.Response(text="")
    service._apply_headers(response, top_level=top_level)
    return response.headers["Content-Security-Policy"]


def _connect_src(csp: str) -> str:
    directive = next(part.strip() for part in csp.split(";") if part.strip().startswith("connect-src"))
    return directive


class TestTheHeaderItself(unittest.TestCase):
    def test_the_embedded_frame_stays_locked_to_itself(self) -> None:
        assert _connect_src(_csp(top_level=False)) == "connect-src 'self'"

    def test_the_standalone_tab_may_call_out_over_secure_schemes(self) -> None:
        connect = _connect_src(_csp(top_level=True))

        assert "'self'" in connect
        assert "https:" in connect
        assert "wss:" in connect

    def test_the_loosening_cannot_reach_thomas_or_a_sibling_preview(self) -> None:
        """Thomas and every other preview grant are plaintext http on loopback.
        The tab's grant must name only secure schemes, so neither is reachable;
        ``http:`` or ``*`` here would quietly join every preview together AND
        open Thomas's own API to generated code."""
        connect = _connect_src(_csp(top_level=True))
        sources = set(connect.split()[1:])

        assert sources == {"'self'", "https:", "wss:"}

    def test_only_where_a_script_may_connect_is_widened(self) -> None:
        """The tab's document identity is the frame's document identity."""
        framed = _csp(top_level=False)
        tab = _csp(top_level=True)

        stripped = [part for part in tab.split(";") if not part.strip().startswith("connect-src")]
        framed_stripped = [part for part in framed.split(";") if not part.strip().startswith("connect-src")]
        assert stripped == framed_stripped
        assert "default-src 'self' data: blob:" in tab
        assert "form-action 'self'" in tab
        assert "base-uri 'none'" in tab


class TestTheRouterReadsTheNavigation(unittest.TestCase):
    def _dest(self, headers: dict[str, str]) -> bool:
        return DeliverablePreviewService._is_top_level_navigation(SimpleNamespace(headers=headers))

    def test_a_top_level_navigation_is_recognised(self) -> None:
        assert self._dest({"Sec-Fetch-Dest": "document"}) is True

    def test_an_embedded_frame_is_not(self) -> None:
        assert self._dest({"Sec-Fetch-Dest": "iframe"}) is False
        assert self._dest({"Sec-Fetch-Dest": "frame"}) is False

    def test_no_evidence_means_locked(self) -> None:
        """An old client that sends no Sec-Fetch-Dest gets the locked policy;
        the widening requires positive evidence, never its absence."""
        assert self._dest({}) is False


class TestTheServedResponse(unittest.IsolatedAsyncioTestCase):
    """Route-level: the real preview server answers a real GET differently for
    a tab navigation and an embedded frame."""

    async def asyncSetUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "index.html").write_text(
            "<script>fetch('https://api.example.com/feed')</script>", encoding="utf-8"
        )
        self.service = DeliverablePreviewService()
        self.service.configure(main_origin="http://127.0.0.1:8899")
        self.addAsyncCleanup(self.service.stop)
        self.addCleanup(self._tmp.cleanup)
        url = await self.service.preview_directory_url(
            subject_id="code:test",
            workspace=self.root,
            tail="index.html",
            allowed_files={"index.html"},
        )
        self.origin = url.rsplit("/__enter/", 1)[0]
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        await self._get(url)  # handshake sets the capability cookie

    async def _get(self, target: str, headers: dict[str, str] | None = None) -> str:
        """Fetch off-loop: urllib is synchronous and the preview server runs in
        THIS event loop, so calling it inline deadlocks."""

        def fetch() -> str:
            request = urllib.request.Request(target, headers=headers or {})
            try:
                with self._opener.open(request, timeout=10) as response:
                    return str(response.headers.get("Content-Security-Policy") or "")
            except urllib.error.HTTPError as exc:
                raise AssertionError(f"preview refused {target}: {exc.code}") from exc

        return await asyncio.to_thread(fetch)

    async def test_a_tab_navigation_is_served_the_outbound_policy(self) -> None:
        csp = await self._get(f"{self.origin}/index.html", {"Sec-Fetch-Dest": "document"})
        assert _connect_src(csp) == "connect-src 'self' https: wss:"

    async def test_an_embedded_frame_is_served_the_locked_policy(self) -> None:
        csp = await self._get(f"{self.origin}/index.html", {"Sec-Fetch-Dest": "iframe"})
        assert _connect_src(csp) == "connect-src 'self'"

    async def test_a_headerless_client_is_served_the_locked_policy(self) -> None:
        csp = await self._get(f"{self.origin}/index.html")
        assert _connect_src(csp) == "connect-src 'self'"


class TestTheArtifactFileRouteStaysShut(unittest.TestCase):
    def test_the_direct_artifact_response_still_grants_no_network(self) -> None:
        """`_artifact_file_response` serves downloads and the capability route's
        decorative frames -- never the standalone tab, whose HTML 302s through
        the preview service. It keeps ``connect-src 'none'``."""
        text = ARTIFACT_ROUTE.read_text(encoding="utf-8")

        assert "connect-src 'none'" in text


if __name__ == "__main__":
    unittest.main()
