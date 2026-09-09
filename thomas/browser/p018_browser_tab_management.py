from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

TabAction = Literal["list", "open", "close", "activate", "close_all", "close_others"]


@dataclass(frozen=True)
class TabInfo:
    """A lightweight, serializable view of a browser tab."""

    id: str
    index: int
    url: str | None = None
    title: str | None = None
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "url": self.url,
            "title": self.title,
            "active": self.active,
        }


class BrowserTabManagementError(Exception):
    """Deterministic error type for browser tab management."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


class InvalidTabRequestError(BrowserTabManagementError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("invalid_input", message, details=details)


class TabNotFoundError(BrowserTabManagementError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("tab_not_found", message, details=details)


class TabConfigError(BrowserTabManagementError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("missing_config", message, details=details)


class TabBackendError(BrowserTabManagementError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("external_failure", message, details=details)


@dataclass(frozen=True)
class TabManagementRequest:
    """Input contract for tab management operations.

    - For actions that target a specific tab ('activate', 'close', 'close_others'):
      exactly one of tab_id or tab_index must be provided.
    - 'open' supports an optional url; when omitted it opens a blank tab.
    """

    action: TabAction
    tab_id: str | None = None
    tab_index: int | None = None
    url: str | None = None
    activate: bool = True


@dataclass(frozen=True)
class TabManagementResponse:
    """Output contract for tab management operations."""

    ok: bool
    action: TabAction
    tabs: list[TabInfo] = field(default_factory=list)
    affected_tab: TabInfo | None = None
    closed_tab_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "tabs": [t.to_dict() for t in self.tabs],
            "affected_tab": self.affected_tab.to_dict() if self.affected_tab else None,
            "closed_tab_ids": list(self.closed_tab_ids),
        }


class TabBackend(Protocol):
    """Backend interface for managing tabs.

    Intentionally minimal to allow adaptation to multiple implementations.
    """

    def list_tabs(self) -> list[TabInfo]: ...

    def open_tab(self, url: str | None = None, *, activate: bool = True) -> TabInfo: ...

    def close_tab(self, tab_id: str) -> None: ...

    def activate_tab(self, tab_id: str) -> TabInfo: ...


def manage_tabs(request: TabManagementRequest, backend: TabBackend | None) -> TabManagementResponse:
    """Perform a tab management action against a backend.

    Raises:
        InvalidTabRequestError, TabNotFoundError, TabConfigError, TabBackendError
    """
    if backend is None:
        raise TabConfigError(
            "No browser tab backend is configured.",
            details={"hint": "Provide a TabBackend instance or configure Thomas' live browser backend."},
        )

    _validate_request(request)

    try:
        if request.action == "list":
            tabs = backend.list_tabs()
            return TabManagementResponse(ok=True, action=request.action, tabs=_normalize_tab_indexes(tabs))

        if request.action == "open":
            tab = backend.open_tab(request.url, activate=request.activate)
            tabs = _normalize_tab_indexes(backend.list_tabs())
            created = _find_tab_by_id(tab.id, tabs) or tab
            return TabManagementResponse(ok=True, action=request.action, tabs=tabs, affected_tab=created)

        if request.action == "activate":
            tab_id = _resolve_tab_id(request, backend)
            activated = backend.activate_tab(tab_id)
            tabs = _normalize_tab_indexes(backend.list_tabs())
            activated_view = _find_tab_by_id(activated.id, tabs) or activated
            return TabManagementResponse(ok=True, action=request.action, tabs=tabs, affected_tab=activated_view)

        if request.action in ("close", "close_all", "close_others"):
            to_close = _resolve_close_targets(request, backend)
            for tab_id in to_close:
                backend.close_tab(tab_id)
            tabs = _normalize_tab_indexes(backend.list_tabs())
            return TabManagementResponse(ok=True, action=request.action, tabs=tabs, closed_tab_ids=list(to_close))

        raise InvalidTabRequestError("Unsupported action.", details={"action": request.action})
    except BrowserTabManagementError:
        raise
    except Exception as exc:  # pragma: no cover - defensive wrapper
        raise TabBackendError(
            "Browser backend failed while managing tabs.",
            details={"exception_type": type(exc).__name__, "exception_message": str(exc)},
        ) from exc


def coerce_tab_backend(obj: Any) -> TabBackend:
    """Best-effort adapter from arbitrary objects into a TabBackend.

    If adaptation fails, a deterministic TabConfigError is raised.
    """
    if obj is None:
        raise TabConfigError("No backend object provided.")

    required = ("list_tabs", "open_tab", "close_tab", "activate_tab")
    if all(callable(getattr(obj, name, None)) for name in required):
        return cast(TabBackend, obj)

    # Try Playwright-like context/live-browser objects without importing Playwright.
    context = _extract_playwright_context(obj)
    if context is not None:
        return _PlaywrightLikeTabBackend(context)

    return _ReflectiveBackendAdapter(obj)


def _validate_request(request: TabManagementRequest) -> None:
    if request.action not in cast(Sequence[str], ("list", "open", "close", "activate", "close_all", "close_others")):
        raise InvalidTabRequestError("Unknown action.", details={"action": request.action})

    if request.tab_index is not None and request.tab_index < 0:
        raise InvalidTabRequestError("tab_index must be >= 0.", details={"tab_index": request.tab_index})

    if request.tab_id is not None and isinstance(request.tab_id, str) and request.tab_id.strip() == "":
        raise InvalidTabRequestError("tab_id must not be empty.", details={})

    # Strictness: don't accept irrelevant/ambiguous fields.
    targets_provided = (request.tab_id is not None) + (request.tab_index is not None)

    if request.action in ("activate", "close", "close_others"):
        if targets_provided != 1:
            raise InvalidTabRequestError(
                f"Action '{request.action}' requires exactly one of tab_id or tab_index.",
                details={"action": request.action, "tab_id": request.tab_id, "tab_index": request.tab_index},
            )
    else:
        if targets_provided != 0:
            raise InvalidTabRequestError(
                f"Action '{request.action}' does not accept tab_id/tab_index.",
                details={"action": request.action, "tab_id": request.tab_id, "tab_index": request.tab_index},
            )

    if request.action == "open":
        if request.url is not None and not isinstance(request.url, str):
            raise InvalidTabRequestError("url must be a string.", details={"url_type": type(request.url).__name__})
        if request.url is not None and request.url.strip() == "":
            raise InvalidTabRequestError("url must not be empty.", details={})


def _normalize_tab_indexes(tabs: Sequence[TabInfo]) -> list[TabInfo]:
    """Return tabs with index values normalized to their list position."""
    normalized: list[TabInfo] = []
    for idx, t in enumerate(tabs):
        if t.index == idx:
            normalized.append(t)
        else:
            normalized.append(TabInfo(id=t.id, index=idx, url=t.url, title=t.title, active=t.active))
    return normalized


def _find_tab_by_id(tab_id: str, tabs: Sequence[TabInfo]) -> TabInfo | None:
    for t in tabs:
        if t.id == tab_id:
            return t
    return None


def _resolve_tab_id(request: TabManagementRequest, backend: TabBackend) -> str:
    if request.tab_id is not None:
        return request.tab_id

    assert request.tab_index is not None  # validated
    tabs = _normalize_tab_indexes(backend.list_tabs())
    if request.tab_index < 0 or request.tab_index >= len(tabs):
        raise TabNotFoundError("No tab exists at the provided index.", details={"tab_index": request.tab_index})
    return tabs[request.tab_index].id


def _resolve_close_targets(request: TabManagementRequest, backend: TabBackend) -> list[str]:
    tabs = _normalize_tab_indexes(backend.list_tabs())

    if request.action == "close_all":
        return [t.id for t in tabs]

    if request.action == "close":
        return [_resolve_tab_id(request, backend)]

    # close_others
    keep_id = _resolve_tab_id(request, backend)
    return [t.id for t in tabs if t.id != keep_id]


class InMemoryTabBackend(TabBackend):
    """A deterministic, in-memory backend for tests and offline use."""

    def __init__(self, *, initial_tabs: Sequence[TabInfo] | None = None) -> None:
        self._tabs: list[TabInfo] = []
        self._next_id = 1

        if initial_tabs:
            normalized = _normalize_tab_indexes(list(initial_tabs))
            active_count = sum(1 for t in normalized if t.active)
            if active_count > 1:
                raise ValueError("initial_tabs may not contain multiple active tabs.")
            self._tabs = list(normalized)
            self._next_id = max(self._next_id, len(self._tabs) + 1)

        if self._tabs and not any(t.active for t in self._tabs):
            self._tabs[0] = TabInfo(
                id=self._tabs[0].id,
                index=self._tabs[0].index,
                url=self._tabs[0].url,
                title=self._tabs[0].title,
                active=True,
            )

    def list_tabs(self) -> list[TabInfo]:
        return list(self._tabs)

    def open_tab(self, url: str | None = None, *, activate: bool = True) -> TabInfo:
        tab_id = f"tab-{self._next_id}"
        self._next_id += 1

        if activate:
            self._tabs = [TabInfo(id=t.id, index=t.index, url=t.url, title=t.title, active=False) for t in self._tabs]

        new_tab = TabInfo(id=tab_id, index=len(self._tabs), url=url, title=None, active=activate)
        self._tabs.append(new_tab)
        return new_tab

    def close_tab(self, tab_id: str) -> None:
        idx = next((i for i, t in enumerate(self._tabs) if t.id == tab_id), None)
        if idx is None:
            raise TabNotFoundError("No tab exists with the provided id.", details={"tab_id": tab_id})

        was_active = self._tabs[idx].active
        del self._tabs[idx]
        self._tabs = _normalize_tab_indexes(self._tabs)

        if not self._tabs:
            return

        if was_active:
            new_active_idx = min(idx, len(self._tabs) - 1)
            self._tabs = [
                TabInfo(id=t.id, index=t.index, url=t.url, title=t.title, active=(t.index == new_active_idx))
                for t in self._tabs
            ]

    def activate_tab(self, tab_id: str) -> TabInfo:
        if not any(t.id == tab_id for t in self._tabs):
            raise TabNotFoundError("No tab exists with the provided id.", details={"tab_id": tab_id})

        self._tabs = [
            TabInfo(id=t.id, index=t.index, url=t.url, title=t.title, active=(t.id == tab_id)) for t in self._tabs
        ]
        return next(t for t in self._tabs if t.id == tab_id)


# ---- Playwright-like backend (duck-typed, no direct dependency) -----------------


def _extract_playwright_context(obj: Any) -> Any | None:
    """Return a Playwright-like context object if `obj` looks like one.

    We avoid importing Playwright here; this is purely duck typing.
    """
    if obj is None:
        return None

    # BrowserContext-style: has pages + new_page
    if hasattr(obj, "pages") and callable(getattr(obj, "new_page", None)):
        return obj

    # LiveBrowser-style: has .context which is BrowserContext-like
    ctx = getattr(obj, "context", None)
    if ctx is not None and hasattr(ctx, "pages") and callable(getattr(ctx, "new_page", None)):
        return ctx

    return None


def _safe_page_title(page: Any) -> str | None:
    """Best-effort title getter that won't crash on async/coroutine APIs."""
    title_attr = getattr(page, "title", None)
    if title_attr is None:
        return None
    if callable(title_attr):
        try:
            value = title_attr()
        except TypeError:
            return None
        # Avoid awaiting coroutines in a sync CLI; just drop it.
        if isinstance(value, str):
            return value
        return None
    if isinstance(title_attr, str):
        return title_attr
    return None


def _page_identifier(page: Any) -> str:
    for attr in ("guid", "_guid", "id", "_id"):
        value = getattr(page, attr, None)
        if value is not None:
            return str(value)
    return str(id(page))


class _PlaywrightLikeTabBackend(TabBackend):
    """TabBackend for a Playwright-like BrowserContext.

    Supports:
    - context.pages -> list of Page-like objects
    - context.new_page() -> Page-like object
    - Page-like: .url (str), .goto(url), .bring_to_front(), .close(), .title() (optional)
    """

    def __init__(self, context: Any) -> None:
        self._context = context
        self._active_id: str | None = None

    def list_tabs(self) -> list[TabInfo]:
        pages = list(getattr(self._context, "pages", []) or [])
        tabs: list[TabInfo] = []

        for idx, page in enumerate(pages):
            tab_id = _page_identifier(page)
            url = cast(str | None, getattr(page, "url", None))
            title = _safe_page_title(page)
            active = (tab_id == self._active_id) if self._active_id is not None else (idx == 0)
            tabs.append(TabInfo(id=tab_id, index=idx, url=url, title=title, active=active))

        # Keep active id in sync with reality.
        if tabs and self._active_id is None:
            self._active_id = tabs[0].id

        return tabs

    def open_tab(self, url: str | None = None, *, activate: bool = True) -> TabInfo:
        page = self._context.new_page()
        if url is not None:
            goto = getattr(page, "goto", None)
            if callable(goto):
                goto(url)

        if activate:
            bring_to_front = getattr(page, "bring_to_front", None)
            if callable(bring_to_front):
                bring_to_front()

        tab_id = _page_identifier(page)
        if activate:
            self._active_id = tab_id

        # Index will be normalized by caller from list_tabs(); use 0 placeholder.
        return TabInfo(
            id=tab_id,
            index=0,
            url=cast(str | None, getattr(page, "url", None)),
            title=_safe_page_title(page),
            active=activate,
        )

    def close_tab(self, tab_id: str) -> None:
        pages = list(getattr(self._context, "pages", []) or [])
        page = next((p for p in pages if _page_identifier(p) == tab_id), None)
        if page is None:
            raise TabNotFoundError("No tab exists with the provided id.", details={"tab_id": tab_id})

        close = getattr(page, "close", None)
        if callable(close):
            close()
        else:
            raise TabBackendError("Backend page does not support close().", details={"tab_id": tab_id})

        if self._active_id == tab_id:
            self._active_id = None
            # Recompute on next list_tabs()

    def activate_tab(self, tab_id: str) -> TabInfo:
        pages = list(getattr(self._context, "pages", []) or [])
        page = next((p for p in pages if _page_identifier(p) == tab_id), None)
        if page is None:
            raise TabNotFoundError("No tab exists with the provided id.", details={"tab_id": tab_id})

        bring_to_front = getattr(page, "bring_to_front", None)
        if callable(bring_to_front):
            bring_to_front()

        self._active_id = tab_id
        return TabInfo(
            id=tab_id,
            index=0,
            url=cast(str | None, getattr(page, "url", None)),
            title=_safe_page_title(page),
            active=True,
        )


# ---- Reflective adapter for miscellaneous backends --------------------------------


class _ReflectiveBackendAdapter(TabBackend):
    """Adapter that tries to talk to an arbitrary browser object.

    It's intentionally conservative: if we can't find something sensible, we raise
    a deterministic configuration error rather than guessing and causing weirdness.
    """

    def __init__(self, obj: Any) -> None:
        self._obj = obj
        self._m_list = _pick_attr_or_method(obj, ["list_tabs", "get_tabs", "tabs", "list_pages", "pages"])
        self._m_open = _pick_attr_or_method(obj, ["open_tab", "new_tab", "create_tab", "open_new_tab", "new_page"])
        self._m_close = _pick_attr_or_method(obj, ["close_tab", "remove_tab", "close_page", "close"])
        self._m_activate = _pick_attr_or_method(obj, ["activate_tab", "switch_tab", "focus_tab", "set_active_tab"])

        missing = [
            name
            for name, member in [
                ("list_tabs", self._m_list),
                ("open_tab", self._m_open),
                ("close_tab", self._m_close),
                ("activate_tab", self._m_activate),
            ]
            if member is None
        ]
        if missing:
            raise TabConfigError(
                "Backend object does not support tab management.",
                details={"missing": missing, "backend_type": type(obj).__name__},
            )

    def list_tabs(self) -> list[TabInfo]:
        raw = _call_attr_or_method(self._m_list, self._obj)
        return _coerce_tabs(raw)

    def open_tab(self, url: str | None = None, *, activate: bool = True) -> TabInfo:
        created = _call_best_effort(self._m_open, self._obj, url=url, activate=activate)
        created_info = _coerce_single_tab(created)
        if created_info is not None:
            return created_info

        tabs = self.list_tabs()
        active = next((t for t in tabs if t.active), None)
        if active:
            return active
        if tabs:
            return tabs[-1]
        raise TabBackendError("Backend reported opening a tab, but no tabs are visible afterwards.", details={})

    def close_tab(self, tab_id: str) -> None:
        _call_best_effort(self._m_close, self._obj, tab_id=tab_id)

    def activate_tab(self, tab_id: str) -> TabInfo:
        result = _call_best_effort(self._m_activate, self._obj, tab_id=tab_id)
        tab = _coerce_single_tab(result)
        if tab is not None:
            return tab

        tabs = self.list_tabs()
        active = next((t for t in tabs if t.active), None)
        if active is None:
            raise TabBackendError("Backend did not expose an active tab after activation.", details={"tab_id": tab_id})
        return active


def _pick_attr_or_method(obj: Any, names: Sequence[str]) -> str | None:
    for name in names:
        if hasattr(obj, name):
            return name
    return None


def _call_attr_or_method(member_name: str | None, obj: Any, *args: Any, **kwargs: Any) -> Any:
    if member_name is None:
        raise TabConfigError("Missing backend member.")
    member = getattr(obj, member_name)
    return member(*args, **kwargs) if callable(member) else member


def _call_best_effort(
    member_name: str | None,
    obj: Any,
    *,
    url: str | None = None,
    activate: bool = True,
    tab_id: str | None = None,
) -> Any:
    if member_name is None:
        raise TabConfigError("Missing backend member.")

    member = getattr(obj, member_name)
    if not callable(member):
        raise TabConfigError("Backend member is not callable.", details={"member": member_name})

    patterns: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    if tab_id is not None:
        patterns.extend(
            [
                ((tab_id,), {}),
                ((), {"tab_id": tab_id}),
                ((), {"id": tab_id}),
            ]
        )
        if tab_id.isdigit():
            idx = int(tab_id)
            patterns.extend([((idx,), {}), ((), {"index": idx}), ((), {"tab_index": idx})])
    else:
        if url is None:
            patterns.extend([((), {}), ((), {"activate": activate})])
        else:
            patterns.extend(
                [
                    ((url,), {}),
                    ((url,), {"activate": activate}),
                    ((), {"url": url, "activate": activate}),
                    ((), {"url": url}),
                ]
            )

    last_type_error: TypeError | None = None
    for args, kwargs in patterns:
        try:
            return member(*args, **kwargs)
        except TypeError as exc:
            last_type_error = exc
            continue

    raise TabBackendError(
        "Backend method could not be called with supported argument patterns.",
        details={
            "member": member_name,
            "backend_type": type(obj).__name__,
            "last_type_error": str(last_type_error) if last_type_error else None,
        },
    )


def _coerce_single_tab(raw: Any) -> TabInfo | None:
    if raw is None:
        return None
    if isinstance(raw, TabInfo):
        return raw
    if isinstance(raw, dict):
        try:
            tab_id = str(raw.get("id", raw.get("tab_id", raw.get("uuid", raw.get("index", "")))))
            index = int(raw.get("index", 0))
            return TabInfo(
                id=tab_id,
                index=index,
                url=cast(str | None, raw.get("url")),
                title=cast(str | None, raw.get("title")),
                active=bool(raw.get("active", raw.get("is_active", False))),
            )
        except (ValueError, TypeError, KeyError):
            return None

    # Heuristic for page-like objects.
    if hasattr(raw, "url"):
        tab_id = _page_identifier(raw)
        url = cast(str | None, getattr(raw, "url", None))
        title = _safe_page_title(raw)
        return TabInfo(id=str(tab_id), index=0, url=url, title=title, active=False)

    return None


def _coerce_tabs(raw: Any) -> list[TabInfo]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        if isinstance(raw, str):
            return []
        if isinstance(raw, Iterable):
            items = list(raw)
        else:
            return []

    tabs: list[TabInfo] = []
    for idx, item in enumerate(items):
        tab = _coerce_single_tab(item)
        if tab is None:
            tab = TabInfo(id=str(idx), index=idx, url=None, title=None, active=False)
        tabs.append(TabInfo(id=tab.id, index=idx, url=tab.url, title=tab.title, active=tab.active))

    if tabs and not any(t.active for t in tabs):
        tabs[0] = TabInfo(id=tabs[0].id, index=tabs[0].index, url=tabs[0].url, title=tabs[0].title, active=True)

    return tabs
