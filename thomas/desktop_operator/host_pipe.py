from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from multiprocessing.connection import Client, Listener
from typing import Any

# `winerror` is a Windows-only module. The bare `import winerror` at module
# load broke `thomas.desktop_operator.host_pipe` imports on Linux CI, even
# in tests that don't exercise the host pipe (e.g. `test_host_service_runner_*`
# which only patches win32serviceutil). Guard the import behind the same
# pattern as the other Windows-only modules below.
try:  # pragma: no cover - Windows-only integration surface
    import winerror
except ImportError:  # pragma: no cover
    winerror = None

try:  # pragma: no cover - Windows-only integration surface
    import ntsecuritycon
    import pywintypes
    import win32file
    import win32pipe
    import win32security
except ImportError:  # pragma: no cover
    pywintypes = None
    win32file = None
    win32pipe = None
    win32security = None
    ntsecuritycon = None


def _is_windows_named_pipe(address: str) -> bool:
    return os.name == "nt" and str(address).startswith("\\\\.\\pipe\\")


def _authkey_text(authkey: bytes) -> str:
    return base64.urlsafe_b64encode(authkey).decode("ascii")


def _make_pipe_security_attributes():
    if not all((pywintypes, win32security, ntsecuritycon)):
        return None
    descriptor = win32security.SECURITY_DESCRIPTOR()
    dacl = win32security.ACL()
    access_mask = int(ntsecuritycon.GENERIC_READ | ntsecuritycon.GENERIC_WRITE)
    principals = [
        win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None),
        win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid, None),
        win32security.CreateWellKnownSid(win32security.WinBuiltinUsersSid, None),
    ]
    for sid in principals:
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access_mask, sid)
    descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def _read_pipe_message(handle) -> bytes:
    if win32file is None or pywintypes is None:
        raise RuntimeError("win32file is unavailable")
    chunks: list[bytes] = []
    while True:
        try:
            _, data = win32file.ReadFile(handle, 65536)
            chunks.append(bytes(data))
            break
        except pywintypes.error as exc:  # pragma: no cover - Windows-only
            if exc.winerror == winerror.ERROR_MORE_DATA:
                chunks.append(bytes(exc.args[2]))
                continue
            raise
    return b"".join(chunks)


def _write_pipe_message(handle, payload: bytes) -> None:
    if win32file is None:
        raise RuntimeError("win32file is unavailable")
    win32file.WriteFile(handle, payload)
    win32file.FlushFileBuffers(handle)


class DesktopHostPipeServer:
    def __init__(self, *, pipe_name: str, authkey: bytes) -> None:
        self.pipe_name = pipe_name
        self.authkey = authkey
        self._authkey_text = _authkey_text(authkey)
        self._closed = False
        self.listener = (
            None
            if _is_windows_named_pipe(pipe_name)
            else Listener(address=pipe_name, family="AF_PIPE", authkey=authkey)
        )

    def close(self) -> None:
        self._closed = True
        if self.listener is not None:
            try:
                self.listener.close()
            except Exception:
                pass
        if _is_windows_named_pipe(self.pipe_name) and win32file is not None:
            try:
                handle = win32file.CreateFile(
                    self.pipe_name,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                try:
                    _write_pipe_message(handle, b"{}")
                finally:
                    win32file.CloseHandle(handle)
            except Exception:
                pass

    def serve_forever(self, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        if self.listener is not None:
            try:
                while True:
                    try:
                        conn = self.listener.accept()
                    except (EOFError, OSError):
                        break
                    with conn:
                        while True:
                            try:
                                payload = conn.recv()
                            except EOFError:
                                break
                            response = handler(payload if isinstance(payload, dict) else {})
                            conn.send(response)
            finally:
                self.close()
            return

        if not all((win32pipe, win32file)):
            raise RuntimeError("win32 named pipe support is unavailable")

        security_attributes = _make_pipe_security_attributes()
        try:
            while not self._closed:
                handle = win32pipe.CreateNamedPipe(
                    self.pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536,
                    65536,
                    0,
                    security_attributes,
                )
                try:
                    try:
                        win32pipe.ConnectNamedPipe(handle, None)
                    except pywintypes.error as exc:  # pragma: no cover - Windows-only
                        if exc.winerror != 535:  # ERROR_PIPE_CONNECTED
                            raise
                    raw = _read_pipe_message(handle)
                    if self._closed:
                        break
                    try:
                        message = json.loads(raw.decode("utf-8")) if raw else {}
                    except Exception:
                        message = {}
                    if not isinstance(message, dict):
                        message = {}
                    if message.get("authkey") != self._authkey_text:
                        response = {"ok": False, "error": {"code": "unauthorized", "message": "invalid authkey"}}
                    else:
                        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
                        response = handler({"action": message.get("action"), "payload": payload})
                    _write_pipe_message(handle, json.dumps(response, ensure_ascii=False).encode("utf-8"))
                finally:
                    try:
                        win32pipe.DisconnectNamedPipe(handle)
                    except Exception:
                        pass
                    win32file.CloseHandle(handle)
        finally:
            self.close()


class DesktopHostPipeClient:
    def __init__(self, *, pipe_name: str, authkey: bytes) -> None:
        self.pipe_name = pipe_name
        self.authkey = authkey
        self._authkey_text = _authkey_text(authkey)

    def request(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not _is_windows_named_pipe(self.pipe_name):
            with Client(address=self.pipe_name, family="AF_PIPE", authkey=self.authkey) as conn:
                conn.send({"action": action, "payload": payload or {}})
                response = conn.recv()
            return response if isinstance(response, dict) else {"ok": False, "error": "invalid_response"}

        if not all((win32file, win32pipe)):
            raise RuntimeError("win32 named pipe support is unavailable")

        handle = win32file.CreateFile(
            self.pipe_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
        try:
            win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            request_payload = {
                "authkey": self._authkey_text,
                "action": action,
                "payload": payload or {},
            }
            _write_pipe_message(handle, json.dumps(request_payload, ensure_ascii=False).encode("utf-8"))
            response = json.loads(_read_pipe_message(handle).decode("utf-8"))
        finally:
            win32file.CloseHandle(handle)
        return response if isinstance(response, dict) else {"ok": False, "error": "invalid_response"}
