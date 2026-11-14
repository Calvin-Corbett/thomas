"""The ratchet's run: once a day in the caged Thomas, and when you ask (POST /api/ratchet/run).

One landing at a time: a run first finds any hand-off a restart cut short, then
waits on any candidate already at your card, then takes up any repair a restart
left running (in the green it is still in), and hands nothing new to the promoter
until the one at your card is decided. A halt -- a landing that broke a test --
stops every run until the tests it names pass on dev's tip.

It runs only in a process whose account is ``THOMAS_RATCHET_ACCOUNT`` (the cage
account by default): its repairs are Build teams, which run a candidate's old
code as the server's account, and the two servers keep separate data folders,
so two drivers would keep two ledgers. A file lease in the ratchet's folder keeps
a second run of the same account out while one lasts.

``work`` is the scope that owns what keeps running, which in a server is the row's
(``thomas/server/rows/ratchet.py``). The daily loop and each started run are its tasks,
so turning the row off ends the loop, and a run counts as its work, so that press waits
for the run and Stop now ends it. A caller with no row gets a scope of its own.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import subprocess
from pathlib import Path
from typing import Any

from thomas.core.kernel import Kernel
from thomas.core.pause import paused
from thomas.forge.anvil import forge_code_projects
from thomas.server import green_checkout
from thomas.server.app_keys import APP_LOCAL_PORT, APP_PRAXIS_START_CODE_RUN, APP_SELF_BASE_URL
from thomas.server.ratchet.attempt import HELD, Context, DevMoved, Hooks, execution_id, side_at
from thomas.server.ratchet.candidates import Candidate, Census, discover, write_census
from thomas.server.ratchet.gitrepo import GitFailed, Repo
from thomas.server.ratchet.host import ACCOUNT_ENV, AUTORUN_ENV, autorun_enabled, host_refusal
from thomas.server.ratchet.landing import await_landing, reconcile, run_candidate
from thomas.server.ratchet.lease import lease
from thomas.server.ratchet.ledger import Ledger, ratchet_root
from thomas.server.ratchet.repair import Repairer, RepairHooks, resumable
from thomas.server.ratchet.report import read_report
from thomas.server.ratchet.stacking import note_once, onto_for

log = logging.getLogger(__name__)

DAILY_S = 24 * 3600.0
FIRST_RUN_DELAY_S = 15 * 60.0
DEFAULT_LIMIT = 5
DEV_MOVED_RETRIES = 2
# Recoverable errors from a run, including a timed-out git subprocess.
_RUN_FAULTS = (
    GitFailed,
    green_checkout.GreenUnavailable,
    DevMoved,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    subprocess.SubprocessError,
)


class RatchetService:
    def __init__(
        self,
        app: Any = None,
        *,
        work: Any = None,
        repo: Path | None = None,
        root: Path | None = None,
        hooks: Hooks | None = None,
        repair_hooks: RepairHooks | None = None,
        interval_s: float = DAILY_S,
        first_delay_s: float = FIRST_RUN_DELAY_S,
    ) -> None:
        self.app, self._repo, self.root = app, repo, root
        self.work = Kernel().root if work is None else work
        self.hooks = hooks or Hooks()
        self.repair_hooks = repair_hooks
        self.interval_s, self.first_delay_s = interval_s, first_delay_s
        self._daily: asyncio.Task[None] | None = None
        self._launched: asyncio.Future[dict[str, Any]] | None = None
        self._active = False
        self._last: dict[str, Any] = {}

    def folder(self) -> Path:
        return self.root or ratchet_root()

    def busy(self) -> bool:
        return self._active or (self._launched is not None and not self._launched.done())

    def report(self) -> dict[str, Any]:
        return {
            **read_report(self.folder()),
            "running": self.busy(),
            "last_run": dict(self._last),
            "host": host_refusal() or "here",
        }

    def launch(self, *, limit: int = DEFAULT_LIMIT, chat: str = "") -> bool:
        if self.busy():
            return False
        self._launched = self.work.task(functools.partial(self._guarded, limit, chat), name="run")
        return True

    async def _guarded(self, limit: int, chat: str) -> dict[str, Any]:
        async with self.work.busy():
            try:
                return await self.run_once(limit=limit, chat=chat)
            except _RUN_FAULTS as exc:
                log.warning("the ratchet run failed: %s", exc, exc_info=True)
                return {"status": "failed", "reason": str(exc)}

    async def run_once(self, *, limit: int = DEFAULT_LIMIT, chat: str = "") -> dict[str, Any]:
        refusal = host_refusal()
        if refusal:
            return {"status": "refused", "reason": refusal}
        blue = self._repo or forge_code_projects.thomas_source_repo_root()
        if blue is None:
            return {"status": "refused", "reason": "Thomas's own source checkout could not be found"}
        with lease(self.folder()) as held:
            if not held:
                return {"status": "busy", "reason": "another ratchet run holds the lease"}
            self._active = True
            try:
                self._last = await self._run(Repo(Path(blue)), limit=limit, chat=chat)
                return self._last
            finally:
                self._active = False

    async def _run(self, repo: Repo, *, limit: int, chat: str) -> dict[str, Any]:
        dev = await asyncio.to_thread(repo.sha, "refs/heads/dev")
        head = await asyncio.to_thread(repo.sha, "HEAD")
        if head != dev:
            return {
                "status": "refused",
                "reason": f"the running copy is at {head[:12]}, not dev's tip {dev[:12]}, so a green would start from the wrong commit",
            }
        if not self.hooks.runner_alive():
            why = "the caged runner is not answering, and a proof never runs outside the cage"
            return {"status": "refused", "reason": why}
        ctx = self._context(repo, chat)
        await asyncio.to_thread(reconcile, ctx)  # a hand-off a restart cut short
        halt = ctx.ledger.halted()
        if halt is not None and not await self._halt_cleared(ctx, halt, dev):
            return {"status": "halted", "reason": str(halt.get("reason") or "")}
        for event in ctx.ledger.awaiting():  # one submission at a time
            state = await await_landing(ctx, event)
            if state in ("awaiting_card", "halted"):
                return {"status": state, "candidate": str(event.get("candidate_ref") or "")}
        for event in ctx.ledger.repairing():  # a repair a restart cut short or a second look held, in its green
            state = await self._resume(ctx, event)
            if state in ("awaiting_card", "halted", HELD):
                return {"status": state, "candidate": str(event.get("candidate_ref") or "")}
        census = await asyncio.to_thread(discover, repo)
        await asyncio.to_thread(write_census, self.folder(), census)
        self._note_skipped(ctx, census)
        proven: list[dict[str, str]] = []
        spent = 0
        for cand in census.candidates:
            if spent >= limit:
                break
            state = await self._one(ctx, cand)
            if state is None:
                continue
            proven.append({"ref": cand.ref, "sha": cand.sha, "state": state})
            if state != "queued":  # a wait costs a screen, not one of the run's proof slots
                spent += 1
            if state in ("awaiting_card", "halted", HELD):  # a second look that cannot run now cannot for the next
                break
        return {"status": "ran", "proven": proven}

    async def _halt_cleared(self, ctx: Context, halt: dict[str, Any], dev: str) -> bool:
        """A halt holds until every test it names as failing passes on dev's tip, and every test it names as gone
        passes again, proven in a green of its own. Then it is kept beside the ledger and lifted."""
        failing = [str(n) for n in halt.get("failures") or []]
        gone = [str(n) for n in halt.get("missing") or []]
        files = sorted({n.split("::", 1)[0] for n in (*failing, *gone)})
        if not files:
            return False  # nothing to prove it by: it holds until you remove it (Open question 17)
        execution = execution_id("halt", str(halt.get("commit") or "0" * 7), dev)
        result = await side_at(ctx, dev, files, label="halt", execution=execution, expect_base=dev)
        still_failing = any(n in result.failing for n in failing)
        still_gone = any(n not in result.passing for n in gone)
        if result.unrunnable or still_failing or still_gone:
            return False
        ctx.ledger.clear_halt(f"every test it named passes on dev {dev[:12]}")
        return True

    async def _resume(self, ctx: Context, event: dict[str, Any]) -> str:
        """Take up a repair the last run left in ``repairing``, or record why it cannot be taken up.

        Proving the candidate again instead would call ``fresh_green`` on the same
        execution id, and that discards the green the Build team was working in.
        """
        found = await asyncio.to_thread(resumable, ctx, event)
        if found is None or ctx.repairs is None:
            why = (
                "a repair was cut short and the green it was in is gone, so it is proven again"
                if found is None
                else f"a repair was cut short, and {ctx.no_repair_reason}"
            )
            ctx.ledger.record(
                sha=str(event.get("candidate_sha") or ""),
                refs=list(event.get("refs") or []),
                dev_sha=str(event.get("dev_sha") or ""),
                state="queued",
                reason=why,
            )
            return "queued"
        att, cid = found
        return await ctx.repairs.resume(ctx, att, cid)

    async def _one(self, ctx: Context, cand: Candidate) -> str | None:
        """Prove one candidate if the ledger says so; None when it is not proven this run."""
        dev = await asyncio.to_thread(ctx.repo.sha, "refs/heads/dev")
        onto, waits, why = await asyncio.to_thread(onto_for, ctx.repo, ctx.ledger, cand, dev)
        if waits:  # stacked on work that has not landed, or never will
            note_once(ctx.ledger, cand, dev, waits, why)
            return None
        for _round in range(DEV_MOVED_RETRIES + 1):
            dev = await asyncio.to_thread(ctx.repo.sha, "refs/heads/dev")
            prove, _why = ctx.ledger.should_prove(cand.sha, dev)
            if not prove:
                return None
            try:
                return await run_candidate(ctx, cand, onto=onto)
            except DevMoved:
                why = "dev moved while it was being proven; it is proven again on the new tip"
                ctx.ledger.record(candidate=cand, dev_sha=dev, state="queued", reason=why)
            except (GitFailed, green_checkout.GreenUnavailable, OSError, subprocess.SubprocessError) as exc:
                # Git or a green failing is this machine's trouble, not the candidate's: recorded as a wait,
                # so it never counts towards MAX_REPORTS and the candidate is proven again next run.
                why = f"the attempt could not run here: {exc}"
                ctx.ledger.record(candidate=cand, dev_sha=dev, state="queued", reason=why)
                return "queued"
        return "queued"

    def _note_skipped(self, ctx: Context, census: Census) -> None:
        latest = ctx.ledger.latest()
        for skip in census.skipped:
            if skip.status == "not_for_ratchet" and latest.get(skip.sha, {}).get("state") != "not_for_ratchet":
                ctx.ledger.record(
                    sha=skip.sha,
                    refs=skip.refs,
                    dev_sha=census.dev_sha,
                    state="not_for_ratchet",
                    reason=skip.reason,
                )

    def _context(self, repo: Repo, chat: str) -> Context:
        ctx = Context(repo=repo, ledger=Ledger(self.folder() / "ledger.jsonl"), hooks=self.hooks, chat=chat)
        port = self._port()
        start_hook = self.app.get(APP_PRAXIS_START_CODE_RUN) if self.app is not None else None
        if start_hook is None:
            ctx.no_repair_reason = "no Build start hook is bound in this server"
        elif not port:
            ctx.no_repair_reason = "the server's own port is not known yet"
        else:
            ctx.repairs = Repairer(self.app, port, self.repair_hooks)
        return ctx

    def _port(self) -> int:
        if self.app is None:
            return 0
        port = int(self.app.get(APP_LOCAL_PORT) or 0)
        if not port:
            tail = str(self.app.get(APP_SELF_BASE_URL) or "").rsplit(":", 1)[-1]
            port = int(tail) if tail.isdigit() else 0
        return port

    async def _run_daily(self) -> None:
        await asyncio.sleep(self.first_delay_s)
        while True:
            if paused():  # Thomas is paused: skip this run and keep the timer
                await asyncio.sleep(self.interval_s)
                continue
            outcome = await self._guarded(DEFAULT_LIMIT, "")
            log.info("ratchet daily run: %s", outcome.get("status"))
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        if self._daily is None:
            self._daily = self.work.task(self._run_daily, name="daily run")


__all__ = [
    "ACCOUNT_ENV",
    "AUTORUN_ENV",
    "DAILY_S",
    "DEFAULT_LIMIT",
    "DEV_MOVED_RETRIES",
    "FIRST_RUN_DELAY_S",
    "RatchetService",
    "autorun_enabled",
    "host_refusal",
]
