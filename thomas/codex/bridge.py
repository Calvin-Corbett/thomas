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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0  # seconds for non-streaming requests
_INIT_TIMEOUT = 15.0


@dataclass
class CodexAccount:
    """Current Codex auth state."""

    logged_in: bool = False
    auth_type: str = ""  # "chatgpt" | "apiKey" | ""
    email: str = ""
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

    def __init__(self, codex_cmd: Optional[str] = None, cwd: Optional[str] = None):
        self._codex_cmd = codex_cmd or _find_codex()
        self._cwd = cwd or os.getcwd()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._notification_handlers: Dict[str, List[Callable]] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized = False
        self._thread_id: Optional[str] = None
        # Accumulate streamed text for the current turn
        self._current_turn_text: str = ""
        # Track active turn for interruption
        self._active_turn_id: Optional[str] = None

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

        self._proc = await asyncio.create_subprocess_exec(
            self._codex_cmd, "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=env,
        )

        # Start reading stdout
        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize handshake
        result = await self._request("initialize", {
            "clientInfo": {
                "name": "thomas",
                "title": "Thomas AI Assistant",
                "version": "0.2.0",
            },
            "capabilities": {
                "experimentalApi": False,
            },
        }, timeout=_INIT_TIMEOUT)

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
        # Fail any pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(CodexBridgeError("Bridge stopped"))
        self._pending.clear()

    # ── Authentication ──────────────────────────────────────

    async def check_auth(self) -> CodexAccount:
        """Check current authentication state."""
        result = await self._request("account/read", {"refreshToken": False})
        acct = result.get("account")
        if not acct:
            return CodexAccount(logged_in=False)
        return CodexAccount(
            logged_in=True,
            auth_type=acct.get("type", ""),
            email=acct.get("email", ""),
            plan_type=acct.get("planType", ""),
        )

    async def login_chatgpt(self) -> CodexAccount:
        """Start ChatGPT OAuth login flow — opens a browser.

        Blocks until the user completes login or an error occurs.
        Returns the authenticated account.
        """
        login_done: asyncio.Future = asyncio.get_event_loop().create_future()
        login_id: Optional[str] = None

        def on_login_completed(params: Dict[str, Any]) -> None:
            nonlocal login_id
            if params.get("loginId") == login_id:
                if not login_done.done():
                    if params.get("success"):
                        login_done.set_result(True)
                    else:
                        login_done.set_exception(
                            CodexBridgeError(f"Login failed: {params.get('error', 'unknown')}")
                        )

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
        await self._request("account/login/start", {
            "type": "apiKey",
            "apiKey": api_key,
        })
        return await self.check_auth()

    async def logout(self) -> None:
        """Log out of the current account."""
        await self._request("account/logout", {})
        self._thread_id = None

    # ── Models ──────────────────────────────────────────────

    async def list_models(self) -> List[CodexModel]:
        """List available models."""
        result = await self._request("model/list", {"limit": 50})
        models = []
        for m in result.get("data", []):
            models.append(CodexModel(
                id=m.get("id", m.get("model", "")),
                display_name=m.get("displayName", ""),
                is_default=m.get("isDefault", False),
            ))
        return models

    # ── Chat ────────────────────────────────────────────────

    async def chat(
        self,
        text: str,
        *,
        model: str = "",
        cwd: Optional[str] = None,
        effort: str = "medium",
    ) -> AsyncIterator[Dict[str, Any]]:
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
            await self._start_thread(model=model, cwd=cwd or self._cwd)

        # Start a turn
        turn_done: asyncio.Future = asyncio.get_event_loop().create_future()
        events_queue: asyncio.Queue = asyncio.Queue()
        self._current_turn_text = ""

        def on_turn_completed(params: Dict[str, Any]) -> None:
            if not turn_done.done():
                turn = params.get("turn", {})
                status = turn.get("status", "completed")
                error = turn.get("error")
                if error:
                    events_queue.put_nowait({
                        "type": "error",
                        "error": error.get("message", str(error)),
                    })
                turn_done.set_result(status)

        def on_text_delta(params: Dict[str, Any]) -> None:
            delta = params.get("delta", "")
            if delta:
                self._current_turn_text += delta
                events_queue.put_nowait({"type": "text", "text": delta})

        def on_item_started(params: Dict[str, Any]) -> None:
            item = params.get("item", {})
            itype = item.get("type", "")
            if itype == "commandExecution":
                events_queue.put_nowait({
                    "type": "tool_start",
                    "name": " ".join(item.get("command", ["?"])),
                    "id": item.get("id", ""),
                })
            elif itype == "fileChange":
                events_queue.put_nowait({
                    "type": "tool_start",
                    "name": f"edit:{item.get('filePath', '?')}",
                    "id": item.get("id", ""),
                })
            elif itype == "mcpToolCall":
                events_queue.put_nowait({
                    "type": "tool_start",
                    "name": item.get("toolName", "mcp_tool"),
                    "id": item.get("id", ""),
                })

        def on_item_completed(params: Dict[str, Any]) -> None:
            item = params.get("item", {})
            itype = item.get("type", "")
            if itype == "commandExecution":
                events_queue.put_nowait({
                    "type": "tool_output",
                    "id": item.get("id", ""),
                    "output": item.get("aggregatedOutput", ""),
                    "exit_code": item.get("exitCode"),
                })
            elif itype == "fileChange":
                events_queue.put_nowait({
                    "type": "tool_output",
                    "id": item.get("id", ""),
                    "output": f"File changed: {item.get('filePath', '?')}",
                })

        def on_cmd_approval(params: Dict[str, Any]) -> None:
            # Auto-approve commands (Thomas handles its own sandboxing)
            req_id = params.get("_request_id")
            if req_id is not None:
                asyncio.get_event_loop().call_soon(
                    lambda: asyncio.ensure_future(
                        self._respond(req_id, {
                            "decision": "accept",
                            "acceptSettings": {"trustCommandClass": True},
                        })
                    )
                )

        def on_file_approval(params: Dict[str, Any]) -> None:
            req_id = params.get("_request_id")
            if req_id is not None:
                asyncio.get_event_loop().call_soon(
                    lambda: asyncio.ensure_future(
                        self._respond(req_id, {"decision": "accept"})
                    )
                )

        self._on("turn/completed", on_turn_completed)
        self._on("item/agentMessage/delta", on_text_delta)
        self._on("item/started", on_item_started)
        self._on("item/completed", on_item_completed)
        self._on("item/commandExecution/requestApproval", on_cmd_approval)
        self._on("item/fileChange/requestApproval", on_file_approval)

        try:
            turn_params: Dict[str, Any] = {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": text}],
                "effort": effort,
            }
            if cwd:
                turn_params["cwd"] = cwd
            if model:
                turn_params["model"] = model
            # Auto-approve everything — Thomas handles its own sandboxing
            turn_params["approvalPolicy"] = "never"
            turn_params["sandboxPolicy"] = {
                "type": "dangerFullAccess",
                "networkAccess": True,
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
            await self._request("turn/interrupt", {
                "threadId": self._thread_id,
                "turnId": self._active_turn_id,
            })

    async def _start_thread(self, model: str = "", cwd: str = "") -> str:
        params: Dict[str, Any] = {"cwd": cwd or self._cwd}
        if model:
            params["model"] = model
        params["approvalPolicy"] = "never"
        params["sandbox"] = "danger-full-access"

        result = await self._request("thread/start", params)
        thread = result.get("thread", {})
        self._thread_id = thread.get("id", "")
        log.info("Codex thread started: %s", self._thread_id)
        return self._thread_id

    # ── JSON-RPC transport ──────────────────────────────────

    async def _request(
        self, method: str, params: Dict[str, Any], timeout: float = _REQUEST_TIMEOUT
    ) -> Dict[str, Any]:
        """Send a request and wait for the response."""
        if not self._proc or not self._proc.stdin:
            raise CodexBridgeError("App-server not running")

        req_id = self._next_id
        self._next_id += 1

        msg = {"method": method, "id": req_id, "params": params}
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        log.debug(">> codex: %s", line.rstrip())

        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise CodexBridgeError(f"Request {method} timed out after {timeout}s")

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        """Send a notification (no response expected)."""
        if not self._proc or not self._proc.stdin:
            raise CodexBridgeError("App-server not running")

        msg = {"method": method, "params": params}
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        log.debug(">> codex (notify): %s", line.rstrip())

        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _respond(self, req_id: int, result: Dict[str, Any]) -> None:
        """Send a response to a server request (e.g. approval)."""
        if not self._proc or not self._proc.stdin:
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
                    # (like approval requests) — handle that below
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
            except Exception as e:
                log.error("Error in codex read loop: %s", e)
                await asyncio.sleep(0.1)

    def _dispatch_notification(self, method: str, params: Dict[str, Any]) -> None:
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

    raise CodexBridgeError(
        "Could not find 'codex' CLI. Install it with: npm i -g @openai/codex"
    )
