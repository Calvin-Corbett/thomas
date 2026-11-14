"""Approval cards and narrowly scoped controls for the settings catalogue.

The caller is responsible for authenticating the owner and passing ``verified``
only after the Windows sign-in succeeds. This module does not expose routes.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.user_questions import question_book
from thomas.server.app_keys import APP_CONFIG
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.server.settings_index import build_index, find_settings


def read_windows():
    from thomas.server.window_records import read_windows as read

    return read()


class SettingsControls:
    def __init__(self, app: Any, book: Any = None, audit_path: Any = None, *, express_runner: Any = None):
        self.app = app
        self.book = book if book is not None else question_book()
        self.audit_path = Path(audit_path) if audit_path is not None else None
        self.express_runner = express_runner
        self._pending: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def _audit(self, event: str, setting: str = "", outcome: str = "") -> None:
        # No query, session, values, error text or window records are persisted.
        item = {"event": event, "setting": setting, "outcome": outcome, "at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._events.append(item)
            if self.audit_path is not None:
                try:
                    self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.audit_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(item, ensure_ascii=True) + "\n")
                except OSError:
                    pass

    def audit(self) -> list[dict[str, Any]]:
        """Return this instance's sanitized audit events, without reading files."""
        with self._lock:
            return [dict(event) for event in self._events]

    def index(self, browser_settings: Any = None, preferences: Any = None) -> list[dict]:
        runtime = self.app.get(APP_RUNTIME_PLUGINS)
        rows = runtime.report().get("rows", []) if runtime is not None else []
        express: dict[str, Any] = {"open": False}
        try:
            windows = read_windows()
            latest = windows[0] if windows else None
            if latest and latest.get("opened_at") and "ended" not in latest:
                since = latest["opened_at"]
                express = {"open": True, "since": since}
                try:
                    opened = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
                    if opened.tzinfo is None:
                        opened = opened.replace(tzinfo=timezone.utc)
                    express["elapsed_seconds"] = max(0, int((datetime.now(timezone.utc) - opened).total_seconds()))
                except (ValueError, TypeError, OverflowError):
                    pass
        except OSError:
            express = {}
        return build_index(
            plugin_rows=rows,
            config=self.app.get(APP_CONFIG),
            browser_settings=browser_settings,
            preferences=preferences,
            express=express,
        )

    @staticmethod
    def _boolean(value: Any, query: str) -> Any:
        if isinstance(value, bool):
            return value
        text = str(value if value is not None else query).strip().lower()
        if text in ("on", "true", "enable", "enabled", "open", "yes", "1"):
            return True
        if text in ("off", "false", "disable", "disabled", "close", "closed", "no", "0"):
            return False
        words = set(text.replace("-", " ").split())
        on = bool(words & {"on", "enable", "enabled", "open"})
        off = bool(words & {"off", "disable", "disabled", "close"})
        return on if on != off else None

    def request(self, query: str, value: Any = None, session_id: str = "") -> dict:
        rows = self.index()
        matches = [row for row in rows if row.get("id") == query]
        if not matches:
            matches = find_settings(rows, query)
        if not matches:
            self._audit("refused", outcome="unknown setting")
            return {"ok": False, "error": "Setting not found."}
        row = matches[0]
        identifier = row["id"]
        kind, _, key = identifier.partition(":")
        desired = value
        lookup = value is None and not any(
            word in str(query).lower().split() for word in ("on", "off", "open", "close", "enable", "disable")
        )
        if lookup:
            desired = None
        elif identifier == "express" or kind == "plugin":
            desired = self._boolean(value, str(query))
            if desired is None:
                self._audit("refused", identifier, "invalid value")
                return {"ok": False, "error": "Specify on or off."}
        elif kind == "dial":
            options = row.get("values")
            if not isinstance(options, list) or not any(type(desired) is type(v) and desired == v for v in options):
                # The UI may serialize numeric dial values as strings.
                candidates = [v for v in options or [] if str(v) == str(desired)]
                if len(candidates) != 1:
                    self._audit("refused", identifier, "invalid value")
                    return {"ok": False, "error": "Choose a listed value for this setting."}
                desired = candidates[0]
        elif value is None:
            self._audit("refused", identifier, "missing value")
            return {"ok": False, "error": "Specify the desired value."}
        # Browser dials are protected here regardless of direction; the client must
        # also enforce its normal elevation checks when applying the instruction.
        protected = not lookup and (
            identifier == "express" or kind == "dial" or row.get("requirement") in ("windows_sign_in", "break_glass")
        )
        label = "Show setting" if lookup else ("Windows sign-in" if protected else "Apply change")
        option = {"label": label}
        if protected:
            option["requires_password"] = True
        details = {
            "setting": dict(row),
            "current": row.get("current_value"),
            "desired": desired,
            "note": "Nothing changes without your press. Windows sign-in is required."
            if protected
            else "Nothing changes without your press.",
            "fields": [
                {"label": "Current value", "value": json.dumps(row.get("current_value"), ensure_ascii=False)},
                {"label": "Where", "value": row.get("location", "Settings")},
            ],
        }
        if not lookup:
            details["fields"].insert(1, {"label": "Requested value", "value": json.dumps(desired, ensure_ascii=False)})
        if identifier == "express" and isinstance(row.get("current_value"), dict):
            state = row["current_value"]
            details["fields"].extend(
                [
                    {"label": "Since", "value": str(state.get("since") or "Not open")},
                    {"label": "Elapsed", "value": str(state.get("elapsed_seconds", 0)) + " seconds"},
                ]
            )
        record = self.book.ask(
            question=f"Change {row['name']}?",
            options=[option],
            session_id=str(session_id or ""),
            kind="settings-control",
            allow_free_text=False,
            details=details,
        )
        card = record.to_dict()
        with self._lock:
            self._pending[record.id] = {
                "session": str(session_id or ""),
                "label": label,
                "protected": protected,
                "id": identifier,
                "desired": desired,
                "lookup": lookup,
                "location": row.get("location", "Settings"),
                "card": card,
            }
        self._audit("request", identifier, "pending")
        return card

    def sign_in_refused(self, question_id: str) -> None:
        with self._lock:
            pending = self._pending.get(str(question_id))
            if pending:
                self._audit("refused", pending["id"], "Windows sign-in was not completed")

    async def press(self, question_id: str, session_id: str, selected: Any, verified: bool = False) -> dict:
        identifier = ""
        with self._lock:
            pending = self._pending.get(str(question_id))
            labels = [selected] if isinstance(selected, str) else selected
            if pending is None or str(session_id or "") != pending["session"] or labels != [pending["label"]]:
                self._audit("refused", outcome="invalid card or selection")
                return {"ok": False, "error": "Card or selection is not valid."}
            identifier = pending["id"]
            if pending["protected"] and verified is not True:
                self._audit("refused", identifier, "verification required")
                return {"ok": False, "error": "Windows sign-in is required."}
            cards = self.book.pending(session_id=pending["session"])
            card = next((c for c in cards if c.get("id") == str(question_id)), None)
            if card != pending["card"] or not self.book.answer(
                str(question_id), labels, session_id=pending["session"], password_verified=verified is True
            ):
                self._pending.pop(str(question_id), None)
                self._audit("refused", identifier, "card no longer pending")
                return {"ok": False, "error": "Card is no longer pending."}
            self._pending.pop(str(question_id), None)
        self._audit("press", identifier, "accepted")
        kind, _, key = identifier.partition(":")
        desired = pending["desired"]
        if pending["lookup"]:
            self._audit("located", identifier, "navigation instruction issued")
            return {"ok": True, "instruction": {"type": "navigate", "location": pending["location"]}}
        if identifier == "express":
            try:
                if self.express_runner is not None:
                    result = self.express_runner(desired)
                    if hasattr(result, "__await__"):
                        result = await result
                else:
                    from scripts.cage.window_control import main

                    args = ["open", "--until-off"] if desired else ["close"]
                    result = await asyncio.to_thread(main, args)
                code = (
                    result
                    if isinstance(result, int) and not isinstance(result, bool)
                    else getattr(result, "returncode", None)
                )
                if code != 0:
                    raise RuntimeError("window control failed")
            except (ImportError, OSError, RuntimeError):
                self._audit("refused", identifier, "window control failed")
                return {"ok": False, "error": "Express control failed; check the window status."}
            self._audit("applied", identifier, "command completed")
            return {"ok": True, "message": "Express command completed; check window status for the result."}
        if kind == "plugin":
            runtime = self.app.get(APP_RUNTIME_PLUGINS)
            try:
                if runtime is None:
                    raise RuntimeError("runtime unavailable")
                live = next((r for r in runtime.report().get("rows", []) if r.get("id") == key), None)
                if live is None or (live.get("required") and desired is False):
                    raise RuntimeError("plugin unavailable")
                result = await (runtime.turn_on(key) if desired else runtime.turn_off(key))
            except Exception:
                self._audit("refused", identifier, "plugin control failed")
                return {"ok": False, "error": "Plugin control failed or is unavailable."}
            self._audit("applied", identifier, "plugin command completed")
            return {"ok": True, "result": result}
        if kind == "dial":
            # Revalidate against trusted descriptors, not card or browser input.
            live = next((r for r in self.index() if r.get("id") == identifier), None)
            if not live or not any(type(desired) is type(v) and desired == v for v in live.get("values", [])):
                self._audit("refused", identifier, "dial no longer available")
                return {"ok": False, "error": "Dial or value is no longer available."}
            self._audit("applied", identifier, "client instruction issued")
            return {
                "ok": True,
                "instruction": {"type": "browser_setting", "id": key, "value": desired},
                "message": "Apply this setting in the browser; it has not yet been changed.",
            }
        self._audit("applied", identifier, "navigation instruction issued")
        return {
            "ok": True,
            "instruction": {"type": "navigate", "location": pending["location"]},
            "message": "Change this setting there; it has not been changed.",
        }


__all__ = ["SettingsControls"]
