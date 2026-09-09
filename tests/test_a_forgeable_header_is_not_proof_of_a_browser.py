"""What may stand in for the CSRF token, and where it may not.

Correction first, because the original version of this file told the story
wrong. Every commit up to 89df3f5f required ``X-CSRF-Token`` unconditionally on
a mutating control-plane request. The "affirmative same-origin browser
evidence" path was introduced in the same unreleased change these tests were
written against, so the ``Sec-Fetch-Site``-only hole reproduced here never
shipped to anyone, and the first fix — requiring ``Origin`` — narrowed a new
substitute rather than closing an old hole. It was still a net loosening.

Where the evidence path earns its place: the attack a CSRF token exists to stop
is a page on another origin making the browser POST to this loopback server.
A browser sets ``Origin`` itself and a page cannot override it, so a
same-origin ``Origin`` is real evidence against that attack — and the UI, which
has no token client, needs it.

Where it does not: ``Origin`` proves the request came from a browser only if a
browser sent it, and a local process can write any header. On loopback that is
tolerable, since such a process could reach the server anyway. In remote mode
it is not — there it let a forged loopback ``Origin`` through without the
secret. Remote therefore keeps the unconditional requirement.

So: token always sufficient; browser-proven same-origin sufficient on loopback
only; ``Sec-Fetch-Site`` alone never sufficient, because with no ``Origin`` to
compare ``_require_same_origin_browser_request`` returns without raising.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestForgeableBrowserEvidence(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_a_same_origin_claim_without_an_origin_header_is_not_evidence(self):
        """The forged case: the header any client can set, and nothing else."""
        with patch.dict("os.environ", {"THOMAS_MUTATING_CSRF_TOKEN": "audit-secret"}):
            resp = await self.client.post(
                "/api/session/new",
                headers={"Sec-Fetch-Site": "same-origin"},
            )
        body = await resp.text()
        self.assertEqual(resp.status, 403, body)
        self.assertIn("Missing X-CSRF-Token", body)

    async def test_the_real_ui_request_carrying_origin_still_succeeds(self):
        """Local mode keeps the browser path: the UI has no token client.

        A page on another origin cannot forge this header — the browser sets
        Origin itself — so a same-origin Origin is genuine evidence against the
        attack CSRF tokens exist to stop.
        """
        origin = str(self.client.make_url("/")).rstrip("/")
        with patch.dict("os.environ", {"THOMAS_MUTATING_CSRF_TOKEN": "audit-secret"}):
            resp = await self.client.post(
                "/api/session/new",
                headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
            )
        self.assertEqual(resp.status, 200, await resp.text())

    async def test_the_explicit_token_remains_sufficient_on_its_own(self):
        """A non-browser client with the secret needs no browser headers."""
        with patch.dict("os.environ", {"THOMAS_MUTATING_CSRF_TOKEN": "audit-secret"}):
            resp = await self.client.post(
                "/api/session/new",
                headers={"X-CSRF-Token": "audit-secret"},
            )
        self.assertEqual(resp.status, 200, await resp.text())

    async def test_a_valid_token_from_a_foreign_host_is_still_refused(self):
        """The second layer, pinned by a request that actually reaches it.

        The previous version of this test sent no token and no Origin, so the
        CSRF guard rejected it long before the API-access check ran: it asserted
        403 and would have passed unchanged with authz_guard_mutating_api
        deleted. A test that cannot fail for the reason it names is decoration.
        This one presents the correct secret, so only the host check can refuse.
        """
        with patch.dict("os.environ", {"THOMAS_MUTATING_CSRF_TOKEN": "audit-secret"}):
            resp = await self.client.post(
                "/api/session/new",
                headers={"X-CSRF-Token": "audit-secret", "Host": "evil.example"},
            )
        body = await resp.text()
        self.assertEqual(resp.status, 403, body)
        self.assertNotIn("X-CSRF-Token", body)


class TestRemoteModeTakesNoHeaderAsEvidence(AioHTTPTestCase):
    """The half that really was a loosening.

    In remote mode the caller is not necessarily a browser on this machine, so
    a forged loopback Origin plus a stolen bearer token got through without the
    CSRF secret — weaker than every commit before it. Remote keeps the
    unconditional requirement; only loopback accepts the browser-proven path.
    """

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="remote", api_token="remote-api-token"),
        )
        return create_app(cfg)

    async def test_a_forged_loopback_origin_is_refused_in_remote_mode(self):
        origin = str(self.client.make_url("/")).rstrip("/")
        with patch.dict("os.environ", {"THOMAS_MUTATING_CSRF_TOKEN": "audit-secret"}):
            resp = await self.client.post(
                "/api/session/new",
                headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
            )
        body = await resp.text()
        self.assertEqual(resp.status, 403, body)
        self.assertIn("Missing X-CSRF-Token", body)

    async def test_the_secret_still_works_in_remote_mode(self):
        with patch.dict("os.environ", {"THOMAS_MUTATING_CSRF_TOKEN": "audit-secret"}):
            resp = await self.client.post(
                "/api/session/new",
                headers={"X-CSRF-Token": "audit-secret"},
            )
        # Remote mode still demands API auth after CSRF; the point here is only
        # that the CSRF layer accepted the secret rather than refusing it.
        self.assertNotIn("X-CSRF-Token", await resp.text())
