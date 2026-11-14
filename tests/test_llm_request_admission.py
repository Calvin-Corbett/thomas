"""Exercise actual httpx stream contexts with no provider account."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from thomas.core.llm_request_admission import (
    RequestAdmission,
    RoutedProviderAdmission,
    SharedProviderAdmission,
    admission_key,
    admitted_stream,
    shared_provider_admission,
)
from thomas.core.provider_pacing import ProviderPacer


@pytest.mark.asyncio
async def test_failover_attempt_uses_its_own_credential_queue(monkeypatch):
    import thomas.core.llm_request_admission as admission_module

    controllers = {}

    def factory(key, *, team, lane):
        controllers[key] = RequestAdmission(ceiling=1)
        return controllers[key]

    monkeypatch.setattr(admission_module, "shared_provider_admission", factory)
    primary = SimpleNamespace(provider="first", api_key="secret-one", base_url="https://first")
    fallback = SimpleNamespace(provider="second", api_key="secret-two", base_url="https://second")
    router = RoutedProviderAdmission(team="one")
    owner = SimpleNamespace(_request_admission=router, config=primary)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        async with admitted_stream(owner, client, "GET", "https://example.test/first"):
            pass
        owner.config = fallback
        async with admitted_stream(owner, client, "GET", "https://example.test/second"):
            pass
    assert len(controllers) == 2
    assert all(value.snapshot()["settled"] == 1 for value in controllers.values())
    assert "secret-one" not in admission_key(primary)
    assert admission_key(SimpleNamespace(provider="openai_codex", api_key="rotating-token")) == "openai_codex"
    router.close()


@pytest.mark.asyncio
async def test_hundred_loops_keep_streams_bounded_and_all_settle():
    admission = RequestAdmission(ceiling=4)
    seen = []

    async def serve(request):
        seen.append(request.url.path)
        return httpx.Response(200, content=b"done")

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:

        async def worker(index):
            async with admitted_stream(
                SimpleNamespace(_request_admission=admission), client, "GET", f"https://test/{index}"
            ) as response:
                await asyncio.sleep(0.003)
                assert await response.aread() == b"done"

        await asyncio.gather(*(worker(index) for index in range(100)))
    result = admission.snapshot()
    assert len(seen) == result["admitted"] == result["settled"] == 100
    assert result["peak_inflight"] == 4 and result["inflight"] == result["waiting"] == 0
    assert not result["failed"]


@pytest.mark.asyncio
async def test_queued_cancellation_and_close_do_not_leak_tickets():
    admission = RequestAdmission(ceiling=1)
    held = await admission.acquire()
    cancelled = asyncio.create_task(admission.acquire())
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    pending = asyncio.create_task(admission.acquire())
    await asyncio.sleep(0)
    admission.close()
    with pytest.raises(RuntimeError, match="closed"):
        await pending
    admission.release(held)
    assert admission.snapshot()["waiting"] == admission.snapshot()["inflight"] == 0
    with pytest.raises(RuntimeError, match="closed"):
        await admission.acquire()


@pytest.mark.asyncio
async def test_fifo_and_rate_refusal_adapts_once_for_same_generation():
    admission = RequestAdmission(ceiling=4)
    held = [await admission.acquire() for _ in range(4)]
    pending = [asyncio.create_task(admission.acquire()) for _ in range(3)]
    await asyncio.sleep(0)
    for token in held:
        admission.release(token, status=429, retry_after=0.03)
    assert admission.snapshot()["limit"] == 2
    await asyncio.sleep(0.01)
    assert not any(task.done() for task in pending)
    a, b = await asyncio.gather(*pending[:2])
    assert a < b and not pending[2].done()
    admission.release(a, status=200, complete=True)
    c = await pending[2]
    assert c > b
    for token in (b, c):
        admission.release(token, status=200, complete=True)
        admission.release(token, status=200, complete=True)
    assert admission.snapshot()["admitted"] == admission.snapshot()["settled"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dispatch", "body", "cancel"])
async def test_dispatch_body_failure_and_cancellation_release_after_close(failure):
    admission = RequestAdmission(ceiling=1)
    entered = asyncio.Event()
    closed = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            if failure == "body":
                raise httpx.ReadError("broken body")
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            assert admission.snapshot()["inflight"] == 1
            closed.set()

    async def serve(request):
        if failure == "dispatch":
            raise httpx.ConnectError("no connection")
        return httpx.Response(200, stream=Body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:

        async def run():
            async with admitted_stream(
                SimpleNamespace(_request_admission=admission), client, "GET", "https://test"
            ) as response:
                await response.aread()

        task = asyncio.create_task(run())
        if failure == "cancel":
            await entered.wait()
            task.cancel()
        with pytest.raises((httpx.TransportError, asyncio.CancelledError)):
            await task
    assert failure == "dispatch" or closed.is_set()
    assert admission.snapshot()["admitted"] == admission.snapshot()["settled"] == 1
    assert admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_no_admission_retains_existing_request_arguments():
    async def serve(request):
        assert request.headers["X-Test"] == "preserved"
        assert request.url.query == b"a=b"
        return httpx.Response(200, content=b"ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        async with admitted_stream(
            SimpleNamespace(), client, "GET", "https://test", params={"a": "b"}, headers={"X-Test": "preserved"}
        ) as response:
            assert await response.aread() == b"ok"


@pytest.mark.asyncio
async def test_old_generation_successes_do_not_raise_post_refusal_limit():
    admission = RequestAdmission(ceiling=20)
    tickets = [await admission.acquire() for _ in range(20)]
    admission.release(tickets[0], status=429, retry_after=0)
    assert admission.snapshot()["limit"] == 10
    for ticket in tickets[1:9]:
        admission.release(ticket, status=200, complete=True)
    assert admission.snapshot()["limit"] == 10, "Old generation responses must not prove recovery at the new limit"


@pytest.mark.asyncio
async def test_two_build_teams_share_one_provider_pacer_and_keep_interactive_room():
    first = shared_provider_admission("test-shared-account-capacity", team="team-one")
    second = shared_provider_admission("test-shared-account-capacity", team="team-two")
    assert first.pacer is second.pacer

    async def serve(_request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=b"ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:

        async def run(index):
            admission = first if index % 2 else second
            async with admitted_stream(
                SimpleNamespace(_request_admission=admission), client, "GET", f"https://test/{index}"
            ) as response:
                assert await response.aread() == b"ok"

        await asyncio.gather(*(run(index) for index in range(100)))
    report = first.pacer.report()
    assert first.snapshot()["admitted"] + second.snapshot()["admitted"] == 100
    assert first.snapshot()["settled"] + second.snapshot()["settled"] == 100
    assert 1 < report["peak_inflight"] <= 96
    assert report["reserved_interactive"] == 4
    assert report["inflight_now"] == report["waiting_now"] == 0
    first.close()
    token = await second.acquire()
    second.release(token, status=200, complete=True)
    second.close()


@pytest.mark.asyncio
async def test_interactive_request_uses_reserved_provider_capacity():
    pacer = ProviderPacer(
        ceiling=6,
        floor=1,
        increase_every=8,
        retry_after_default_s=0,
        retry_after_max_s=1,
        reserved_interactive=2,
    )
    workers = [await pacer.acquire(f"worker-{index}") for index in range(4)]
    fifth = asyncio.create_task(pacer.acquire("worker-5"))
    await asyncio.sleep(0.02)
    assert not fifth.done()
    interactive = await asyncio.wait_for(pacer.acquire("manager", lane="interactive"), timeout=0.2)
    assert interactive["slot"] and pacer.report()["inflight_now"] == 5
    pacer.release("manager", kind="clean")
    pacer.release("worker-0", kind="clean")
    assert (await asyncio.wait_for(fifth, timeout=0.2))["slot"]
    for index in range(1, 5):
        pacer.release(f"worker-{index}", kind="clean")
    assert pacer.report()["inflight_now"] == 0


@pytest.mark.asyncio
async def test_refusal_waits_only_its_builder_and_old_success_cannot_raise_cap():
    pacer = ProviderPacer(
        ceiling=4,
        floor=1,
        increase_every=1,
        retry_after_default_s=0.1,
        retry_after_max_s=1,
        poll_s=0.001,
    )
    import time

    old_sent = time.monotonic()
    await pacer.acquire("refused")
    await pacer.acquire("old-peer")
    pacer.release("refused", kind="provider_refusal", sent_mono=old_sent, retry_after_raw=0.1, status=429)
    assert pacer.report()["cap_now"] == 2
    pacer.release("old-peer", kind="clean", sent_mono=old_sent)
    assert pacer.report()["cap_now"] == 2
    waiting = asyncio.create_task(pacer.acquire("refused"))
    await asyncio.sleep(0.02)
    assert not waiting.done()
    # Windows monotonic clocks can advance in coarse ticks; this peer's send
    # must be measurably later than the refusal to count as recovery evidence.
    await asyncio.sleep(0.02)
    peer = await asyncio.wait_for(pacer.acquire("new-peer"), timeout=0.05)
    assert peer["slot"]
    pacer.release("new-peer", kind="clean", sent_mono=time.monotonic())
    assert pacer.report()["cap_now"] == 3
    assert (await asyncio.wait_for(waiting, timeout=0.2))["slot"]
    pacer.release("refused", kind="clean")
    assert pacer.report()["inflight_now"] == 0


@pytest.mark.asyncio
async def test_repeated_cancel_during_http_close_keeps_slot_until_close():
    admission = RequestAdmission(ceiling=1)
    reading, closing, release_close, closed = [asyncio.Event() for _ in range(4)]

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            reading.set()
            await asyncio.Event().wait()
            yield b"never"

        async def aclose(self):
            closing.set()
            await release_close.wait()
            closed.set()

    async def serve(_request):
        return httpx.Response(200, stream=Body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:

        async def consume():
            async with admitted_stream(
                SimpleNamespace(_request_admission=admission), client, "GET", "https://fixture.invalid"
            ) as response:
                await response.aread()

        task = asyncio.create_task(consume())
        await reading.wait()
        task.cancel()
        await closing.wait()
        task.cancel()
        await asyncio.sleep(0)
        snapshot = admission.snapshot()
        release_close.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert snapshot["inflight"] == 1 or closed.is_set(), (
            "Admission was released while the response still needed closing"
        )
        assert closed.is_set(), "Second cancellation interrupted resource cleanup"
