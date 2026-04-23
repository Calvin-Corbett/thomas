"""Helper utilities for sandbox module (internal use only)."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import traceback
import venv
from collections import deque
from pathlib import Path
from typing import Any

# =============================================================================
# Process execution with capped capture (head + tail)
# =============================================================================


class _CappedBuffer:
    def __init__(self, head_limit: int, tail_limit: int):
        self.head_limit = max(0, int(head_limit))
        self.tail_limit = max(0, int(tail_limit))
        self._head: bytearray = bytearray()
        self._tail: deque[int] = deque(maxlen=self.tail_limit) if self.tail_limit > 0 else deque()
        self.truncated = False

    def push(self, data: bytes) -> None:
        if not data:
            return
        if len(self._head) < self.head_limit:
            take = min(len(data), self.head_limit - len(self._head))
            if take:
                self._head.extend(data[:take])
            rest = data[take:]
        else:
            rest = data

        if rest:
            self.truncated = True
            if self.tail_limit > 0:
                for b in rest:
                    self._tail.append(b)

    def render_text(self) -> str:
        head = bytes(self._head)
        tail = bytes(self._tail) if self.tail_limit > 0 else b""
        if self.truncated:
            mid = b"\n...[output truncated]...\n"
            data = head + mid + tail if tail else head + mid
        else:
            data = head
        return data.decode("utf-8", errors="replace")


def run_process_capped(
    cmd: list[str],
    timeout_seconds: int,
    stdout_head: int,
    stdout_tail: int,
    stderr_head: int,
    stderr_tail: int,
    unix_cpu_seconds: int = 2,
    unix_as_limit: int = 512 * 1024 * 1024,
    unix_fsize_limit: int = 0,
) -> tuple[str, str, int, dict[str, bool]]:
    import threading

    out_buf = _CappedBuffer(stdout_head, stdout_tail)
    err_buf = _CappedBuffer(stderr_head, stderr_tail)

    def reader(stream, buf: _CappedBuffer):
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                buf.push(chunk)
        except OSError:
            pass

    def _preexec() -> None:
        _unix_preexec_limits(unix_cpu_seconds, unix_as_limit, unix_fsize_limit)

    preexec_fn = _preexec if os.name != "nt" else None

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        preexec_fn=preexec_fn,
        env=_child_env(),
    )

    t_out = threading.Thread(target=reader, args=(p.stdout, out_buf), daemon=True)  # type: ignore[arg-type]
    t_err = threading.Thread(target=reader, args=(p.stderr, err_buf), daemon=True)  # type: ignore[arg-type]
    t_out.start()
    t_err.start()

    try:
        p.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError, ProcessLookupError):
            p.kill()
        return "", "", -1, {"stdout": False, "stderr": False}

    t_out.join(timeout=0.5)
    t_err.join(timeout=0.5)

    rc = p.returncode if p.returncode is not None else 0
    return (
        out_buf.render_text(),
        err_buf.render_text(),
        int(rc),
        {"stdout": out_buf.truncated, "stderr": err_buf.truncated},
    )


def _unix_preexec_limits(unix_cpu_seconds: int, unix_as_limit: int, unix_fsize_limit: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (unix_cpu_seconds, unix_cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (unix_as_limit, unix_as_limit))
        resource.setrlimit(resource.RLIMIT_FSIZE, (unix_fsize_limit, unix_fsize_limit))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (OSError, ValueError):
        pass


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# =============================================================================
# Venv package caching (subprocess fallback)
# =============================================================================


def ensure_venv_with_packages(packages: list[str], runtime_dir: Path) -> Path:
    venv_root = Path(os.environ.get("THOMAS_SANDBOX_VENV_DIR", str(runtime_dir / "sandbox" / "venvs")))
    venv_root.mkdir(parents=True, exist_ok=True)

    normalized = [p.strip() for p in packages if p and p.strip()]
    normalized.sort()
    key = f"py{sys.version_info.major}.{sys.version_info.minor}|" + "|".join(normalized)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    venv_dir = venv_root / digest
    python_path = _venv_python_executable(venv_dir)

    marker = venv_dir / ".installed.json"
    if python_path.exists() and marker.exists():
        return python_path

    venv_dir.mkdir(parents=True, exist_ok=True)
    if not python_path.exists():
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(str(venv_dir))

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PYTHONNOUSERSITE"] = "1"

    cmd = [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "--no-input"] + normalized
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=240, env=env)
    if completed.returncode != 0:
        raise RuntimeError("pip install failed:\n" + (completed.stdout or "") + "\n" + (completed.stderr or ""))

    marker.write_text(json.dumps({"packages": normalized}, indent=2), encoding="utf-8")
    return python_path


def _venv_python_executable(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


# =============================================================================
# Wheelhouse (Docker packages)
# =============================================================================


def ensure_wheelhouse(packages: list[str], wheelhouse_cache_dir: Path) -> tuple[Path | None, str | None]:
    normalized = [p.strip() for p in packages if p.strip()]
    normalized.sort()
    key = f"py{sys.version_info.major}.{sys.version_info.minor}|" + "|".join(normalized)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    wh = wheelhouse_cache_dir / digest
    wh.mkdir(parents=True, exist_ok=True)

    marker = wh / ".ok.json"
    if marker.exists():
        return wh, None

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PYTHONNOUSERSITE"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(wh),
        "--no-input",
        "--disable-pip-version-check",
    ] + normalized

    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=240, env=env)
        if completed.returncode != 0:
            return None, (completed.stdout or "") + "\n" + (completed.stderr or "")
        marker.write_text(
            json.dumps({"packages": normalized, "py": f"{sys.version_info.major}.{sys.version_info.minor}"}, indent=2),
            encoding="utf-8",
        )
        return wh, None
    except (OSError, subprocess.CalledProcessError, TimeoutError):
        return None, traceback.format_exc()


# =============================================================================
# Wrapper script building
# =============================================================================


def build_wrapper_script(user_code: str, allow_network: bool, max_trace_steps: int, sentinel: str) -> str:
    user_b64 = base64.b64encode(user_code.encode("utf-8")).decode("ascii")
    allow_network_literal = "True" if allow_network else "False"

    blocked_always = {
        "os",
        "sys",
        "subprocess",
        "importlib",
        "builtins",
        "ctypes",
        "pathlib",
        "shutil",
        "tempfile",
        "io",
        "multiprocessing",
        "threading",
        "signal",
        "inspect",
        "types",
        "gc",
    }
    blocked_net = {
        "socket",
        "_socket",
        "ssl",
        "_ssl",
        "http",
        "urllib",
        "ftplib",
        "asyncio",
        "selectors",
        "smtplib",
        "imaplib",
        "poplib",
        "telnetlib",
        "xmlrpc",
        "websocket",
        "websockets",
        "requests",
        "aiohttp",
    }

    return f"""# Auto-generated Thomas sandbox wrapper
import base64 as _b64
import json as _json
import math as _math
import datetime as _datetime
import collections as _collections
import traceback as _traceback
import sys as _sys

USER_CODE = _b64.b64decode("{user_b64}").decode("utf-8")

_ALLOW_NETWORK = {allow_network_literal}
_BLOCK_ALWAYS = {blocked_always}
_BLOCK_NET = {blocked_net}

_real_import = __import__
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = (name or "").split(".", 1)[0]
    if root in _BLOCK_ALWAYS:
        raise ImportError(f"Import blocked: {{name}}")
    if (not _ALLOW_NETWORK) and (root in _BLOCK_NET):
        raise ImportError(f"Network-related import blocked: {{name}}")
    return _real_import(name, globals, locals, fromlist, level)

_SAFE_BUILTINS = {{}}
for _name in [
    "abs","all","any","bool","callable","chr","complex","dict","divmod","enumerate",
    "filter","float","format","hash","hex","int","isinstance","issubclass","iter",
    "len","list","map","max","min","next","oct","ord","pow","print","range","repr","globals",
    "reversed","round","set","slice","sorted","str","sum","tuple","zip",
    "Exception","BaseException","NameError","TypeError","ValueError","RuntimeError"
]:
    _SAFE_BUILTINS[_name] = getattr(__builtins__, _name)

def _blocked(*args, **kwargs):
    raise PermissionError("Operation blocked in sandbox")

_SAFE_BUILTINS["open"] = _blocked
_SAFE_BUILTINS["eval"] = _blocked
_SAFE_BUILTINS["exec"] = _blocked
_SAFE_BUILTINS["compile"] = _blocked
_SAFE_BUILTINS["__import__"] = _guarded_import

_steps = {{"n": 0}}
def _trace(frame, event, arg):
    if event == "line":
        _steps["n"] += 1
        if _steps["n"] > {max_trace_steps}:
            raise RuntimeError("Step limit exceeded ({max_trace_steps})")
    return _trace
_sys.settrace(_trace)

exec_globals = {{
    "__builtins__": _SAFE_BUILTINS,
    "math": _math,
    "json": _json,
    "datetime": _datetime,
    "collections": _collections,
}}
exec_locals = exec_globals

_return_value = ""
_error = None
try:
    exec(compile(USER_CODE, "<sandbox>", "exec"), exec_globals, exec_locals)
    rv = exec_locals.get("result", exec_locals.get("return_value", ""))
    if rv is None:
        _return_value = ""
    elif isinstance(rv, str):
        _return_value = rv
    else:
        _return_value = repr(rv)
except Exception as e:
    _error = str(e)
    _sys.stderr.write(_traceback.format_exc())

_sys.stderr.write("\\n{sentinel}" + _json.dumps({{"return_value": _return_value, "error": _error}}, ensure_ascii=False) + "\\n")
if _error:
    raise SystemExit(1)
"""


def decode_wrapper(stdout: str, stderr: str, rc: int, sentinel: str) -> dict[str, Any]:
    """Decode wrapper script output and extract return value."""
    return_value = ""
    error = None
    if sentinel in stderr:
        before, tail = stderr.rsplit(sentinel, 1)
        stderr = before.rstrip()
        try:
            payload = json.loads(tail.strip())
            rv = payload.get("return_value", "")
            return_value = rv if isinstance(rv, str) else _safe_repr(rv)
            if payload.get("error"):
                error = str(payload.get("error"))
        except (ValueError, KeyError, AttributeError):
            error = "Failed to parse sandbox return payload."
    if rc != 0 and error is None:
        error = f"Process exited with code {rc}"
    return {"stdout": stdout, "stderr": stderr, "return_value": return_value, "error": error, "exit_code": rc}


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception:
        # REVIEWED: broad catch — repr() can raise various exceptions
        try:
            return str(value)
        except Exception:
            # REVIEWED: broad catch — str() can raise various exceptions
            return "<unrepr-able>"


def json_dumps_best_effort(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(_safe_repr(value), ensure_ascii=False)


def write_text(path: Path, text: str) -> None:
    with contextlib.suppress(OSError, UnicodeEncodeError):
        path.write_text(text, encoding="utf-8")


def wrap_fail(msg: str, detail: str = "") -> dict[str, Any]:
    return {
        "stdout": "",
        "stderr": detail,
        "return_value": "",
        "error": msg,
        "exit_code": None,
        "truncated_stdout": False,
        "truncated_stderr": False,
    }
