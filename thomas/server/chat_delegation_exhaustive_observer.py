"""Durable progress and receipt observation for one Max delegation run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_session import _execution_is_terminal, _normalize_record
from thomas.server.model_runtime_receipt import validate_model_runtime_receipt


class _ExhaustiveRunObserver:
    """Persist Max progress, model receipts, and independent quality reviews."""

    def __init__(
        self,
        *,
        execution_id: str,
        repo_root: Path,
        profile: str | None,
        model_id: str | None,
        specialist_id: str,
        bot: Any,
        emitter: _DelegationEmitter,
    ) -> None:
        self.execution_id = execution_id
        self.repo_root = repo_root
        self.profile = profile
        self.model_id = model_id
        self.specialist_id = specialist_id
        self.bot = bot
        self.emitter = emitter
        self.tools_used: list[str] = []
        self.model_runtime_receipts: list[dict[str, Any]] = []
        self.quality_reviews: list[dict[str, Any]] = []

    def should_stop(self) -> bool:
        return bool(
            task_bot_runtime.is_cancel_requested(self.execution_id, repo_root=self.repo_root)
            or _execution_is_terminal(self.execution_id, self.repo_root)
        )

    async def _progress(self, text: str) -> None:
        task_bot_runtime.update_execution(
            self.execution_id,
            progress_summary=text,
            actor=self.bot.name,
            repo_root=self.repo_root,
            force=True,
        )
        record = _normalize_record(task_bot_runtime.get_execution(self.execution_id, self.repo_root))
        await self.emitter.progress(record, specialist_id=self.specialist_id, bot=self.bot, text=text)

    async def on_tool(self, name: str) -> None:
        if name not in self.tools_used:
            self.tools_used.append(name)
        await self._progress(f"Using {name}…")

    async def on_stage(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "").replace("_", " ")
        await self._progress(f"Max: {stage}…")

    async def on_model_runtime(self, receipt: dict[str, Any]) -> None:
        pass_kind = str(receipt.get("pass_kind") or "model_pass")[:64]
        role = str(receipt.get("role") or "unknown")[:128]
        agent_name = str(receipt.get("agent_name") or role)[:128]
        pass_id = str(receipt.get("pass_id") or "unknown")[:64]
        runtime = validate_model_runtime_receipt(
            receipt,
            requested_profile=str(self.profile or ""),
            requested_model_id=str(self.model_id or ""),
        )
        if runtime is None:
            raise RuntimeError("exhaustive runtime receipt failed persistence validation")
        self.model_runtime_receipts.append(
            {
                "pass_id": pass_id,
                "pass_kind": pass_kind,
                "role": role,
                "agent_name": agent_name,
                "runtime": runtime,
            }
        )
        current = task_bot_runtime.get_execution(self.execution_id, self.repo_root) or {}
        runtime_profile = dict(current.get("runtime_profile") or {})
        runtime_profile.update(
            {
                "model_runtime": runtime,
                "model_runtime_receipts": list(self.model_runtime_receipts),
                "model_runtime_pass_count": len(self.model_runtime_receipts),
            }
        )
        task_bot_runtime.update_execution(
            self.execution_id,
            runtime_profile=runtime_profile,
            actor=self.bot.name,
            repo_root=self.repo_root,
            force=True,
        )

    async def on_quality_review(self, review: dict[str, Any]) -> None:
        self.quality_reviews.append(dict(review))
        current = task_bot_runtime.get_execution(self.execution_id, self.repo_root) or {}
        runtime_profile = dict(current.get("runtime_profile") or {})
        runtime_profile["exhaustive_quality_reviews"] = list(self.quality_reviews)
        task_bot_runtime.update_execution(
            self.execution_id,
            runtime_profile=runtime_profile,
            actor=self.bot.name,
            repo_root=self.repo_root,
            force=True,
        )


__all__ = ["_ExhaustiveRunObserver"]
