"""Codex app-server bridge.

Spawns `codex app-server` as a subprocess and communicates over
stdio using the JSON-RPC-like protocol documented at:
  https://developers.openai.com/codex/app-server

This lets Thomas use your ChatGPT subscription (via OAuth) instead
of requiring a separate API key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import webbrowser
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0  # seconds for non-streaming requests
_INIT_TIMEOUT = 15.0
_STDOUT_READ_LIMIT_DEFAULT = 1024 * 1024  # 1 MiB
_STDOUT_READ_LIMIT_MIN = 64 * 1024
_STDOUT_READ_LIMIT_MAX = 64 * 1024 * 1024


def _resolve_stdout_read_limit() -> int:
    """Resolve codex stdout read limit in bytes with sane bounds."""
    raw = str(os.environ.get("THOMAS_CODEX_STDOUT_LIMIT_BYTES", "")).strip()
    if not raw:
        return _STDOUT_READ_LIMIT_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return _STDOUT_READ_LIMIT_DEFAULT
    return max(_STDOUT_READ_LIMIT_MIN, min(value, _STDOUT_READ_LIMIT_MAX))


from thomas.marketplace.codex.bridge_helpers import (
    event_matches_turn as _event_matches_turn,  # noqa: F401  -- re-exported for tests/test_codex_bridge_usage.py
)
from thomas.marketplace.codex.bridge_helpers import (
    extract_usage_payload as _extract_usage_payload,  # noqa: F401  -- re-exported for tests/test_codex_bridge_usage.py
)


@dataclass
class CodexAccount:
    """Current Codex auth state."""

    logged_in: bool = False
    auth_type: str = ""  # "chatgpt" | "apiKey" | ""
    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    plan_type: str = ""  # "free" | "plus" | "pro" | "team" | ""


@dataclass
class CodexModel:
    """A model available through Codex."""

    id: str
    display_name: str = ""
    is_default: bool = False


class CodexBridgeError(Exception):
    """Error from the Codex app-server."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class CodexBridge:
    """Manages a codex app-server subprocess and speaks its protocol.

    Usage::

        bridge = CodexBridge()
        await bridge.start()

        # Check / trigger login
        account = await bridge.check_auth()
        if not account.logged_in:
            await bridge.login_chatgpt()  # opens browser

        # Chat
        async for event in bridge.chat("explain this code", cwd="/my/project"):
            print(event)

        await bridge.stop()
    """

    def __init__(self, codex_cmd: str | None = None, cwd: str | None = None):
        self._codex_cmd = codex_cmd or _find_codex()
        self._cwd = cwd or os.getcwd()
        self._stdout_read_limit = _resolve_stdout_read_limit()
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notification_handlers: dict[str, list[Callable]] = {}
        self._reader_task: asyncio.Task | None = None
        self._initialized = False
        self._thread_id: str | None = None
        # Accumulate streamed text for the current turn
        self._current_turn_text: str = ""
        # Track active turn for interruption
        self._active_turn_id: str | None = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        """Spawn the codex app-server and complete the initialization handshake."""
        if self.is_running:
            return

        log.info("Starting codex app-server: %s", self._codex_cmd)

        env = dict(os.environ)
        # Suppress Codex's own interactive prompts
        env["CODEX_NONINTERACTIVE"] = "1"

        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._codex_cmd,
                "app-server",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self._stdout_read_limit,
                cwd=self._cwd,
                env=env,
            )
        except NotImplementedError as exc:
            raise CodexBridgeError(
                "Current asyncio event loop does not support subprocess execution. "
                "Use WindowsProactorEventLoopPolicy (e.g., by running `repl` with a "
                "Codex profile)."
            ) from exc

        # Start reading stdout
        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize handshake
        result = await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "thomas",
                    "title": "Thomas AI Assistant",
                    "version": "0.2.0",
                },
                "capabilities": {
                    "experimentalApi": False,
                },
            },
            timeout=_INIT_TIMEOUT,
        )

        # Send initialized notification
        await self._notify("initialized", {})
        self._initialized = True
        log.info("Codex app-server initialized: %s", result)

    async def stop(self) -> None:
        """Shut down the app-server subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._proc:
            try:
                self._proc.stdin.close()  # type: ignore
            except Exception as e:
                log.debug("Failed to close codex stdin cleanly: %s", e)
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._proc.kill()
                except Exception as e:
                    log.debug("Failed to kill codex process during shutdown: %s", e)
            self._proc = None

        self._initialized = False
        self._thread_id = None
        self._fail_pending_requests(CodexBridgeError("Bridge stopped"))

    def _fail_pending_requests(self, error: Exception) -> None:
        """Fail and clear all pending request futures."""
        if not isinstance(error, Exception):
            error = CodexBridgeError("Bridge request failed")
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(error)
        self._pending.clear()

    # â”€â”€ Authentication â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def check_auth(self) -> CodexAccount:
        """Check current authentication state."""
        result = await self._request("account/read", {"refreshToken": False})
        acct = result.get("account")
        if not acct:
            return CodexAccount(logged_in=False)
        profile = acct.get("profile") if isinstance(acct.get("profile"), dict) else {}
        display_name = str(
            acct.get("displayName") or acct.get("name") or profile.get("displayName") or profile.get("name") or ""
        ).strip()
        avatar_url = str(
            acct.get("avatarUrl")
            or acct.get("imageUrl")
            or acct.get("picture")
            or profile.get("avatarUrl")
            or profile.get("imageUrl")
            or profile.get("picture")
            or ""
        ).strip()
        return CodexAccount(
            logged_in=True,
            auth_type=acct.get("type", ""),
            email=acct.get("email", ""),
            display_name=display_name,
            avatar_url=avatar_url,
            plan_type=acct.get("planType", ""),
        )

    async def login_chatgpt(self) -> CodexAccount:
        """Start ChatGPT OAuth login flow â€” opens a browser.

        Blocks until the user completes login or an error occurs.
        Returns the authenticated account.
        """
        login_done: asyncio.Future = asyncio.get_event_loop().create_future()
        login_id: str | None = None

        def on_login_completed(params: dict[str, Any]) -> None:
            nonlocal login_id
            if params.get("loginId") == login_id:
                if not login_done.done():
                    if params.get("success"):
                        login_done.set_result(True)
                    else:
                        login_done.set_exception(CodexBridgeError(f"Login failed: {params.get('error', 'unknown')}"))

        self._on("account/login/completed", on_login_completed)

        try:
            result = await self._request("account/login/start", {"type": "chatgpt"})
            login_id = result.get("loginId", "")
            auth_url = result.get("authUrl", "")

            if auth_url:
                log.info("Opening browser for ChatGPT login: %s", auth_url[:80])
                webbrowser.open(auth_url)
            else:
                raise CodexBridgeError("No authUrl returned from app-server")

            # Wait for login to complete (up to 5 minutes)
            await asyncio.wait_for(login_done, timeout=300.0)

        except asyncio.TimeoutError:
            raise CodexBridgeError("Login timed out (5 minutes). Please try again.")
        finally:
            self._off("account/login/completed", on_login_completed)

        return await self.check_auth()

    async def login_api_key(self, api_key: str) -> CodexAccount:
        """Login with an OpenAI API key."""
        await self._request(
            "account/login/start",
            {
                "type": "apiKey",
                "apiKey": api_key,
            },
        )
        return await self.check_auth()

    async def logout(self) -> None:
        """Log out of the current account."""
        await self._request("account/logout", {})
        self._thread_id = None

    # â”€â”€ Models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def list_models(self) -> list[CodexModel]:
        """List available models."""
        result = await self._request("model/list", {"limit": 50})
        models = []
        for m in result.get("data", []):
            models.append(
                CodexModel(
                    id=m.get("id", m.get("model", "")),
                    display_name=m.get("displayName", ""),
                    is_default=m.get("isDefault", False),
                )
            )
        return models

    # â”€â”€ Chat â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def chat(
        self,
        text: str,
        *,
        model: str = "",
        cwd: str | None = None,
        effort: str = "medium",
        allow_tools: bool = True,
        instructions: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a message and stream back events.

        Yields dicts like:
            {"type": "text", "text": "Hello..."}
            {"type": "tool_start", "name": "ls", "id": "item_123"}
            {"type": "tool_output", "id": "item_123", "output": "..."}
            {"type": "done"}
            {"type": "error", "error": "..."}
        """
        # Ensure we have a thread
        if not self._thread_id:
            await self._start_thread(
                model=model, cwd=cwd or self._cwd, allow_tools=allow_tools, instructions=instructions
            )

        # Start a turn
        turn_done: asyncio.Future = asyncio.get_event_loop().create_future()
        events_queue: asyncio.Queue = asyncio.Queue()
        self._current_turn_text = ""
        tools_blocked = {"triggered": False}

        def on_turn_completed(params: dict[str, Any]) -> None:
            if not turn_done.done():
                turn = params.get("turn", {})
                status = turn.get("status", "completed")
                error = turn.get("error")
                if error:
                    events_queue.put_nowait(
                        {
                            "type": "error",
                            "error": error.get("message", str(error)),
                        }
                    )
                turn_done.set_result(status)

        def on_text_delta(params: dict[str, Any]) -> None:
            delta = params.get("delta", "")
            if delta:
                self._current_turn_text += delta
                events_queue.put_nowait({"type": "text", "text": delta})

        def on_item_started(params: dict[str, Any]) -> None:
            item = params.get("item", {})
            itype = item.get("type", "")
            is_tool_item = itype in {"commandExecution", "fileChange", "mcpToolCall"}
            if not is_tool_item:
                return

            if not allow_tools:
                if not tools_blocked["triggered"]:
                    tools_blocked["triggered"] = True
                    asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(self.interrupt()))
                return

            if itype == "commandExecution":
                events_queue.put_nowait(
                    {
                        "type": "tool_start",
                        "name": " ".join(item.get("command", ["?"])),
                        "id": item.get("id", ""),
                    }
                )
            elif itype == "fileChange":
                events_queue.put_nowait(
                    {
                        "type": "tool_start",
                        "name": f"edit:{item.get('filePath', '?')}",
                        "id": item.get("id", ""),
                    }
                )
            elif itype == "mcpToolCall":
                events_queue.put_nowait(
                    {
                        "type": "tool_start",
                        "name": item.get("toolName", "mcp_tool"),
                        "id": item.get("id", ""),
                    }
                )

        def on_item_completed(params: dict[str, Any]) -> None:
            item = params.get("item", {})
            itype = item.get("type", "")
            if not allow_tools and itype in {"commandExecution", "fileChange", "mcpToolCall"}:
                return
            if itype == "commandExecution":
                events_queue.put_nowait(
                    {
                        "type": "tool_output",
                        "id": item.get("id", ""),
                        "output": item.get("aggregatedOutput", ""),
                        "exit_code": item.get("exitCode"),
                    }
                )
            elif itype == "fileChange":
                events_queue.put_nowait(
                    {
                        "type": "tool_output",
                        "id": item.get("id", ""),
                        "output": f"File changed: {item.get('filePath', '?')}",
                    }
                )

        def on_cmd_approval(params: dict[str, Any]) -> None:
            req_id = params.get("_request_id")
            if req_id is not None:
                decision_payload: dict[str, Any]
                if allow_tools:
                    # Auto-approve commands (Thomas handles its own sandboxing)
                    decision_payload = {
                        "decision": "accept",
                        "acceptSettings": {"trustCommandClass": True},
                    }
                else:
                    decision_payload = {"decision": "decline"}
                asyncio.get_event_loop().call_soon(
                    lambda: asyncio.ensure_future(self._respond(req_id, decision_payload))
                )

        def on_file_approval(params: dict[str, Any]) -> None:
            req_id = params.get("_request_id")
            if req_id is not None:
                decision_payload = {"decision": "accept"} if allow_tools else {"decision": "decline"}
                asyncio.get_event_loop().call_soon(
                    lambda: asyncio.ensure_future(self._respond(req_id, decision_payload))
                )

        self._on("turn/completed", on_turn_completed)
        self._on("item/agentMessage/delta", on_text_delta)
        self._on("item/started", on_item_started)
        self._on("item/completed", on_item_completed)
        self._on("item/commandExecution/requestApproval", on_cmd_approval)
        self._on("item/fileChange/requestApproval", on_file_approval)

        try:
            turn_params: dict[str, Any] = {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": text}],
                "effort": effort,
            }
            if cwd:
                turn_params["cwd"] = cwd
            if model:
                turn_params["model"] = model
            if instructions:
                turn_params["instructions"] = instructions
            # Auto-approve everything â€” Thomas handles its own sandboxing
            if allow_tools:
                turn_params["approvalPolicy"] = "never"
                turn_params["sandboxPolicy"] = {
                    "type": "dangerFullAccess",
                    "networkAccess": True,
                }
            else:
                turn_params["approvalPolicy"] = "untrusted"
                turn_params["sandboxPolicy"] = {
                    "type": "readOnly",
                    "networkAccess": False,
                }

            result = await self._request("turn/start", turn_params)
            turn = result.get("turn", {})
            self._active_turn_id = turn.get("id")

            # Yield events until turn completes
            while True:
                # Check if turn is done
                if turn_done.done():
                    # Drain remaining events
                    while not events_queue.empty():
                        yield events_queue.get_nowait()
                    yield {"type": "done"}
                    break

                try:
                    event = await asyncio.wait_for(events_queue.get(), timeout=0.1)
                    yield event
                except asyncio.TimeoutError:
                    continue

        finally:
            self._active_turn_id = None
            self._off("turn/completed", on_turn_completed)
            self._off("item/agentMessage/delta", on_text_delta)
            self._off("item/started", on_item_started)
            self._off("item/completed", on_item_completed)
            self._off("item/commandExecution/requestApproval", on_cmd_approval)
            self._off("item/fileChange/requestApproval", on_file_approval)

    async def interrupt(self) -> None:
        """Interrupt the current turn."""
        if self._thread_id and self._active_turn_id:
            await self._request(
                "turn/interrupt",
                {
                    "threadId": self._thread_id,
                    "turnId": self._active_turn_id,
                },
            )

    async def _start_thread(
        self, model: str = "", cwd: str = "", allow_tools: bool = True, instructions: str = ""
    ) -> str:
        params: dict[str, Any] = {"cwd": cwd or self._cwd}
        if model:
            params["model"] = model
        if instructions:
            params["instructions"] = instructions
        if allow_tools:
            params["approvalPolicy"] = "never"
            params["sandbox"] = "danger-full-access"
        else:
            params["approvalPolicy"] = "untrusted"
            params["sandbox"] = "read-only"

        result = await self._request("thread/start", params)
        thread = result.get("thread", {})
        self._thread_id = thread.get("id", "")
        log.info("Codex thread started: %s", self._thread_id)
        return self._thread_id

    # â”€â”€ JSON-RPC transport â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _request(self, method: str, params: dict[str, Any], timeout: float = _REQUEST_TIMEOUT) -> dict[str, Any]:
        """Send a request and wait for the response."""
        if not self.is_running or not self._proc or not self._proc.stdin:
            raise CodexBridgeError("App-server not running")

        req_id = self._next_id
        self._next_id += 1

        msg = {"method": method, "id": req_id, "params": params}
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        log.debug(">> codex: %s", line.rstrip())

        try:
            self._proc.stdin.write(line.encode("utf-8"))
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            raise CodexBridgeError(f"Request {method} failed before send: {type(e).__name__}") from e

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise CodexBridgeError(f"Request {method} timed out after {timeout}s")

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification (no response expected)."""
        if not self.is_running or not self._proc or not self._proc.stdin:
            raise CodexBridgeError("App-server not running")

        msg = {"method": method, "params": params}
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        log.debug(">> codex (notify): %s", line.rstrip())

        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _respond(self, req_id: int, result: dict[str, Any]) -> None:
        """Send a response to a server request (e.g. approval)."""
        if not self.is_running or not self._proc or not self._proc.stdin:
            return

        msg = {"id": req_id, "result": result}
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        log.debug(">> codex (respond): %s", line.rstrip())

        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        """Read stdout lines and dispatch to pending requests / notification handlers."""
        if not self._proc or not self._proc.stdout:
            raise CodexBridgeError("App-server not running")

        while True:
            try:
                raw = await self._proc.stdout.readline()
                if not raw:
                    log.warning("Codex app-server stdout closed")
                    self._initialized = False
                    self._thread_id = None
                    self._fail_pending_requests(CodexBridgeError("Codex app-server stdout closed"))
                    break

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                log.debug("<< codex: %s", line[:500])

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("Non-JSON from codex: %s", line[:200])
                    continue

                # Response to a request we sent
                if "id" in msg and ("result" in msg or "error" in msg):
                    req_id = msg["id"]
                    future = self._pending.pop(req_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            err = msg["error"]
                            future.set_exception(
                                CodexBridgeError(
                                    err.get("message", str(err)),
                                    code=err.get("code", 0),
                                )
                            )
                        else:
                            future.set_result(msg.get("result", {}))
                    # If it has a method too, it's a server-initiated request
                    # (like approval requests) â€” handle that below
                    if "method" not in msg:
                        continue

                # Server-initiated request (needs a response from us)
                if "id" in msg and "method" in msg:
                    method = msg["method"]
                    params = msg.get("params", {})
                    params["_request_id"] = msg["id"]
                    self._dispatch_notification(method, params)
                    continue

                # Notification (no id, or id is absent)
                if "method" in msg:
                    method = msg["method"]
                    params = msg.get("params", {})
                    self._dispatch_notification(method, params)

            except asyncio.CancelledError:
                break
            except asyncio.LimitOverrunError as e:
                # A single JSON line exceeded StreamReader's configured line limit.
                # Drain buffered bytes so the read loop can recover on next line.
                consumed = max(int(getattr(e, "consumed", 0)), 1)
                try:
                    if self._proc and self._proc.stdout:
                        await self._proc.stdout.read(consumed)
                except asyncio.IncompleteReadError:
                    log.warning("Codex stdout closed while draining oversized line")
                    self._initialized = False
                    self._thread_id = None
                    self._fail_pending_requests(CodexBridgeError("Codex stdout closed while draining oversized line"))
                    break
                log.error(
                    "Codex stdout line exceeded read limit (%d bytes). "
                    "Increase THOMAS_CODEX_STDOUT_LIMIT_BYTES if this persists.",
                    int(self._stdout_read_limit),
                )
                await asyncio.sleep(0.05)
            except Exception as e:
                log.error("Error in codex read loop: %s", e)
                await asyncio.sleep(0.1)

    def _dispatch_notification(self, method: str, params: dict[str, Any]) -> None:
        handlers = self._notification_handlers.get(method, [])
        for handler in handlers:
            try:
                handler(params)
            except Exception as e:
                log.error("Notification handler error for %s: %s", method, e)

    def _on(self, method: str, handler: Callable) -> None:
        self._notification_handlers.setdefault(method, []).append(handler)

    def _off(self, method: str, handler: Callable) -> None:
        handlers = self._notification_handlers.get(method, [])
        try:
            handlers.remove(handler)
        except ValueError:
            return


def _find_codex() -> str:
    """Find the codex CLI binary."""
    # Check common locations
    for name in ("codex", "codex.cmd", "codex.exe"):
        path = shutil.which(name)
        if path:
            return path

    # Check npm global
    npm_global = os.environ.get("NPM_GLOBAL", "")
    if npm_global:
        for name in ("codex", "codex.cmd"):
            p = os.path.join(npm_global, name)
            if os.path.isfile(p):
                return p

    raise CodexBridgeError("Could not find 'codex' CLI. Install it with: npm i -g @openai/codex")
