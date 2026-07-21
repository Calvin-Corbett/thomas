"""CAP-072 — chat-platform operation of Thomas runs from Slack.

Proves the five verbs of the ChatOps facade against a hermetic fake transport
and fake runtime seams (no network, no credentials):

1. dispatch  -> invokes start_background_delegation seam + posts the run id;
2. steer     -> invokes apply_task_update(steer) seam + posts confirmation;
3. approve   -> invokes the governed-approval seam + posts approval;
   deny       -> invokes the seam with decision="deny";
   unauthorized approver -> rejected, seam NOT called;
4. diff review -> posts a Block Kit diff message;
5. request-to-merge -> invokes the governed-merge seam + posts a proof message
   built from the merge's validation evidence.

Also checks the real SlackChatTransport refuses to post (and never leaks a
token) when no credential is present.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.integrations.slack.chat_ops import (
    ChatOps,
    ChatOpsError,
    ChatOpsSeams,
    FakeChatTransport,
    SlackChatTransport,
    build_diff_blocks,
)


def _blocks_text(message: dict) -> str:
    """Flatten every text field in a posted message's blocks for assertions."""
    chunks: list[str] = [str(message.get("text") or "")]
    for block in message.get("blocks") or []:
        text = block.get("text")
        if isinstance(text, dict):
            chunks.append(str(text.get("text") or ""))
        elif isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


class _Spy:
    """Records the single call made to it and returns a preset value."""

    def __init__(self, returns=None):
        self.calls: list[tuple[tuple, dict]] = []
        self._returns = returns

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._returns

    @property
    def call(self) -> tuple[tuple, dict]:
        assert len(self.calls) == 1, f"expected exactly one call, got {len(self.calls)}"
        return self.calls[0]


def _seams(*, dispatch=None, steer=None, approve=None, merge=None) -> ChatOpsSeams:
    return ChatOpsSeams(
        dispatch=dispatch or _Spy(),
        steer=steer or _Spy(),
        approve=approve or _Spy(),
        merge=merge or _Spy(),
    )


# ── (1) DISPATCH ─────────────────────────────────────────────────────────────


def test_dispatch_invokes_delegation_seam_and_posts_run_id():
    async def fake_dispatch(prompt, *, session_id, mode, recent_messages=None, **kwargs):
        fake_dispatch.seen = {"prompt": prompt, "session_id": session_id, "mode": mode}
        return {"execution_id": "exec-77", "state": "executing"}

    transport = FakeChatTransport()
    ops = ChatOps(transport=transport, seams=_seams(dispatch=fake_dispatch), default_channel="C1")

    result = asyncio.run(ops.dispatch_run("build a login page", session_id="sess-1", mode="max"))

    assert fake_dispatch.seen == {"prompt": "build a login page", "session_id": "sess-1", "mode": "max"}
    assert result["execution_id"] == "exec-77"
    assert transport.last["channel"] == "C1"
    assert "exec-77" in _blocks_text(transport.last)


# ── (2) STEER ─────────────────────────────────────────────────────────────────


def test_steer_invokes_apply_task_update_seam_and_confirms():
    steer = _Spy(returns={"ok": True, "execution_id": "exec-77", "action": "steer"})
    transport = FakeChatTransport()
    ops = ChatOps(transport=transport, seams=_seams(steer=steer), default_channel="C1")

    result = asyncio.run(ops.steer_run("exec-77", "also add password reset", session_id="sess-1"))

    args, kwargs = steer.call
    assert args == ("sess-1", "exec-77", "also add password reset")
    assert result["ok"] is True
    text = _blocks_text(transport.last)
    assert "exec-77" in text
    assert "password reset" in text


def test_steer_surfaces_seam_error():
    steer = _Spy(returns={"ok": False, "error": "No running task matches reference 'exec-x'."})
    transport = FakeChatTransport()
    ops = ChatOps(transport=transport, seams=_seams(steer=steer), default_channel="C1")

    result = asyncio.run(ops.steer_run("exec-x", "do more", session_id="sess-1"))

    assert result["ok"] is False
    assert "No running task" in _blocks_text(transport.last)


# ── (3) APPROVE / DENY ────────────────────────────────────────────────────────


def test_approve_invokes_governed_seam_when_authorized():
    approve = _Spy(returns={"ok": True, "approval": {"status": "approved"}})
    transport = FakeChatTransport()
    ops = ChatOps(
        transport=transport,
        seams=_seams(approve=approve),
        authorized_approvers={"U_ADMIN"},
        default_channel="C1",
    )

    result = asyncio.run(ops.resolve_approval("appr-9", approver="U_ADMIN", decision="approve"))

    _args, kwargs = approve.call
    assert kwargs["decision"] == "approve"
    assert kwargs["approver"] == "U_ADMIN"
    assert result["authorized"] is True
    assert "approved" in _blocks_text(transport.last).lower()


def test_deny_invokes_governed_seam_with_deny_decision():
    approve = _Spy(returns={"ok": True, "approval": {"status": "rejected"}})
    transport = FakeChatTransport()
    ops = ChatOps(
        transport=transport,
        seams=_seams(approve=approve),
        authorized_approvers={"U_ADMIN"},
        default_channel="C1",
    )

    result = asyncio.run(ops.resolve_approval("appr-9", approver="U_ADMIN", decision="deny", reason="scope creep"))

    _args, kwargs = approve.call
    assert kwargs["decision"] == "deny"
    assert result["decision"] == "deny"
    assert "scope creep" in _blocks_text(transport.last)


def test_unauthorized_approver_is_rejected_and_seam_not_called():
    approve = _Spy(returns={"ok": True})
    transport = FakeChatTransport()
    ops = ChatOps(
        transport=transport,
        seams=_seams(approve=approve),
        authorized_approvers={"U_ADMIN"},
        default_channel="C1",
    )

    result = asyncio.run(ops.resolve_approval("appr-9", approver="U_INTRUDER", decision="approve"))

    assert result["ok"] is False
    assert result["authorized"] is False
    assert approve.calls == []  # governed seam must NOT run for an unauthorized approver
    assert "not authorized" in _blocks_text(transport.last).lower()


# ── (4) DIFF REVIEW ───────────────────────────────────────────────────────────


def test_diff_review_posts_block_kit_diff_message():
    transport = FakeChatTransport()
    ops = ChatOps(transport=transport, seams=_seams(), default_channel="C1")
    diff = "--- a/login.py\n+++ b/login.py\n-    return None\n+    return session"

    result = asyncio.run(ops.post_diff_review(title="Add session return", diff=diff, files=["login.py"]))

    block_types = [b.get("type") for b in result["blocks"]]
    assert "header" in block_types
    text = _blocks_text(transport.last)
    assert "```diff" in text
    assert "+    return session" in text
    assert "-    return None" in text
    assert "login.py" in text


def test_build_diff_blocks_is_pure_and_fenced():
    blocks = build_diff_blocks(title="t", diff="-a\n+b", summary="why")
    joined = "".join(b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "section")
    assert "why" in joined
    assert "```diff" in joined and "-a" in joined and "+b" in joined


# ── (5) REQUEST-TO-MERGE ──────────────────────────────────────────────────────


def test_request_to_merge_triggers_governed_merge_and_posts_proof():
    merge = _Spy(
        returns={
            "ok": True,
            "merged": True,
            "merge_ref": "lane-3",
            "commit": "abc1234",
            "validations": [
                {"command": "pytest -q", "passed": True, "evidence": "42 passed"},
                {"command": "ruff check", "passed": True, "evidence": "All checks passed"},
            ],
        }
    )
    transport = FakeChatTransport()
    ops = ChatOps(
        transport=transport,
        seams=_seams(merge=merge),
        authorized_approvers={"U_ADMIN"},
        default_channel="C1",
    )

    result = asyncio.run(ops.request_to_merge("lane-3", approver="U_ADMIN"))

    args, kwargs = merge.call
    assert args == ("lane-3",)
    assert kwargs["approver"] == "U_ADMIN"
    assert result["ok"] is True

    proof = _blocks_text(transport.last)
    # Proof carries the actual validation evidence, not just a bare "merged".
    assert "Validation evidence" in proof
    assert "pytest -q" in proof and "42 passed" in proof
    assert "ruff check" in proof and "All checks passed" in proof
    assert "lane-3" in proof


def test_request_to_merge_blocked_result_posts_failing_evidence():
    merge = _Spy(
        returns={
            "ok": False,
            "merged": False,
            "merge_ref": "lane-4",
            "validations": [{"command": "pytest -q", "passed": False, "evidence": "1 failed"}],
        }
    )
    transport = FakeChatTransport()
    ops = ChatOps(transport=transport, seams=_seams(merge=merge), default_channel="C1")

    result = asyncio.run(ops.request_to_merge("lane-4", approver="anyone"))

    assert result["ok"] is False
    proof = _blocks_text(transport.last)
    assert "blocked" in proof.lower()
    assert "1 failed" in proof


def test_unauthorized_merge_request_is_rejected_and_seam_not_called():
    merge = _Spy(returns={"ok": True, "merged": True})
    transport = FakeChatTransport()
    ops = ChatOps(
        transport=transport,
        seams=_seams(merge=merge),
        authorized_approvers={"U_ADMIN"},
        default_channel="C1",
    )

    result = asyncio.run(ops.request_to_merge("lane-3", approver="U_INTRUDER"))

    assert result["authorized"] is False
    assert merge.calls == []


# ── transport credential gating (no token -> honest refusal, no leak) ──────────


def test_slack_transport_refuses_without_token_and_redacts_repr():
    transport = SlackChatTransport(token_provider=lambda: "")
    with pytest.raises(ChatOpsError):
        asyncio.run(transport.post_message(channel="C1", text="hi"))
    # A real token must never appear in repr.
    secret = SlackChatTransport(token_provider=lambda: "xoxb-super-secret")
    assert "xoxb-super-secret" not in repr(secret)
    assert "redacted" in repr(secret)


def test_unwired_governance_seam_raises_clear_error():
    seams = ChatOpsSeams.live(app=None)  # approve/merge intentionally unwired
    ops = ChatOps(transport=FakeChatTransport(), seams=seams, default_channel="C1")
    with pytest.raises(ChatOpsError):
        asyncio.run(ops.resolve_approval("appr-1", approver="anyone"))
