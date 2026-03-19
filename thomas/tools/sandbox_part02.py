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
    cmd: list[str],
    timeout_seconds: int,
    stdout_head: int,
    stdout_tail: int,
    stderr_head: int,
    stderr_tail: int,
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
        except (OSError, ProcessLookupError):
            pass
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


def _unix_preexec_limits():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (UNIX_CPU_SECONDS, UNIX_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_AS, (UNIX_AS_LIMIT, UNIX_AS_LIMIT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (UNIX_FSIZE_LIMIT, UNIX_FSIZE_LIMIT))
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


def _ensure_venv_with_packages(packages: list[str]) -> Path:
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


def _build_batch_test_harness(cases: list[dict[str, Any]]) -> str:
    cases_json = _json_dumps_best_effort(cases)
    return f"""
# --- Thomas sandbox.test_snippet batch harness ---
__thomas_cases = json.loads({cases_json!r})

def __thomas_safe(v):
    try:
        json.dumps(v, ensure_ascii=False)
        return v
    except (TypeError, ValueError):
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
"""


# =============================================================================
# Validation / receipts / helpers
# =============================================================================


def _clamp_timeout(timeout_seconds: int) -> int:
    try:
        t = int(timeout_seconds)
    except (ValueError, TypeError):
        t = DEFAULT_TIMEOUT
    if t <= 0:
        t = DEFAULT_TIMEOUT
    return max(1, min(MAX_TIMEOUT, t))


def _validate_packages(packages: list[str]) -> str | None:
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


def _limits_receipt(backend: str, timeout: int, allow_network: bool) -> dict[str, Any]:
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
        "subprocess": {
            "python_isolated_flags": ["-I", "-S", "-B"],
            "step_limit": MAX_TRACE_STEPS,
            "unix_rlimits": (os.name != "nt"),
        },
    }


def _finalize(
    t0: float,
    run_id: str,
    run_dir: Path,
    backend: str,
    stdout: str,
    stderr: str,
    return_value: str,
    error: str | None,
    exit_code: int | None = None,
    truncated_stdout: bool = False,
    truncated_stderr: bool = False,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        # REVIEWED: broad catch — repr() can raise various exceptions
        try:
            return str(value)
        except Exception:
            # REVIEWED: broad catch — str() can raise various exceptions
            return "<unrepr-able>"


def _json_dumps_best_effort(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(_safe_repr(value), ensure_ascii=False)


def _write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except (OSError, UnicodeEncodeError):
        pass


def _wrap_fail(msg: str, detail: str = "") -> dict[str, Any]:
    return {
        "stdout": "",
        "stderr": detail,
        "return_value": "",
        "error": msg,
        "exit_code": None,
        "truncated_stdout": False,
        "truncated_stderr": False,
    }
