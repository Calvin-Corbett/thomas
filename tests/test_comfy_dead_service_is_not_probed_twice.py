"""A ComfyUI that is not running costs one probe at most, and closing a service that booted nothing costs none.

The measured cost: every test that built the web app paid 4 s at teardown, because the app's cleanup called
ComfyStudioService.close(), which probed the default server twice (2 s each on a dead localhost port) for a
status nobody read.
"""

from __future__ import annotations

import urllib.error

import pytest

from thomas.marketplace.asset_studio import comfy_service
from thomas.marketplace.asset_studio.comfy_service import ComfyStudioService


def _calls(monkeypatch: pytest.MonkeyPatch, responses: dict[str, object]) -> list[str]:
    seen: list[str] = []

    def fake(url: str, *, timeout_s: float):
        seen.append(url)
        answer = responses[url.rsplit("/", 1)[-1]]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(comfy_service, "_json_get", fake)
    return seen


def test_a_refused_connection_skips_the_second_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    seen = _calls(monkeypatch, {"queue": refused, "system_stats": refused})
    status = ComfyStudioService._status_sync("http://127.0.0.1:8188", 1.0)
    assert seen == ["http://127.0.0.1:8188/queue"]
    assert status["running"] is False
    assert "refused" in status["error"]


def test_a_bare_refused_connection_also_skips_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _calls(monkeypatch, {"queue": ConnectionRefusedError(10061, "refused"), "system_stats": {}})
    status = ComfyStudioService._status_sync("http://127.0.0.1:8188", 1.0)
    assert len(seen) == 1 and status["running"] is False


@pytest.mark.parametrize(
    "first",
    [
        TimeoutError("timed out"),
        urllib.error.URLError(TimeoutError("timed out")),
        ConnectionResetError(10054, "reset"),
        urllib.error.URLError(ConnectionResetError(10054, "reset")),
        ConnectionAbortedError("aborted"),
    ],
)
def test_a_timeout_or_a_reset_on_the_first_probe_still_tries_the_second(monkeypatch, first) -> None:
    seen = _calls(monkeypatch, {"queue": first, "system_stats": {"system": {"python_version": "3.11"}}})
    status = ComfyStudioService._status_sync("http://127.0.0.1:8188", 1.0)
    assert [u.rsplit("/", 1)[-1] for u in seen] == ["queue", "system_stats"]
    assert status["running"] is True, "a busy but alive server is not reported down"


def test_a_server_that_answers_with_an_error_is_still_probed_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    not_found = urllib.error.HTTPError("http://x/queue", 404, "nope", None, None)  # type: ignore[arg-type]
    seen = _calls(monkeypatch, {"queue": not_found, "system_stats": {"system": {"python_version": "3.11"}}})
    status = ComfyStudioService._status_sync("http://127.0.0.1:8188", 1.0)
    assert [u.rsplit("/", 1)[-1] for u in seen] == ["queue", "system_stats"]
    assert status["running"] is True
    assert status["python_version"] == "3.11"


def test_a_live_server_is_probed_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _calls(monkeypatch, {"queue": {"queue_running": [1], "queue_pending": []}, "system_stats": {}})
    status = ComfyStudioService._status_sync("http://127.0.0.1:8188", 1.0)
    assert len(seen) == 2
    assert status["queue_running"] == 1


@pytest.mark.asyncio
async def test_closing_a_service_that_booted_nothing_probes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _calls(monkeypatch, {"queue": AssertionError("probed"), "system_stats": AssertionError("probed")})
    await ComfyStudioService().close()
    assert seen == []


@pytest.mark.asyncio
async def test_closing_a_service_with_a_managed_process_still_shuts_it_down(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ComfyStudioService()
    service._process = object()  # type: ignore[assignment]
    stopped: list[float] = []

    async def fake_shutdown(*, wait_timeout_s: float = 8.0, **_: object) -> dict[str, object]:
        stopped.append(wait_timeout_s)
        return {}

    monkeypatch.setattr(service, "shutdown", fake_shutdown)
    await service.close()
    assert stopped == [3.0]
