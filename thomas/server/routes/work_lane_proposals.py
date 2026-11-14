"""Routes behind the gate-change proposal card.

Thomas notices that one of its own gates should change and says so here. Nothing
in this module can change a gate on its own: approving one runs the breakglass
human authorization first, and the applied lane is still validated and re-proven,
so a human tap does not exempt the result from the red-proof rule.

The authorizer is injected. In the server it lazily imports
``scripts.breakglass_auth`` -- the same Windows Hello path every other owner
action uses -- and a test passes its own so no prompt appears.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from thomas.work.lanes.proposals import GateProposalStore, apply_proposal
from thomas.work.lanes.stats import GateStatsStore
from thomas.work.lanes.store import LaneStore, lane_data_dir

Authorizer = Callable[..., tuple[bool, str]]


def lane_stores(work_root: Any) -> tuple[GateProposalStore, GateStatsStore]:
    """One instance each, for the runtime that WRITES and the routes that READ.

    Two default-constructed stores agree only by accident of path and diverge the
    moment either is pointed somewhere else, so the caller makes them once here
    and hands the same objects to both sides.
    """

    lane_dir = lane_data_dir(work_root)
    return (
        GateProposalStore(path=lane_dir / "lane_proposals.json"),
        GateStatsStore(path=lane_dir / "lane_stats.json"),
    )


def breakglass_authorizer() -> Authorizer:
    """The real thing: a Windows Hello tap, or an already-open breakglass window."""

    def authorize(*, purpose: str, reason: str) -> tuple[bool, str]:
        try:
            from scripts.breakglass_auth import authorize_breakglass
        except ImportError as exc:  # pragma: no cover - packaging shape
            return False, f"breakglass authorization is unavailable: {exc}"
        result = authorize_breakglass(
            purpose=purpose,
            agent="work-lane-proposal",
            ticket=purpose,
            reason=reason,
        )
        return bool(getattr(result, "ok", False)), str(getattr(result, "message", ""))

    return authorize


def proposal_row(proposal: Any) -> dict[str, Any]:
    """What the card shows. The evidence travels with the ask, never just a verdict."""

    return {
        "id": proposal.id,
        "job_kind": proposal.job_kind,
        "kind": proposal.kind,
        "gate_id": proposal.gate_id,
        "rationale": proposal.rationale,
        "evidence": dict(proposal.evidence or {}),
        "status": proposal.status,
        "created_at": proposal.created_at,
        "decided_at": proposal.decided_at,
        "decided_reason": proposal.decided_reason,
    }


def register_lane_proposal_routes(
    app: web.Application,
    *,
    guard: Callable[[web.Request], None],
    expected_errors: Callable[..., Callable[[web.Request], Awaitable[web.StreamResponse]]],
    ok: Callable[..., web.Response],
    proposal_store: GateProposalStore | None = None,
    lane_store: LaneStore | None = None,
    authorize: Authorizer | None = None,
) -> None:
    proposals = proposal_store or GateProposalStore()
    lanes = lane_store or LaneStore()
    authorizer = authorize or breakglass_authorizer()

    async def _body(request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            # A missing or unparseable body means "no options", which every
            # handler here treats as valid. Anything else is a real fault and
            # must surface rather than read as an empty payload.
            return {}
        return payload if isinstance(payload, dict) else {}

    async def proposals_list(request: web.Request) -> web.Response:
        guard(request)
        job_kind = request.query.get("job_kind", "")
        return ok(
            proposals=[proposal_row(row) for row in proposals.pending(job_kind)],
            decided=[proposal_row(row) for row in proposals.decided(job_kind)[-10:]],
        )

    async def proposal_approve(request: web.Request) -> web.Response:
        guard(request)
        proposal_id = request.match_info["proposal_id"]
        payload = await _body(request)
        proposal = proposals.get(proposal_id)
        if proposal is None:
            return web.json_response({"ok": False, "error": "no such proposal"}, status=404)
        if proposal.status != "pending":
            return web.json_response(
                {"ok": False, "error": f"this proposal was already {proposal.status}"},
                status=409,
            )
        # Authorize and apply BEFORE recording the decision. A refused tap must
        # leave the proposal pending, not sitting in the ledger as approved with
        # nothing behind it.
        proposal.decided_by = str(payload.get("approved_by") or "")
        try:
            lane = apply_proposal(proposal, lanes, authorize=authorizer)
        except PermissionError as exc:
            return web.json_response({"ok": False, "code": "not_authorized", "error": str(exc)}, status=403)
        recorded = proposals.approve(
            proposal_id,
            approved_by=proposal.decided_by,
            reason=str(payload.get("reason") or ""),
        )
        return ok(proposal=proposal_row(recorded), lane_version=lane.version)

    async def proposal_reject(request: web.Request) -> web.Response:
        guard(request)
        payload = await _body(request)
        try:
            recorded = proposals.reject(
                request.match_info["proposal_id"],
                reason=str(payload.get("reason") or ""),
                rejected_by=str(payload.get("rejected_by") or ""),
            )
        except KeyError:
            return web.json_response({"ok": False, "error": "no such proposal"}, status=404)
        return ok(proposal=proposal_row(recorded))

    routes = [
        ("GET", "/api/work/lane-proposals", proposals_list),
        ("POST", "/api/work/lane-proposals/{proposal_id}/approve", proposal_approve),
        ("POST", "/api/work/lane-proposals/{proposal_id}/reject", proposal_reject),
    ]
    for method, path, handler in routes:
        app.router.add_route(method, path, expected_errors(handler))
