"""Per-job connector-account bindings for Work."""

from __future__ import annotations

import copy
from typing import Any

from .connectors import canonical_connector_scopes, installed_connector_ids
from .validation import (
    WorkConflictError,
    WorkNotFoundError,
    WorkValidationError,
    clean_string_list,
    clean_text,
    new_id,
    require_safe_id,
    utc_now_iso,
)


class WorkConnectorBindingMixin:
    def bind_account(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = require_safe_id(payload.get("account_id"), field="account_id")
        requested_scopes = clean_string_list(payload.get("scopes"), field="scopes")
        outbound_approved = payload.get("approve_outbound", False)
        if not isinstance(outbound_approved, bool):
            raise WorkValidationError("approve_outbound must be true or false")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            account = state["connector_accounts"].get(account_id)
            if not isinstance(account, dict) or account.get("status") == "archived":
                raise WorkNotFoundError("active connector account not found")
            if account.get("provider") not in installed_connector_ids():
                raise WorkConflictError("connector provider is not installed")
            scopes = canonical_connector_scopes(account.get("provider"), requested_scopes)
            if any(scope in {"send", "write"} for scope in scopes) and not outbound_approved:
                raise WorkValidationError("send and write scopes require explicit outbound approval")
            job = self._job(state, app_id, job_id)
            if job.get("status") == "archived":
                raise WorkConflictError("archived jobs cannot receive connector bindings")
            if any(row.get("account_id") == account_id for row in job["connector_bindings"]):
                raise WorkConflictError("connector account is already bound to this job")
            binding = {
                "id": new_id("binding"),
                "account_id": account_id,
                "provider": account["provider"],
                "scopes": scopes,
                "outbound_approved": outbound_approved,
                "enabled": True,
                "created_at": utc_now_iso(),
            }
            job["connector_bindings"].append(binding)
            job["updated_at"] = binding["created_at"]
            self._append_activity(
                job,
                kind="connector_bound",
                state="complete",
                summary=f"Connected {account['label']}",
                details={"account_id": account_id, "provider": account["provider"]},
            )
            return binding

        return self._mutate(operation)

    def list_bindings(self, app_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            job = self._job(self._state, app_id, job_id)
            bindings = copy.deepcopy(job["connector_bindings"])
            accounts = self._state["connector_accounts"]
            for binding in bindings:
                account = accounts.get(binding.get("account_id"))
                if isinstance(account, dict):
                    binding["account"] = {
                        "id": account.get("id"),
                        "provider": account.get("provider"),
                        "label": account.get("label"),
                        "identity": account.get("identity"),
                        "status": account.get("status"),
                    }
        return bindings

    def unbind_account(self, app_id: str, job_id: str, binding_id: str) -> dict[str, Any]:
        safe_id = require_safe_id(binding_id, field="binding_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            match = next((row for row in job["connector_bindings"] if row.get("id") == safe_id), None)
            if not isinstance(match, dict):
                raise WorkNotFoundError("connector binding not found")
            job["connector_bindings"] = [row for row in job["connector_bindings"] if row.get("id") != safe_id]
            job["updated_at"] = utc_now_iso()
            self._append_activity(
                job,
                kind="connector_unbound",
                state="complete",
                summary="Connector account removed",
                details={"binding_id": safe_id},
            )
            return match

        return self._mutate(operation)
