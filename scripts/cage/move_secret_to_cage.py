"""Hand a secret to the cage account without it touching a file, a log or a screen.

Thomas keeps secrets with Windows DPAPI in the current user's scope
(thomas/server/secrets.py), so the cage account cannot read yours: moving one means
your process decrypts it and a process running as the cage account encrypts it
again. Plan item 4a-3 required a pipe, never a file, for that handoff.

``send`` (as you) reads the named secrets, opens a named pipe with a random name
that it must create first (FILE_FLAG_FIRST_PIPE_INSTANCE, so nothing can squat the
name) and whose permissions admit the cage account and nothing else, then asks the
caged shell to run ``receive``. ``receive`` (as the cage account) reads the pipe and
stores each value in its own secret store. Only names are ever printed.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import secrets as random_names
import sys
import threading
from ctypes import wintypes
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PIPE_PREFIX = "\\\\.\\pipe\\thomas-cage-secret-"
_PIPE_ACCESS_OUTBOUND = 0x00000002
_FIRST_INSTANCE = 0x00080000
_INVALID = ctypes.c_void_p(-1).value


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _security_for(sid: str) -> _SecurityAttributes:
    """Protected DACL: generic-all for *sid*, and no one else -- not even you."""
    descriptor = ctypes.c_void_p()
    ok = ctypes.windll.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"D:P(A;;GA;;;{sid})", 1, ctypes.byref(descriptor), None
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "could not build the pipe's permissions")
    return _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)


def serve_once(pipe: str, payload: bytes, *, allow_sid: str, done: threading.Event) -> None:
    """Create *pipe*, wait for its one reader, write *payload*, close. Sets *done* on delivery."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.restype = ctypes.c_void_p
    security = _security_for(allow_sid)
    handle = kernel.CreateNamedPipeW(
        pipe, _PIPE_ACCESS_OUTBOUND | _FIRST_INSTANCE, 0, 1, 65536, 65536, 0, ctypes.byref(security)
    )
    if handle in (None, _INVALID):
        raise OSError(ctypes.get_last_error(), f"could not create {pipe}")
    try:
        connected = kernel.ConnectNamedPipe(ctypes.c_void_p(handle), None) or ctypes.get_last_error() == 535
        if connected:
            written = wintypes.DWORD()
            kernel.WriteFile(ctypes.c_void_p(handle), payload, len(payload), ctypes.byref(written), None)
            kernel.FlushFileBuffers(ctypes.c_void_p(handle))
            done.set()
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def receive(pipe: str, store_root: Path) -> list[str]:
    """Read the pipe once and keep each secret in this account's own store."""
    from thomas.server.secrets import SecretStore

    with open(pipe, "rb") as handle:  # noqa: PTH123 - a pipe, not a path
        values = json.loads(handle.read().decode("utf-8"))
    store = SecretStore(store_root)
    for name, value in values.items():
        store.set(name, value)
    return sorted(values)


def _cage_sid(user: str) -> str:
    sid = ctypes.create_string_buffer(256)
    size, domain, domain_size, use = (
        wintypes.DWORD(256),
        ctypes.create_unicode_buffer(256),
        wintypes.DWORD(256),
        wintypes.DWORD(),
    )
    if not ctypes.windll.advapi32.LookupAccountNameW(
        None, user, sid, ctypes.byref(size), domain, ctypes.byref(domain_size), ctypes.byref(use)
    ):
        raise OSError(ctypes.get_last_error(), f"no account {user}")
    text = ctypes.c_wchar_p()
    ctypes.windll.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text))
    return text.value or ""


def send(names: list[str], source_root: Path, target_root: str, *, user: str = "thomas-agent") -> list[str]:
    """Move *names* from your store at *source_root* into the cage account's store."""
    from thomas.server.secrets import SecretStore
    from thomas.tools.cage_shell import run_caged

    store = SecretStore(source_root)
    values = {name: store.get(name) for name in names if store.get(name)}
    if not values:
        return []
    pipe = PIPE_PREFIX + random_names.token_hex(16)
    done = threading.Event()
    server = threading.Thread(
        target=serve_once,
        args=(pipe, json.dumps(values).encode("utf-8")),
        kwargs={"allow_sid": _cage_sid(user), "done": done},
        daemon=True,
    )
    server.start()
    script = Path(__file__).resolve()
    result = run_caged(
        f'python "{script}" receive --pipe "{pipe}" --to "{target_root}"', cwd=str(script.parents[2]), timeout_s=120.0
    )
    server.join(timeout=10)
    if not done.is_set() or result.returncode != 0:
        raise RuntimeError(
            f"the cage account did not take the secrets: {result.outcome} {result.output.strip()[-300:]}"
        )
    return sorted(values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move secrets to the cage account through a pipe only it can open.")
    sub = parser.add_subparsers(dest="step", required=True)
    s = sub.add_parser("send")
    s.add_argument("--name", action="append", required=True)
    s.add_argument("--from", dest="source", required=True, help="your secret store's folder")
    s.add_argument("--to", required=True, help="the cage account's secret store folder")
    r = sub.add_parser("receive")
    r.add_argument("--pipe", required=True)
    r.add_argument("--to", required=True)
    args = parser.parse_args(argv)
    if args.step == "send":
        moved = send(args.name, Path(args.source), args.to)
    else:
        moved = receive(args.pipe, Path(args.to))
    print(json.dumps({"moved": moved}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
