from __future__ import annotations

"""SQLAlchemy Session scoping hook to enforce workspace isolation by default.

This is a guardrail, not a magical force-field:
- ORM queries are scoped when session.info["workspace_id"] is set.
- Core SQL / raw SQL that bypasses ORM won't be automatically scoped.
"""

from typing import Set, Type

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql.dml import Delete, Update

_REGISTERED = False


def register_workspace_scoping() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @event.listens_for(Session, "before_flush")
    def _set_workspace_id(session: Session, flush_context, instances):  # noqa: ARG001
        ws_id = session.info.get("workspace_id")
        if not ws_id:
            return
        for obj in session.new:
            if hasattr(obj, "workspace_id") and obj.workspace_id in (None, ""):
                try:
                    obj.workspace_id = ws_id
                except Exception:
                    pass

    @event.listens_for(Session, "do_orm_execute")
    def _enforce_workspace(orm_execute_state):
        ws_id = orm_execute_state.session.info.get("workspace_id")
        if not ws_id:
            return

        stmt = orm_execute_state.statement

        # UPDATE/DELETE: constrain by workspace_id if the target table has it.
        if isinstance(stmt, Update):
            table = stmt.table
            if hasattr(table.c, "workspace_id"):
                orm_execute_state.statement = stmt.where(table.c.workspace_id == ws_id)
            return

        if isinstance(stmt, Delete):
            table = stmt.table
            if hasattr(table.c, "workspace_id"):
                orm_execute_state.statement = stmt.where(table.c.workspace_id == ws_id)
            return

        # SELECT: add criteria for mapped entities with workspace_id attribute.
        if not orm_execute_state.is_select:
            return

        entities: set[type] = set()
        try:
            for desc in getattr(stmt, "column_descriptions", []) or []:
                ent = desc.get("entity")
                if ent is not None and hasattr(ent, "workspace_id"):
                    entities.add(ent)
        except Exception:
            return

        if not entities:
            return

        for ent in entities:
            stmt = stmt.options(
                with_loader_criteria(
                    ent,
                    lambda cls: cls.workspace_id == ws_id,  # noqa: E731
                    include_aliases=True,
                )
            )
        orm_execute_state.statement = stmt
