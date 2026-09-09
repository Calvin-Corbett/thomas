"""Own live Mission tasks until their cancellation cleanup has finished."""

from __future__ import annotations

import asyncio


class CancellationUnconfirmed(RuntimeError):
    """Cancellation was requested, but the running work has not confirmed stop."""


async def drain_task(task):
    """Keep ownership through repeated cancellation until cleanup really ends."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def gather_owned(coroutines):
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    group = asyncio.gather(*tasks, return_exceptions=True)
    interrupted = False
    try:
        results = await asyncio.shield(group)
    except asyncio.CancelledError:
        interrupted = True
        for task in tasks:
            JobExecutionTasks._request_stop(task)
        results = await drain_task(group)
    # A cleanup failure takes precedence over the cancellation that exposed it.
    for result in results:
        if isinstance(result, CancellationUnconfirmed):
            raise result
    if interrupted:
        raise asyncio.CancelledError
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


class JobExecutionTasks:
    def __init__(self, store):
        self.store = store
        self.active: dict[str, asyncio.Task] = {}
        self.unconfirmed: dict[str, str] = {}
        self.cancel_wait_s = 25.0

    @staticmethod
    def _request_stop(task: asyncio.Task) -> None:
        # A second cancel can interrupt the first cancellation's cleanup.
        if not task.done() and not task.cancelling():
            task.cancel()

    async def run(self, job, handler) -> None:
        task = asyncio.create_task(handler(job))
        self.active[job.id] = task
        try:
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=0.2)
                    if not task.done() and self.store.get_job(job.id).cancelled:
                        self._request_stop(task)
                await task
            except asyncio.CancelledError:
                self._request_stop(task)
                try:
                    await drain_task(task)
                except asyncio.CancelledError:
                    pass
                if not self.store.get_job(job.id).cancelled:
                    raise
            if self.store.get_job(job.id).status == "cancelling":
                self.store.cancel_job(job.id, actor="engine")
        except CancellationUnconfirmed as exc:
            self.unconfirmed[job.id] = str(exc)
            raise
        finally:
            if not task.done():
                self._request_stop(task)
                try:
                    await drain_task(task)
                except asyncio.CancelledError:
                    pass
            if self.active.get(job.id) is task:
                self.active.pop(job.id, None)

    async def cancel(self, job_id: str, *, actor: str):
        job = self.store.get_job(job_id)
        task = self.active.get(job_id)
        pending = task is not None or job.status in {"running", "cancelling"}
        self.store.cancel_job(job_id, actor=actor, pending=pending)
        if task is not None:
            self._request_stop(task)
            done, _ = await asyncio.wait({task}, timeout=self.cancel_wait_s)
            if not done:
                raise CancellationUnconfirmed(
                    "Cancellation is still in progress; the runtime is waiting for worker cleanup"
                )
            try:
                await drain_task(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
            except CancellationUnconfirmed as exc:
                self.unconfirmed[job_id] = str(exc)
                raise
        elif self.store.get_job(job_id).status == "cancelling":
            self.unconfirmed[job_id] = "The running Mission is not owned by this runtime; stop is unconfirmed"
        if job_id in self.unconfirmed:
            raise CancellationUnconfirmed(self.unconfirmed[job_id])
        self.store.cancel_job(job_id, actor=actor)
        return self.store.get_job(job_id)
