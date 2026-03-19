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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

"""
thomas.tools.sandbox
====================

A consumer-grade safe code execution sandbox for Thomas.

Key idea: users don't just want "it ran"; they want "I can trust what happened".
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

SANDBOX_RUN_SPEC: dict[str, Any] = {
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

SANDBOX_TEST_SNIPPET_SPEC: dict[str, Any] = {
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

TOOL_SPECS: list[dict[str, Any]] = [SANDBOX_RUN_SPEC, SANDBOX_TEST_SNIPPET_SPEC]


# Optional: a simple dispatch table if your tool registry wants it.
TOOLS = {
    "sandbox.run": "sandbox_run",
    "sandbox.test_snippet": "sandbox_test_snippet",
}


def get_tool_specs() -> list[dict[str, Any]]:
    return TOOL_SPECS


# =============================================================================
# Tunables / Policy
# =============================================================================

DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 30

MAX_CODE_BYTES = int(os.environ.get("THOMAS_SANDBOX_MAX_CODE_BYTES", "250000"))  # 250 KB

# Output capture keeps head + tail so the return sentinel survives truncation.
STDOUT_HEAD = int(os.environ.get("THOMAS_SANDBOX_STDOUT_HEAD", "262144"))  # 256 KB
STDOUT_TAIL = int(os.environ.get("THOMAS_SANDBOX_STDOUT_TAIL", "65536"))  # 64 KB
STDERR_HEAD = int(os.environ.get("THOMAS_SANDBOX_STDERR_HEAD", "262144"))  # 256 KB
STDERR_TAIL = int(os.environ.get("THOMAS_SANDBOX_STDERR_TAIL", "65536"))  # 64 KB

# Step limiter (line events). Helps prevent tight loops from just burning CPU until wall timeout.
MAX_TRACE_STEPS = int(os.environ.get("THOMAS_SANDBOX_MAX_TRACE_STEPS", "2000000"))

# Backend selection: auto | docker | restrictedpython | subprocess
SANDBOX_BACKEND = os.environ.get("THOMAS_SANDBOX_BACKEND", "auto").strip().lower()

# Runtime storage: run receipts + artifacts (created by the tool, not the sandboxed code)
_DEFAULT_DATA_DIR = os.environ.get("THOMAS_DATA_DIR")
if _DEFAULT_DATA_DIR:
    _DEFAULT_DATA_ROOT = Path(_DEFAULT_DATA_DIR).expanduser()
    _DEFAULT_PROFILE = str(os.environ.get("THOMAS_PROFILE", "")).strip()
    if _DEFAULT_PROFILE:
        _DEFAULT_DATA_ROOT = _DEFAULT_DATA_ROOT / _DEFAULT_PROFILE
else:
    _DEFAULT_DATA_ROOT = Path.home() / ".thomas"
RUNTIME_DIR = Path(os.environ.get("THOMAS_RUNTIME_DIR", str(_DEFAULT_DATA_ROOT / "runtime")))
RUNS_DIR = Path(os.environ.get("THOMAS_SANDBOX_RUNS_DIR", str(RUNTIME_DIR / "sandbox" / "runs")))
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Docker backend "physics sandbox"
DOCKER_IMAGE = os.environ.get("THOMAS_SANDBOX_DOCKER_IMAGE", "python:3.12-slim")
DOCKER_MEMORY = os.environ.get("THOMAS_SANDBOX_DOCKER_MEMORY", "512m")
DOCKER_CPUS = os.environ.get("THOMAS_SANDBOX_DOCKER_CPUS", "1.0")
DOCKER_PIDS_LIMIT = os.environ.get("THOMAS_SANDBOX_DOCKER_PIDS_LIMIT", "128")

# Wheelhouse cache so packages don't re-download every run
WHEELHOUSE_CACHE_DIR = Path(
    os.environ.get("THOMAS_SANDBOX_WHEELHOUSE_DIR", str(RUNTIME_DIR / "sandbox" / "wheelhouse_cache"))
)
WHEELHOUSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Host pip download toggle (trusted host action)
ALLOW_HOST_PIP_DOWNLOAD = os.environ.get("THOMAS_SANDBOX_HOST_PIP_DOWNLOAD", "1") != "0"

# Package policy:
#   allow_any (default): accept safe-token packages
#   allowlist: only allow roots listed in THOMAS_SANDBOX_ALLOWED_PACKAGES
PACKAGES_MODE = os.environ.get("THOMAS_SANDBOX_PACKAGES_MODE", "allow_any").strip().lower()
ALLOWED_PACKAGES = {
    p.strip().lower() for p in os.environ.get("THOMAS_SANDBOX_ALLOWED_PACKAGES", "").split(",") if p.strip()
}

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
    packages: list[str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    run_id = str(uuid.uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    timeout = _clamp_timeout(timeout_seconds)

    if not isinstance(code, str):
        return _finalize(
            t0, run_id, run_dir, backend="none", stdout="", stderr="", return_value="", error="code must be a string"
        )

    if len(code.encode("utf-8", errors="ignore")) > MAX_CODE_BYTES:
        return _finalize(
            t0,
            run_id,
            run_dir,
            backend="none",
            stdout="",
            stderr="",
            return_value="",
            error=f"code too large (max {MAX_CODE_BYTES} bytes)",
        )

    pkgs = [p.strip() for p in (packages or []) if isinstance(p, str) and p.strip()]
    pkg_err = _validate_packages(pkgs)
    if pkg_err:
        return _finalize(t0, run_id, run_dir, backend="none", stdout="", stderr="", return_value="", error=pkg_err)

    backend = _choose_backend(allow_network=allow_network, packages=pkgs)

    # Persist request receipt
    _write_text(
        run_dir / "request.json",
        json.dumps(
            {
                "run_id": run_id,
                "timestamp_unix": time.time(),
                "backend": backend,
                "timeout_seconds": timeout,
                "allow_network": allow_network,
                "packages": pkgs,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
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
    _write_text(
        run_dir / "response.json",
        json.dumps(
            {
                "stdout": out.get("stdout", ""),
                "stderr": out.get("stderr", ""),
                "return_value": out.get("return_value", ""),
                "error": out.get("error", None),
                "exit_code": out.get("exit_code", None),
                "truncated_stdout": out.get("truncated_stdout", False),
                "truncated_stderr": out.get("truncated_stderr", False),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    return _finalize(
        t0,
        run_id,
        run_dir,
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
    test_cases: list[Mapping[str, Any]],
    timeout_seconds: int = DEFAULT_TIMEOUT,
    allow_network: bool = False,
    packages: list[str] | None = None,
) -> dict[str, Any]:
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
        return {
            "summary": {"total": 0, "passed": 0, "failed": 0},
            "cases": [{"index": 0, "passed": False, "error": pkg_err}],
        }

    payload_cases = [
        {"index": i, "input": tc.get("input"), "expected": tc.get("expected")} for i, tc in enumerate(test_cases or [])
    ]
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
            "cases": [
                {
                    "index": i,
                    "passed": False,
                    "actual": "",
                    "expected": _safe_repr(payload_cases[i].get("expected")),
                    "error": run_res.get("error"),
                }
                for i in range(total)
            ],
            "run_receipt": _subset_receipt(run_res),
        }

    try:
        parsed = json.loads(run_res.get("return_value", "") or "")
    except json.JSONDecodeError:
        parsed = None

    if not isinstance(parsed, dict) or "cases" not in parsed or "summary" not in parsed:
        total = len(payload_cases)
        return {
            "summary": {"total": total, "passed": 0, "failed": total},
            "cases": [
                {
                    "index": i,
                    "passed": False,
                    "actual": "",
                    "expected": _safe_repr(payload_cases[i].get("expected")),
                    "error": "Harness did not return expected JSON payload.",
                }
                for i in range(total)
            ],
            "run_receipt": _subset_receipt(run_res),
        }

    return {
        "summary": parsed["summary"],
        "cases": parsed["cases"],
        "run_receipt": _subset_receipt(run_res),
    }


def _subset_receipt(run_res: dict[str, Any]) -> dict[str, Any]:
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


def _choose_backend(allow_network: bool, packages: list[str]) -> str:
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
    except ImportError:
        return False


# =============================================================================
# RestrictedPython backend (strict)
# =============================================================================


@dataclasses.dataclass
class _RPResult:
    stdout: str = ""
    stderr: str = ""
    return_value: str = ""
    error: str | None = None
    exit_code: int | None = 0
    truncated_stdout: bool = False
    truncated_stderr: bool = False


def _run_with_restrictedpython(code: str, timeout_seconds: int) -> dict[str, Any]:
    """
    Strict mode: no imports, no open, safe globals injected.
    Executes in a separate process with a hard timeout.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    q: mp.Queue[dict[str, Any]] = ctx.Queue()
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
    except (OSError, RuntimeError):
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
        import collections as _collections
        import datetime as _datetime
        import json as _json
        import math as _math
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
            from RestrictedPython import limited_builtins, safe_builtins  # type: ignore
        except ImportError:
            from RestrictedPython.Guards import safe_builtins  # type: ignore

            limited_builtins = {}  # type: ignore

        from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter  # type: ignore
        from RestrictedPython.Guards import (  # type: ignore
            full_write_guard,
            guarded_iter_unpack_sequence,
            guarded_unpack_sequence,
            safer_getattr,
        )
        from RestrictedPython.PrintCollector import PrintCollector  # type: ignore

        builtins_dict = dict(safe_builtins)
        try:
            builtins_dict.update(limited_builtins)
        except (TypeError, AttributeError):
            pass

        builtins_dict.pop("__import__", None)
        builtins_dict.pop("open", None)

        glb: dict[str, Any] = {
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
        loc: dict[str, Any] = {}

        compile_res = compile_restricted(code, filename="<sandbox>", mode="exec")
        byte_code = getattr(compile_res, "code", compile_res)
        errors = getattr(compile_res, "errors", ())
        if errors:
            raise SyntaxError("\n".join(str(e) for e in errors))

        exec(byte_code, glb, loc)

        # PrintCollector output
        stdout_parts: list[str] = []
        _print_obj = loc.get("_print") or glb.get("_print")
        if callable(_print_obj):
            try:
                stdout_parts.append(str(_print_obj()))
            except (TypeError, RuntimeError):
                # REVIEWED: broad catch — PrintCollector output may raise various errors
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


def _run_with_docker(code: str, timeout_seconds: int, allow_network: bool, packages: list[str]) -> dict[str, Any]:
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
            inner.append(
                "python -m pip install --no-input --disable-pip-version-check --no-index --find-links=/wheelhouse "
                + " ".join(packages)
            )
        inner.append("python -I -S -B /work/runner.py")
        cmd += ["sh", "-lc", " && ".join(inner)]

        stdout_s, stderr_s, rc, trunc = _run_process_capped(
            cmd, timeout_seconds, STDOUT_HEAD, STDOUT_TAIL, STDERR_HEAD, STDERR_TAIL
        )
        out = _decode_wrapper(stdout_s, stderr_s, rc)
        out["truncated_stdout"] = trunc["stdout"]
        out["truncated_stderr"] = trunc["stderr"]
        return out


def _ensure_wheelhouse(packages: list[str]) -> tuple[Path | None, str | None]:
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
# Subprocess backend (compat fallback)
# =============================================================================


def _run_with_subprocess(code: str, timeout_seconds: int, allow_network: bool, packages: list[str]) -> dict[str, Any]:
    python_exe = sys.executable
    if packages:
        python_exe = str(_ensure_venv_with_packages(packages))

    with tempfile.TemporaryDirectory(prefix="thomas_sandbox_subproc_") as td:
        pth = Path(td) / "runner.py"
        pth.write_text(_build_wrapper_script(code, allow_network=allow_network), encoding="utf-8")

        cmd = [python_exe, "-I", "-S", "-B", str(pth)]
        stdout_s, stderr_s, rc, trunc = _run_process_capped(
            cmd, timeout_seconds, STDOUT_HEAD, STDOUT_TAIL, STDERR_HEAD, STDERR_TAIL
        )
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
"""


def _decode_wrapper(stdout: str, stderr: str, rc: int) -> dict[str, Any]:
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
        except (ValueError, KeyError, AttributeError):
            error = "Failed to parse sandbox return payload."
    if rc != 0 and error is None:
        error = f"Process exited with code {rc}"
    return {"stdout": stdout, "stderr": stderr, "return_value": return_value, "error": error, "exit_code": rc}


# =============================================================================
# Process execution with capped capture (head + tail)
# =============================================================================
