from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
import venv
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


"""
thomas.tools.sandbox
====================

A consumer-grade safe code execution sandbox for Thomas.

Key idea: users donâ€™t just want â€œit ranâ€; they want â€œI can trust what happenedâ€.
So this module does three things:

1) SAFETY (best-effort; real isolation when available)
   Backends (auto-selected):
     - RestrictedPython (policy sandbox): fast, strict, no imports, no file I/O, no network.
     - Docker (physics sandbox): real OS isolation (read-only FS, caps dropped, optional no network, mem/cpu/pids limits).
     - Subprocess (compat): guarded imports, blocked file I/O, step limiter, unix rlimits (best-effort).

2) RECEIPTS (debuggability + trust)
   Every run gets a run_id and a run_dir with:
     - request.json, code.py, response.json

3) UX DETAILS THAT MATTER
   - Output capture keeps BOTH head and tail, so return payload (written at end) is not lost.
   - Deterministic-ish environment flags for subprocess/docker.
   - Packages can be installed offline (wheelhouse) while runtime network stays disabled.

Tool handlers:
  - sandbox.run
  - sandbox.test_snippet

Required return keys (sandbox.run):
  {"stdout": str, "stderr": str, "return_value": str, "duration_ms": float, "error": str|null}

This module returns those keys PLUS optional extras (backend, run_id, run_dir, limits, truncation flags).
Extra keys are backwards-compatible: they can be ignored by older callers.
"""


# =============================================================================
# Tool Specs
# =============================================================================

SANDBOX_RUN_SPEC: Dict[str, Any] = {
    "name": "sandbox.run",
    "category": "sandbox",
    "description": "Execute Python code in a restricted sandbox with stdout/stderr capture and timeouts.",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout_seconds": {
                "type": "integer",
                "description": "Max execution time. Default 10, max 30.",
                "default": 10,
            },
            "allow_network": {
                "type": "boolean",
                "description": "Allow network calls. Default false.",
                "default": False,
            },
            "packages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Extra pip packages to pre-install.",
                "default": [],
            },
        },
        "required": ["code"],
    },
}

SANDBOX_TEST_SNIPPET_SPEC: Dict[str, Any] = {
    "name": "sandbox.test_snippet",
    "category": "sandbox",
    "description": "Run a code snippet against test cases and return per-case pass/fail.",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "test_cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "input": {"description": "Input value (JSON-serializable recommended)"},
                        "expected": {"description": "Expected output (JSON-serializable recommended)"},
                    },
                    "required": ["input", "expected"],
                },
                "description": "List of test cases.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Max execution time (all cases). Default 10, max 30.",
                "default": 10,
            },
            "allow_network": {
                "type": "boolean",
                "description": "Allow network calls during test run. Default false.",
                "default": False,
            },
            "packages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Extra pip packages to pre-install for tests.",
                "default": [],
            },
        },
        "required": ["code", "test_cases"],
    },
}

TOOL_SPECS: List[Dict[str, Any]] = [SANDBOX_RUN_SPEC, SANDBOX_TEST_SNIPPET_SPEC]


# Optional: a simple dispatch table if your tool registry wants it.
TOOLS = {
    "sandbox.run": "sandbox_run",
    "sandbox.test_snippet": "sandbox_test_snippet",
}

def get_tool_specs() -> List[Dict[str, Any]]:
    return TOOL_SPECS


# =============================================================================
# Tunables / Policy
# =============================================================================

DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 30

MAX_CODE_BYTES = int(os.environ.get("THOMAS_SANDBOX_MAX_CODE_BYTES", "250000"))  # 250 KB

# Output capture keeps head + tail so the return sentinel survives truncation.
STDOUT_HEAD = int(os.environ.get("THOMAS_SANDBOX_STDOUT_HEAD", "262144"))  # 256 KB
STDOUT_TAIL = int(os.environ.get("THOMAS_SANDBOX_STDOUT_TAIL", "65536"))   # 64 KB
STDERR_HEAD = int(os.environ.get("THOMAS_SANDBOX_STDERR_HEAD", "262144"))  # 256 KB
STDERR_TAIL = int(os.environ.get("THOMAS_SANDBOX_STDERR_TAIL", "65536"))   # 64 KB

# Step limiter (line events). Helps prevent tight loops from just burning CPU until wall timeout.
MAX_TRACE_STEPS = int(os.environ.get("THOMAS_SANDBOX_MAX_TRACE_STEPS", "2000000"))

# Backend selection: auto | docker | restrictedpython | subprocess
SANDBOX_BACKEND = os.environ.get("THOMAS_SANDBOX_BACKEND", "auto").strip().lower()

# Runtime storage: run receipts + artifacts (created by the tool, not the sandboxed code)
RUNTIME_DIR = Path(os.environ.get("THOMAS_RUNTIME_DIR", str(Path.cwd() / "runtime")))
RUNS_DIR = Path(os.environ.get("THOMAS_SANDBOX_RUNS_DIR", str(RUNTIME_DIR / "sandbox" / "runs")))
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Docker backend â€œphysics sandboxâ€
DOCKER_IMAGE = os.environ.get("THOMAS_SANDBOX_DOCKER_IMAGE", "python:3.12-slim")
DOCKER_MEMORY = os.environ.get("THOMAS_SANDBOX_DOCKER_MEMORY", "512m")
DOCKER_CPUS = os.environ.get("THOMAS_SANDBOX_DOCKER_CPUS", "1.0")
DOCKER_PIDS_LIMIT = os.environ.get("THOMAS_SANDBOX_DOCKER_PIDS_LIMIT", "128")

# Wheelhouse cache so packages donâ€™t re-download every run
WHEELHOUSE_CACHE_DIR = Path(os.environ.get("THOMAS_SANDBOX_WHEELHOUSE_DIR", str(RUNTIME_DIR / "sandbox" / "wheelhouse_cache")))
WHEELHOUSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Host pip download toggle (trusted host action)
ALLOW_HOST_PIP_DOWNLOAD = os.environ.get("THOMAS_SANDBOX_HOST_PIP_DOWNLOAD", "1") != "0"

# Package policy:
#   allow_any (default): accept safe-token packages
#   allowlist: only allow roots listed in THOMAS_SANDBOX_ALLOWED_PACKAGES
PACKAGES_MODE = os.environ.get("THOMAS_SANDBOX_PACKAGES_MODE", "allow_any").strip().lower()
ALLOWED_PACKAGES = {p.strip().lower() for p in os.environ.get("THOMAS_SANDBOX_ALLOWED_PACKAGES", "").split(",") if p.strip()}

# Unix rlimits (best-effort) (subprocess wrapper uses these on POSIX)
UNIX_AS_LIMIT = int(os.environ.get("THOMAS_SANDBOX_UNIX_AS_LIMIT", str(512 * 1024 * 1024)))
UNIX_CPU_SECONDS = int(os.environ.get("THOMAS_SANDBOX_UNIX_CPU_SECONDS", "2"))
UNIX_FSIZE_LIMIT = int(os.environ.get("THOMAS_SANDBOX_UNIX_FSIZE_LIMIT", "0"))

# Package token validation (no URLs, no flags)
_PKG_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-\.]*(\[[A-Za-z0-9_,\-]+\])?([<>=!~]=?[A-Za-z0-9\.\*]+)?$")

SENTINEL = "__THOMAS_RETURN__:"


# =============================================================================
# Public handlers
# =============================================================================

def sandbox_run(
    code: str,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    allow_network: bool = False,
    packages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    run_id = str(uuid.uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    timeout = _clamp_timeout(timeout_seconds)

    if not isinstance(code, str):
        return _finalize(t0, run_id, run_dir, backend="none", stdout="", stderr="", return_value="", error="code must be a string")

    if len(code.encode("utf-8", errors="ignore")) > MAX_CODE_BYTES:
        return _finalize(t0, run_id, run_dir, backend="none", stdout="", stderr="", return_value="", error=f"code too large (max {MAX_CODE_BYTES} bytes)")

    pkgs = [p.strip() for p in (packages or []) if isinstance(p, str) and p.strip()]
    pkg_err = _validate_packages(pkgs)
    if pkg_err:
        return _finalize(t0, run_id, run_dir, backend="none", stdout="", stderr="", return_value="", error=pkg_err)

    backend = _choose_backend(allow_network=allow_network, packages=pkgs)

    # Persist request receipt
    _write_text(run_dir / "request.json", json.dumps({
        "run_id": run_id,
        "timestamp_unix": time.time(),
        "backend": backend,
        "timeout_seconds": timeout,
        "allow_network": allow_network,
        "packages": pkgs,
    }, ensure_ascii=False, indent=2))
    _write_text(run_dir / "code.py", code)

    try:
        if backend == "restrictedpython":
            out = _run_with_restrictedpython(code, timeout)
        elif backend == "docker":
            out = _run_with_docker(code, timeout, allow_network, pkgs)
        else:
            out = _run_with_subprocess(code, timeout, allow_network, pkgs)
    except Exception as e:
        out = _wrap_fail(str(e), traceback.format_exc())

    # Persist response receipt
    _write_text(run_dir / "response.json", json.dumps({
        "stdout": out.get("stdout", ""),
        "stderr": out.get("stderr", ""),
        "return_value": out.get("return_value", ""),
        "error": out.get("error", None),
        "exit_code": out.get("exit_code", None),
        "truncated_stdout": out.get("truncated_stdout", False),
        "truncated_stderr": out.get("truncated_stderr", False),
    }, ensure_ascii=False, indent=2))

    return _finalize(
        t0, run_id, run_dir,
        backend=backend,
        stdout=out.get("stdout", ""),
        stderr=out.get("stderr", ""),
        return_value=str(out.get("return_value", "")),
        error=out.get("error"),
        exit_code=out.get("exit_code"),
        truncated_stdout=out.get("truncated_stdout", False),
        truncated_stderr=out.get("truncated_stderr", False),
        limits=_limits_receipt(backend=backend, timeout=timeout, allow_network=allow_network),
    )


def sandbox_test_snippet(
    code: str,
    test_cases: List[Mapping[str, Any]],
    timeout_seconds: int = DEFAULT_TIMEOUT,
    allow_network: bool = False,
    packages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Runs all test cases in ONE execution for speed + consistent state.
    Contract:
      - define solve(input_data) OR main(input_data)
      - OR set a variable named result (fallback)
    """
    timeout = _clamp_timeout(timeout_seconds)
    pkgs = [p.strip() for p in (packages or []) if isinstance(p, str) and p.strip()]
    pkg_err = _validate_packages(pkgs)
    if pkg_err:
        return {"summary": {"total": 0, "passed": 0, "failed": 0}, "cases": [{"index": 0, "passed": False, "error": pkg_err}]}

    payload_cases = [{"index": i, "input": tc.get("input"), "expected": tc.get("expected")} for i, tc in enumerate(test_cases or [])]
    harness = _build_batch_test_harness(payload_cases)
    merged = f"{code.rstrip()}\n\n{harness}\n"

    run_res = sandbox_run(
        code=merged,
        timeout_seconds=timeout,
        allow_network=allow_network,
        packages=pkgs,
    )

    if run_res.get("error"):
        total = len(payload_cases)
        return {
            "summary": {"total": total, "passed": 0, "failed": total},
            "cases": [{
                "index": i,
                "passed": False,
                "actual": "",
                "expected": _safe_repr(payload_cases[i].get("expected")),
                "error": run_res.get("error"),
            } for i in range(total)],
            "run_receipt": _subset_receipt(run_res),
        }

    try:
        parsed = json.loads(run_res.get("return_value", "") or "")
    except Exception:
        parsed = None

    if not isinstance(parsed, dict) or "cases" not in parsed or "summary" not in parsed:
        total = len(payload_cases)
        return {
            "summary": {"total": total, "passed": 0, "failed": total},
            "cases": [{
                "index": i,
                "passed": False,
                "actual": "",
                "expected": _safe_repr(payload_cases[i].get("expected")),
                "error": "Harness did not return expected JSON payload.",
            } for i in range(total)],
            "run_receipt": _subset_receipt(run_res),
        }

    return {
        "summary": parsed["summary"],
        "cases": parsed["cases"],
        "run_receipt": _subset_receipt(run_res),
    }


def _subset_receipt(run_res: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": run_res.get("run_id"),
        "backend": run_res.get("backend"),
        "duration_ms": run_res.get("duration_ms"),
        "exit_code": run_res.get("exit_code"),
        "truncated_stdout": run_res.get("truncated_stdout"),
        "truncated_stderr": run_res.get("truncated_stderr"),
        "run_dir": run_res.get("run_dir"),
    }


# =============================================================================
# Backend selection
# =============================================================================

def _choose_backend(allow_network: bool, packages: List[str]) -> str:
    if SANDBOX_BACKEND in ("docker", "restrictedpython", "subprocess"):
        if SANDBOX_BACKEND == "docker":
            return "docker" if _docker_available() else "subprocess"
        if SANDBOX_BACKEND == "restrictedpython":
            if allow_network or packages:
                return "docker" if _docker_available() else "subprocess"
            return "restrictedpython" if _restrictedpython_available() else "subprocess"
        return "subprocess"

    # auto:
    # - RestrictedPython for the strict/simple case
    # - Docker when packages or network are requested OR RestrictedPython missing
    # - Subprocess as last resort
    if (not allow_network) and (len(packages) == 0) and _restrictedpython_available():
        return "restrictedpython"
    if _docker_available():
        return "docker"
    return "subprocess"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _restrictedpython_available() -> bool:
    try:
        import RestrictedPython  # noqa: F401
        return True
    except Exception:
        return False


# =============================================================================
# RestrictedPython backend (strict)
# =============================================================================

@dataclasses.dataclass
class _RPResult:
    stdout: str = ""
    stderr: str = ""
    return_value: str = ""
    error: Optional[str] = None
    exit_code: Optional[int] = 0
    truncated_stdout: bool = False
    truncated_stderr: bool = False


def _run_with_restrictedpython(code: str, timeout_seconds: int) -> Dict[str, Any]:
    """
    Strict mode: no imports, no open, safe globals injected.
    Executes in a separate process with a hard timeout.
    """
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    q: "mp.Queue[Dict[str, Any]]" = ctx.Queue()
    p = ctx.Process(target=_restrictedpython_worker, args=(code, q), daemon=True)
    p.start()
    p.join(timeout_seconds)

    if p.is_alive():
        p.terminate()
        p.join(1.0)
        return {
            "stdout": "",
            "stderr": "",
            "return_value": "",
            "error": f"Timeout after {timeout_seconds}s",
            "exit_code": None,
            "truncated_stdout": False,
            "truncated_stderr": False,
        }

    try:
        res = q.get_nowait()
    except Exception:
        return {
            "stdout": "",
            "stderr": "",
            "return_value": "",
            "error": "Sandbox process exited without result.",
            "exit_code": None,
            "truncated_stdout": False,
            "truncated_stderr": False,
        }

    return res


def _restrictedpython_worker(code: str, q) -> None:  # pragma: no cover
    out = _RPResult()
    try:
        import math as _math
        import json as _json
        import datetime as _datetime
        import collections as _collections
        import sys as _sys

        # Step limiter
        steps = {"n": 0}
        def _trace(frame, event, arg):
            if event == "line":
                steps["n"] += 1
                if steps["n"] > MAX_TRACE_STEPS:
                    raise RuntimeError(f"Step limit exceeded ({MAX_TRACE_STEPS})")
            return _trace
        _sys.settrace(_trace)

        from RestrictedPython import compile_restricted  # type: ignore
        try:
            from RestrictedPython import safe_builtins, limited_builtins  # type: ignore
        except Exception:
            from RestrictedPython.Guards import safe_builtins  # type: ignore
            limited_builtins = {}  # type: ignore

        from RestrictedPython.PrintCollector import PrintCollector  # type: ignore
        from RestrictedPython.Eval import default_guarded_getiter, default_guarded_getitem  # type: ignore
        from RestrictedPython.Guards import (  # type: ignore
            guarded_iter_unpack_sequence,
            guarded_unpack_sequence,
            safer_getattr,
            full_write_guard,
        )

        builtins_dict = dict(safe_builtins)
        try:
            builtins_dict.update(limited_builtins)
        except Exception:
            pass

        builtins_dict.pop("__import__", None)
        builtins_dict.pop("open", None)

        glb: Dict[str, Any] = {
            "__builtins__": builtins_dict,
            "__name__": "thomas_sandbox",
            "_print_": PrintCollector,
            "_getattr_": safer_getattr,
            "_getitem_": default_guarded_getitem,
            "_getiter_": default_guarded_getiter,
            "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
            "_unpack_sequence_": guarded_unpack_sequence,
            "_write_": full_write_guard,
            "math": _math,
            "json": _json,
            "datetime": _datetime,
            "collections": _collections,
        }
        loc: Dict[str, Any] = {}

        compile_res = compile_restricted(code, filename="<sandbox>", mode="exec")
        byte_code = getattr(compile_res, "code", compile_res)
        errors = getattr(compile_res, "errors", ())
        if errors:
            raise SyntaxError("\n".join(str(e) for e in errors))

        exec(byte_code, glb, loc)

        # PrintCollector output
        stdout_parts: List[str] = []
        _print_obj = loc.get("_print") or glb.get("_print")
        if callable(_print_obj):
            try:
                stdout_parts.append(str(_print_obj()))
            except Exception:
                pass

        out.stdout = "".join(stdout_parts)

        rv = loc.get("result", loc.get("return_value", ""))
        if rv is None:
            out.return_value = ""
        elif isinstance(rv, str):
            out.return_value = rv
        else:
            out.return_value = repr(rv)

        out.exit_code = 0

    except Exception as e:
        out.error = str(e)
        out.stderr = traceback.format_exc()
        out.exit_code = 1

    q.put(dataclasses.asdict(out))


# =============================================================================
# Docker backend (best isolation)
# =============================================================================

def _run_with_docker(code: str, timeout_seconds: int, allow_network: bool, packages: List[str]) -> Dict[str, Any]:
    if not _docker_available():
        return _wrap_fail("docker not available")

    wheelhouse_dir = None
    if packages:
        if not ALLOW_HOST_PIP_DOWNLOAD:
            return _wrap_fail("Host pip download disabled; cannot prepare wheelhouse for packages.")
        wheelhouse_dir, wheel_err = _ensure_wheelhouse(packages)
        if wheel_err:
            return _wrap_fail("Failed to prepare wheelhouse", wheel_err)

    with tempfile.TemporaryDirectory(prefix="thomas_sandbox_docker_") as td:
        td_path = Path(td)
        work = td_path / "work"
        work.mkdir(parents=True, exist_ok=True)

        runner_py = work / "runner.py"
        runner_py.write_text(_build_wrapper_script(code, allow_network=allow_network), encoding="utf-8")

        cmd = ["docker", "run", "--rm"]
        cmd += ["--memory", DOCKER_MEMORY, "--cpus", DOCKER_CPUS, "--pids-limit", DOCKER_PIDS_LIMIT]
        cmd += ["--read-only"]
        cmd += ["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777"]
        cmd += ["--tmpfs", "/run:rw,noexec,nosuid,size=16m,mode=1777"]
        cmd += ["--security-opt", "no-new-privileges"]
        cmd += ["--cap-drop", "ALL"]

        if not allow_network:
            cmd += ["--network", "none"]

        cmd += ["--user", "65534:65534"]
        cmd += ["-e", "PYTHONNOUSERSITE=1", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONHASHSEED=0"]
        cmd += ["-v", f"{str(work)}:/work:ro"]

        if wheelhouse_dir:
            cmd += ["-v", f"{str(wheelhouse_dir)}:/wheelhouse:ro"]

        cmd += [DOCKER_IMAGE]

        inner = []
        if wheelhouse_dir:
            inner.append("python -m pip install --no-input --disable-pip-version-check --no-index --find-links=/wheelhouse " + " ".join(packages))
        inner.append("python -I -S -B /work/runner.py")
        cmd += ["sh", "-lc", " && ".join(inner)]

        stdout_s, stderr_s, rc, trunc = _run_process_capped(cmd, timeout_seconds, STDOUT_HEAD, STDOUT_TAIL, STDERR_HEAD, STDERR_TAIL)
        out = _decode_wrapper(stdout_s, stderr_s, rc)
        out["truncated_stdout"] = trunc["stdout"]
        out["truncated_stderr"] = trunc["stderr"]
        return out


def _ensure_wheelhouse(packages: List[str]) -> Tuple[Optional[Path], Optional[str]]:
    normalized = [p.strip() for p in packages if p.strip()]
    normalized.sort()
    key = f"py{sys.version_info.major}.{sys.version_info.minor}|" + "|".join(normalized)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    wh = WHEELHOUSE_CACHE_DIR / digest
    wh.mkdir(parents=True, exist_ok=True)

    marker = wh / ".ok.json"
    if marker.exists():
        return wh, None

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PYTHONNOUSERSITE"] = "1"

    cmd = [sys.executable, "-m", "pip", "download", "--dest", str(wh), "--no-input", "--disable-pip-version-check"] + normalized

    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=240, env=env)
        if completed.returncode != 0:
            return None, (completed.stdout or "") + "\n" + (completed.stderr or "")
        marker.write_text(json.dumps({"packages": normalized, "py": f"{sys.version_info.major}.{sys.version_info.minor}"}, indent=2), encoding="utf-8")
        return wh, None
    except Exception:
        return None, traceback.format_exc()


# =============================================================================
# Subprocess backend (compat fallback)
# =============================================================================

def _run_with_subprocess(code: str, timeout_seconds: int, allow_network: bool, packages: List[str]) -> Dict[str, Any]:
    python_exe = sys.executable
    if packages:
        python_exe = str(_ensure_venv_with_packages(packages))

    with tempfile.TemporaryDirectory(prefix="thomas_sandbox_subproc_") as td:
        pth = Path(td) / "runner.py"
        pth.write_text(_build_wrapper_script(code, allow_network=allow_network), encoding="utf-8")

        cmd = [python_exe, "-I", "-S", "-B", str(pth)]
        stdout_s, stderr_s, rc, trunc = _run_process_capped(cmd, timeout_seconds, STDOUT_HEAD, STDOUT_TAIL, STDERR_HEAD, STDERR_TAIL)
        out = _decode_wrapper(stdout_s, stderr_s, rc)
        out["truncated_stdout"] = trunc["stdout"]
        out["truncated_stderr"] = trunc["stderr"]
        return out


# =============================================================================
# Wrapper script used by docker/subprocess
# =============================================================================

def _build_wrapper_script(user_code: str, allow_network: bool) -> str:
    user_b64 = base64.b64encode(user_code.encode("utf-8")).decode("ascii")
    allow_network_literal = "True" if allow_network else "False"

    blocked_always = {
        "os", "sys", "subprocess", "importlib", "builtins", "ctypes",
        "pathlib", "shutil", "tempfile", "io",
        "multiprocessing", "threading", "signal",
        "inspect", "types", "gc",
    }
    blocked_net = {
        "socket", "_socket", "ssl", "_ssl",
        "http", "urllib", "ftplib", "asyncio", "selectors",
        "smtplib", "imaplib", "poplib", "telnetlib", "xmlrpc",
        "websocket", "websockets", "requests", "aiohttp",
    }

    return f'''# Auto-generated Thomas sandbox wrapper
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
        if _steps["n"] > {MAX_TRACE_STEPS}:
            raise RuntimeError("Step limit exceeded ({MAX_TRACE_STEPS})")
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

_sys.stderr.write("\\n{SENTINEL}" + _json.dumps({{"return_value": _return_value, "error": _error}}, ensure_ascii=False) + "\\n")
if _error:
    raise SystemExit(1)
'''


def _decode_wrapper(stdout: str, stderr: str, rc: int) -> Dict[str, Any]:
    return_value = ""
    error = None
    if SENTINEL in stderr:
        before, tail = stderr.rsplit(SENTINEL, 1)
        stderr = before.rstrip()
        try:
            payload = json.loads(tail.strip())
            rv = payload.get("return_value", "")
            return_value = rv if isinstance(rv, str) else _safe_repr(rv)
            if payload.get("error"):
                error = str(payload.get("error"))
        except Exception:
            error = "Failed to parse sandbox return payload."
    if rc != 0 and error is None:
        error = f"Process exited with code {rc}"
    return {"stdout": stdout, "stderr": stderr, "return_value": return_value, "error": error, "exit_code": rc}


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


def _run_process_capped(
    cmd: List[str],
    timeout_seconds: int,
    stdout_head: int,
    stdout_tail: int,
    stderr_head: int,
    stderr_tail: int,
) -> Tuple[str, str, int, Dict[str, bool]]:
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
        except Exception:
            pass

    preexec_fn = _unix_preexec_limits if os.name != "nt" else None

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
        try:
            p.kill()
        except Exception:
            pass
        return "", "", -1, {"stdout": False, "stderr": False}

    t_out.join(timeout=0.5)
    t_err.join(timeout=0.5)

    rc = p.returncode if p.returncode is not None else 0
    return out_buf.render_text(), err_buf.render_text(), int(rc), {"stdout": out_buf.truncated, "stderr": err_buf.truncated}


def _unix_preexec_limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (UNIX_CPU_SECONDS, UNIX_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_AS, (UNIX_AS_LIMIT, UNIX_AS_LIMIT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (UNIX_FSIZE_LIMIT, UNIX_FSIZE_LIMIT))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except Exception:
        pass


def _child_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# =============================================================================
# Venv package caching (subprocess fallback)
# =============================================================================

def _ensure_venv_with_packages(packages: List[str]) -> Path:
    venv_root = Path(os.environ.get("THOMAS_SANDBOX_VENV_DIR", str(RUNTIME_DIR / "sandbox" / "venvs")))
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
# Test harness
# =============================================================================

def _build_batch_test_harness(cases: List[Dict[str, Any]]) -> str:
    cases_json = _json_dumps_best_effort(cases)
    return f'''
# --- Thomas sandbox.test_snippet batch harness ---
__thomas_cases = json.loads({cases_json!r})

def __thomas_safe(v):
    try:
        json.dumps(v, ensure_ascii=False)
        return v
    except Exception:
        return repr(v)

out_cases = []
passed = 0

for c in __thomas_cases:
    idx = c.get("index")
    inp = c.get("input")
    exp = c.get("expected")
    actual = None
    err = None
    ok = False
    try:
        if "solve" in globals():
            actual = solve(inp)
        elif "main" in globals():
            actual = main(inp)
        elif "result" in globals():
            actual = result
        else:
            raise NameError("Provide solve(input_data) or main(input_data), or set variable result.")
        ok = (actual == exp)
    except Exception as e:
        err = str(e)
        ok = False

    if ok:
        passed += 1

    out_cases.append({{
        "index": idx,
        "passed": ok,
        "actual": __thomas_safe(actual),
        "expected": __thomas_safe(exp),
        "error": err,
    }})

summary = {{"total": len(__thomas_cases), "passed": passed, "failed": len(__thomas_cases) - passed}}
result = json.dumps({{"summary": summary, "cases": out_cases}}, ensure_ascii=False)
'''


# =============================================================================
# Validation / receipts / helpers
# =============================================================================

def _clamp_timeout(timeout_seconds: int) -> int:
    try:
        t = int(timeout_seconds)
    except Exception:
        t = DEFAULT_TIMEOUT
    if t <= 0:
        t = DEFAULT_TIMEOUT
    return max(1, min(MAX_TIMEOUT, t))


def _validate_packages(packages: List[str]) -> Optional[str]:
    for p in packages:
        if not p or not isinstance(p, str):
            return "invalid package entry"

        bad_tokens = ["--", "://", "@", "file:", "git+", "svn+", "hg+", "bzr+", "\n", "\r", "\t", ";", "&", "|"]
        if any(tok in p for tok in bad_tokens) or p.strip().startswith("-"):
            return f"unsafe package spec rejected: {p!r}"
        if not _PKG_SAFE_RE.match(p):
            return f"package spec rejected (not a safe token): {p!r}"

        root = p.split("[", 1)[0]
        root = re.split(r"[<>=!~]", root, 1)[0].strip().lower()
        if PACKAGES_MODE == "allowlist" and root not in ALLOWED_PACKAGES:
            return f"package not allowed by policy: {root!r}"

    return None


def _limits_receipt(backend: str, timeout: int, allow_network: bool) -> Dict[str, Any]:
    if backend == "docker":
        return {
            "timeout_seconds": timeout,
            "network": "enabled" if allow_network else "disabled",
            "docker": {
                "image": DOCKER_IMAGE,
                "memory": DOCKER_MEMORY,
                "cpus": DOCKER_CPUS,
                "pids_limit": DOCKER_PIDS_LIMIT,
                "read_only_fs": True,
                "caps_dropped": True,
                "no_new_privileges": True,
            },
        }
    if backend == "restrictedpython":
        return {
            "timeout_seconds": timeout,
            "network": "disabled",
            "restrictedpython": {"imports": "disabled", "file_io": "blocked", "step_limit": MAX_TRACE_STEPS},
        }
    return {
        "timeout_seconds": timeout,
        "network": "enabled" if allow_network else "disabled (best-effort)",
        "subprocess": {"python_isolated_flags": ["-I", "-S", "-B"], "step_limit": MAX_TRACE_STEPS, "unix_rlimits": (os.name != "nt")},
    }


def _finalize(
    t0: float,
    run_id: str,
    run_dir: Path,
    backend: str,
    stdout: str,
    stderr: str,
    return_value: str,
    error: Optional[str],
    exit_code: Optional[int] = None,
    truncated_stdout: bool = False,
    truncated_stderr: bool = False,
    limits: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "stdout": stdout,
        "stderr": stderr,
        "return_value": return_value,
        "duration_ms": float((time.perf_counter() - t0) * 1000.0),
        "error": error,
        "backend": backend,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "exit_code": exit_code,
        "truncated_stdout": truncated_stdout,
        "truncated_stderr": truncated_stderr,
        "limits": limits or {},
    }


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception:
        try:
            return str(value)
        except Exception:
            return "<unrepr-able>"


def _json_dumps_best_effort(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps(_safe_repr(value), ensure_ascii=False)


def _write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except Exception:
        pass


def _wrap_fail(msg: str, detail: str = "") -> Dict[str, Any]:
    return {"stdout": "", "stderr": detail, "return_value": "", "error": msg, "exit_code": None, "truncated_stdout": False, "truncated_stderr": False}
