from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

Key = Tuple[str, str]  # (run_id, tool_call_id)

@dataclass
class PendingApproval:
    run_id: str
    tool_call_id: str
    session_id: str
    tool_name: str
    args_preview: Any
    reason: str
    created_at: float

class ApprovalBroker:
    """Async approval broker (stdlib only).

    Stores pending approvals keyed by (run_id, tool_call_id).
    """
    def __init__(self) -> None:
        self._futs: Dict[Key, asyncio.Future[bool]] = {}
        self._pending: Dict[Key, PendingApproval] = {}
        self._lock = asyncio.Lock()
        self._session_allow: Dict[str, set[str]] = {}

    def is_allowed_for_session(self, session_id: str, tool_name: str) -> bool:
        s = self._session_allow.get(session_id)
        return bool(s and tool_name in s)

    def allow_tool_for_session(self, session_id: str, tool_name: str) -> None:
        self._session_allow.setdefault(session_id, set()).add(tool_name)

    async def require(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        session_id: str,
        tool_name: str,
        args_preview: Any,
        reason: str,
        timeout_s: int,
    ) -> bool:
        key = (run_id, tool_call_id)

        if self.is_allowed_for_session(session_id, tool_name):
            return True

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        pa = PendingApproval(
            run_id=run_id,
            tool_call_id=tool_call_id,
            session_id=session_id,
            tool_name=tool_name,
            args_preview=args_preview,
            reason=reason,
            created_at=time.time(),
        )

        async with self._lock:
            # Avoid leaking old futures if a duplicate key is created
            old = self._futs.pop(key, None)
            if old and not old.done():
                old.set_result(False)
            self._futs[key] = fut
            self._pending[key] = pa

        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            await self.resolve(run_id=run_id, tool_call_id=tool_call_id, approved=False)
            return False

    async def resolve(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        approved: bool,
        allow_session_tool: bool = False,
        tool_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        key = (run_id, tool_call_id)
        async with self._lock:
            fut = self._futs.pop(key, None)
            pending = self._pending.pop(key, None)

        if allow_session_tool:
            tn = tool_name or (pending.tool_name if pending else None)
            sid = session_id or (pending.session_id if pending else None)
            if tn and sid:
                self.allow_tool_for_session(sid, tn)

        if fut is None:
            return False
        if not fut.done():
            fut.set_result(bool(approved))
        return True

    async def pending(self) -> List[Dict[str, Any]]:
        async with self._lock:
            items = list(self._pending.values())
        return [
            {
                "run_id": p.run_id,
                "tool_call_id": p.tool_call_id,
                "session_id": p.session_id,
                "tool_name": p.tool_name,
                "args_preview": p.args_preview,
                "reason": p.reason,
                "created_at": p.created_at,
            }
            for p in items
        ]
