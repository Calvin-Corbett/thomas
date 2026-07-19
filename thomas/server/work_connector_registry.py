"""Request-scoped connector-account binding for Work tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from thomas.tools.base import ToolResult
from thomas.work import WorkStore
from thomas.work.connectors import canonical_connector_scopes
from thomas.work.validation import WorkValidationError


class WorkConnectorExecutionError(RuntimeError):
    """Raised when a Work connector call cannot be bound safely."""


@dataclass(frozen=True, slots=True)
class WorkExecutionBinding:
    """Private account binding used only at the connector execution boundary."""

    binding_id: str
    account_id: str
    provider: str
    scopes: frozenset[str]
    credential_ref: str = field(repr=False)
    account_status: str


class WorkConnectorExecutor(Protocol):
    """Provider executor contract used by the request-scoped registry view."""

    async def execute(
        self,
        binding: WorkExecutionBinding,
        tool_name: str,
        args: dict[str, Any],
        credential_secret: str,
    ) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class _ToolPolicy:
    provider: str
    scope: str


_TOOL_POLICIES: dict[str, _ToolPolicy] = {
    "email.read": _ToolPolicy("gmail", "read"),
    "email.get": _ToolPolicy("gmail", "read"),
    "email.send": _ToolPolicy("gmail", "send"),
    "email.reply": _ToolPolicy("gmail", "send"),
    "calendar.today": _ToolPolicy("google_calendar", "read"),
    "calendar.week": _ToolPolicy("google_calendar", "read"),
    "calendar.create": _ToolPolicy("google_calendar", "write"),
    "calendar.suggest_times": _ToolPolicy("google_calendar", "read"),
    "drive.list": _ToolPolicy("google_drive", "read"),
    "drive.get": _ToolPolicy("google_drive", "read"),
    "drive.search": _ToolPolicy("google_drive", "read"),
    "drive.create_folder": _ToolPolicy("google_drive", "write"),
    "drive.share": _ToolPolicy("google_drive", "write"),
}


def _normalize_scope(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _scope_allows(scopes: frozenset[str], required: str) -> bool:
    normalized = {_normalize_scope(scope) for scope in scopes}
    return required in normalized


def _snapshot_bindings(store: WorkStore, context_id: str) -> tuple[WorkExecutionBinding, ...]:
    parts = str(context_id or "").split(":")
    if len(parts) != 2 or not all(parts):
        raise WorkConnectorExecutionError("Work connector execution requires an existing job context.")
    app_id, job_id = parts
    state = store.snapshot()
    app = (state.get("apps") or {}).get(app_id)
    job = (app.get("jobs") or {}).get(job_id) if isinstance(app, dict) else None
    if not isinstance(job, dict):
        raise WorkConnectorExecutionError("Work connector execution could not resolve the selected job.")
    accounts = state.get("connector_accounts") if isinstance(state.get("connector_accounts"), dict) else {}
    rows: list[WorkExecutionBinding] = []
    for raw_binding in job.get("connector_bindings") or []:
        if not isinstance(raw_binding, dict) or not raw_binding.get("enabled", True):
            continue
        account_id = str(raw_binding.get("account_id") or "")
        account = accounts.get(account_id)
        if not isinstance(account, dict):
            continue
        try:
            scopes = canonical_connector_scopes(
                raw_binding.get("provider") or account.get("provider"),
                raw_binding.get("scopes") or [],
            )
        except (TypeError, ValueError, WorkValidationError):
            continue
        if not raw_binding.get("outbound_approved", False):
            scopes = [scope for scope in scopes if scope == "read"]
        rows.append(
            WorkExecutionBinding(
                binding_id=str(raw_binding.get("id") or ""),
                account_id=account_id,
                provider=str(raw_binding.get("provider") or account.get("provider") or ""),
                scopes=frozenset(scopes),
                credential_ref=str(account.get("credential_ref") or ""),
                account_status=str(account.get("status") or ""),
            )
        )
    return tuple(rows)


class WorkBoundToolRegistry:
    """A concurrency-safe registry view pinned to one Work job snapshot."""

    def __init__(
        self,
        base: Any,
        *,
        bindings: tuple[WorkExecutionBinding, ...],
        secret_store: Any,
        executor: WorkConnectorExecutor,
    ) -> None:
        self._base = base
        self._bindings = bindings
        self._secret_store = secret_store
        self._executor = executor

    def get(self, name: str) -> Any | None:
        return self._base.get(name)

    def list_tools(self, category: str | None = None) -> list[Any]:
        return self._base.list_tools(category)

    def list_categories(self) -> list[str]:
        return self._base.list_categories()

    def search(self, query: str, limit: int = 10) -> list[Any]:
        return self._base.search(query, limit=limit)

    def get_openai_specs(self, category: str | None = None) -> list[dict[str, Any]]:
        return self._base.get_openai_specs(category)

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        resolved_tool = self._base.get(name)
        canonical_name = str(getattr(resolved_tool, "name", "") or name or "").strip()
        policy = _TOOL_POLICIES.get(canonical_name.lower())
        if policy is None:
            return await self._base.execute(name, args)
        try:
            binding, clean_args = self._select_binding(policy, args)
            secret = self._read_secret(binding)
            return await self._executor.execute(binding, canonical_name, clean_args, secret)
        except WorkConnectorExecutionError as exc:
            return ToolResult(ok=False, error=str(exc))
        except (OSError, RuntimeError, TypeError, ValueError):
            return ToolResult(ok=False, error="Work connector execution failed safely.")

    def _select_binding(
        self,
        policy: _ToolPolicy,
        args: dict[str, Any],
    ) -> tuple[WorkExecutionBinding, dict[str, Any]]:
        clean_args = dict(args or {})
        requested_account = str(clean_args.pop("work_account_id", clean_args.pop("account_id", "")) or "").strip()
        provider_rows = [row for row in self._bindings if row.provider == policy.provider]
        if requested_account:
            provider_rows = [row for row in provider_rows if row.account_id == requested_account]
            if not provider_rows:
                raise WorkConnectorExecutionError("The requested connector account is not bound to this Work job.")
        active = [row for row in provider_rows if row.account_status == "active" and row.credential_ref]
        if not active:
            raise WorkConnectorExecutionError(
                f"No active {policy.provider} account with credentials is bound to this Work job."
            )
        permitted = [row for row in active if _scope_allows(row.scopes, policy.scope)]
        if not permitted:
            raise WorkConnectorExecutionError(
                f"The bound {policy.provider} account does not grant the required {policy.scope} scope."
            )
        if len(permitted) != 1:
            raise WorkConnectorExecutionError(
                f"Multiple {policy.provider} accounts match this action; select a bound work_account_id."
            )
        return permitted[0], clean_args

    def _read_secret(self, binding: WorkExecutionBinding) -> str:
        getter = getattr(self._secret_store, "get", None)
        if not callable(getter):
            raise WorkConnectorExecutionError("Work connector credential storage is unavailable.")
        try:
            secret = str(getter(binding.credential_ref) or "")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WorkConnectorExecutionError("Work connector credential storage could not be read safely.") from exc
        if not secret:
            raise WorkConnectorExecutionError(
                f"Credentials for Work connector account '{binding.account_id}' are unavailable."
            )
        return secret

    def __len__(self) -> int:
        return len(self._base)

    def __contains__(self, name: str) -> bool:
        return name in self._base

    def __iter__(self):
        return iter(self.list_tools())

    def __bool__(self) -> bool:
        return bool(self._base)


def bind_work_connector_tools(
    base: Any,
    *,
    store: WorkStore,
    secret_store: Any,
    context_id: str,
    executor: WorkConnectorExecutor,
) -> WorkBoundToolRegistry:
    """Pin a registry view to the exact Work job selected for this request."""

    return WorkBoundToolRegistry(
        base,
        bindings=_snapshot_bindings(store, context_id),
        secret_store=secret_store,
        executor=executor,
    )


__all__ = [
    "WorkBoundToolRegistry",
    "WorkConnectorExecutionError",
    "WorkConnectorExecutor",
    "WorkExecutionBinding",
    "bind_work_connector_tools",
]
