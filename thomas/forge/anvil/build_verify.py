"""Engine-side verification — the RUN/TEST step of the reason→edit→verify loop.

The dispatched agent is edit-only (it has no shell), but the build is a LOOP,
not a one-shot edit. After the agent's edit pass the *engine* — ordinary Python
in this process — runs a REAL check over the files the run changed and reflects
its REAL exit code back into the same streamed transcript. Nothing here is ever
fabricated: the pass/fail shown is the genuine returncode of a genuine subprocess.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.tools.web_preflight import (
    LocalAssetReferenceParser,
    artifact_preflight_failures,
    browser_smoke_files,
    duplicate_script_includes,
    has_obvious_top_level_throw,
    javascript_syntax_error,
    mask_js_strings_and_comments,
    orphaned_web_assets,
    owners_by_mention,
)

from .bridge_config import emergency_stop_active
from .bridge_prompts import compose_fix_prompt
from .forge_event_stream import FORGE_EVENT_KEY
from .web_artifact_smoke import smoke_html_artifacts

# A small, self-contained verifier program: byte-compile each changed file and
# import each changed package module. A syntax error (py_compile) or an import
# error raises -> the subprocess exits non-zero -> the run is honestly a failure.
_VERIFY_SRC = (
    "import csv, html.parser, importlib, json, pathlib, shutil, subprocess, sys, py_compile, xml.etree.ElementTree as ET, zipfile\n"
    "files = json.loads(sys.argv[1])\n"
    "mods = json.loads(sys.argv[2])\n"
    "preflight_failures = json.loads(sys.argv[3])\n"
    "assert not preflight_failures, '; '.join(preflight_failures)\n"
    "read_only = []\n"
    "for f in files:\n"
    "    p=pathlib.Path(f); raw=p.read_bytes(); ext=p.suffix.lower()\n"
    "    if ext=='.py': py_compile.compile(f,doraise=True); print('compiled '+f)\n"
    "    elif ext in {'.js','.mjs','.cjs'}:\n"
    "        node=shutil.which('node'); assert node,'node is required to verify JavaScript'; r=subprocess.run([node,'--check',f],capture_output=True,text=True); assert r.returncode==0,r.stdout+r.stderr; print('checked '+f)\n"
    "    elif ext in {'.html','.htm'}: text=raw.decode('utf-8'); parser=html.parser.HTMLParser(); parser.feed(text); assert '<' in text and '>' in text,'HTML has no elements'; print('parsed '+f)\n"
    "    elif ext=='.json': json.loads(raw.decode('utf-8')); print('parsed '+f)\n"
    "    elif ext=='.csv': rows=list(csv.reader(raw.decode('utf-8-sig').splitlines())); assert rows,'CSV is empty'; print('parsed '+f)\n"
    "    elif ext in {'.svg','.xml'}: ET.fromstring(raw); print('parsed '+f)\n"
    "    elif ext=='.css': text=raw.decode('utf-8'); assert text.count('{')==text.count('}'),'unbalanced CSS braces'; print('checked '+f)\n"
    "    elif ext=='.pdf': assert raw.startswith(b'%PDF-'),'invalid PDF header'; print('opened '+f)\n"
    "    elif ext in {'.docx','.xlsx','.pptx'}: assert zipfile.is_zipfile(p),'invalid Office document'; print('opened '+f)\n"
    "    elif ext=='.png': assert raw.startswith(b'\\x89PNG\\r\\n\\x1a\\n'),'invalid PNG'; print('opened '+f)\n"
    "    elif ext in {'.jpg','.jpeg'}: assert raw.startswith(b'\\xff\\xd8') and raw.endswith(b'\\xff\\xd9'),'invalid JPEG'; print('opened '+f)\n"
    "    else: raw.decode('utf-8'); read_only.append(f); print('read '+f)\n"
    "for m in mods:\n"
    "    importlib.import_module(m)\n"
    "    print('imported ' + m)\n"
    "print('STATIC_VERIFY_OK: ' + str(len(files) - len(read_only)) + ' files checked, '"
    " + (str(len(read_only)) + ' read only, ' if read_only else '') + str(len(mods)) + ' imported')\n"
)
# Why the summary separates "checked" from "read only":
#
# The `else` arm above is the fallback for every extension this program has no
# real check for -- .ts, .go, .rs, .sh, .sql, .md and the rest. All it does is
# decode the bytes as UTF-8, so it passes for any text file and cannot fail for a
# reason anyone cares about. Whole languages were being counted in
# "N files checked", which is the same shape as a skipped browser smoke reading
# as a pass: a check that could not have found anything, reported as one that
# found nothing wrong.
#
# The per-file lines were always honest -- `compiled`/`parsed`/`checked` for the
# real arms, `read` for this one -- so only the total lied. A run whose one
# changed file is a .ts now says "0 files checked, 1 read only", which is a
# statement someone can act on, instead of "1 files checked".
#
# Deliberately unchanged: this still exits 0. Reading a text asset is a weak
# check, not a failure, and turning it into one would break every run that
# legitimately emits a .md alongside its code. Making the count honest is what
# was actually wrong here.

_REPAIR_TRUNCATION_SUFFIXES = {".css", ".html", ".htm", ".js", ".mjs", ".cjs"}
_REPAIR_TRUNCATION_MIN_BYTES = 1024
_REPAIR_TRUNCATION_RATIO = 0.25

# The deterministic web preflight now lives in ``thomas.tools.web_preflight`` so
# the marketplace verifier can run it too -- ``marketplace`` may not import
# ``forge``, and both layers already depend on ``tools``. The old private names
# are kept as aliases: they are the names about ten test modules import, and the
# behaviour they name did not change, so renaming them here would be churn that
# proves nothing.
_LocalAssetReferenceParser = LocalAssetReferenceParser
_mask_js_strings_and_comments = mask_js_strings_and_comments
_has_obvious_top_level_throw = has_obvious_top_level_throw
_javascript_syntax_error = javascript_syntax_error
_orphaned_web_assets = orphaned_web_assets
_duplicate_script_includes = duplicate_script_includes
_artifact_preflight_failures = artifact_preflight_failures
_browser_smoke_files = browser_smoke_files
_owners_by_mention = owners_by_mention


def _is_test_file(path: str) -> bool:
    """True for a pytest-shaped path (``tests/`` dir or ``test_*`` / ``*_test.py``)."""
    p = str(path).replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py") or "/tests/" in p or p.startswith("tests/")


def _importable_module_for(cwd: str | Path, path: str) -> str:
    """Dotted module name for ``path`` IFF it lives in a real package under ``cwd``.

    Only nested package modules (a top dir containing ``__init__.py``) are
    importable safely from the worktree; top-level scripts and non-identifier
    paths return ``""`` and are byte-compiled only (not executed).
    """
    p = str(path).replace("\\", "/")
    if not p.endswith(".py"):
        return ""
    segs = p[:-3].split("/")
    if segs and segs[-1] == "__init__":
        segs = segs[:-1]
    if len(segs) < 2 or not all(s.isidentifier() for s in segs):
        return ""
    if not (Path(cwd) / segs[0] / "__init__.py").exists():
        return ""
    return ".".join(segs)


def verify_python_changes(
    cwd: str | Path,
    changed_files: list[str],
    emit: Callable[[dict[str, Any]], None],
    *,
    timeout: int = 120,
    run_check: Any = None,
) -> tuple[bool, int, str]:
    """Run a REAL verification subprocess over the changed python files.

    Emits the check as a forge ``tool`` call and its result as a forge
    ``tool_result`` carrying the REAL exit code. Returns ``(ok, returncode, summary)``.

    * changed test files -> run them with ``pytest`` (executes the tests).
    * else -> byte-compile every changed ``.py`` and import the changed package
      modules (executes them) in ONE subprocess with ONE real exit code.

    ``run_check(cmd, cwd, timeout) -> (rc, out)`` is injectable for tests.
    Defensive: a check that cannot even be launched surfaces honestly as a failed
    tool result, never crashes the stream.
    """
    import subprocess
    import sys

    files = [str(f) for f in (changed_files or []) if (Path(cwd) / str(f)).is_file()]
    if not files:
        return False, 1, "changed paths could not be verified as files"

    tests = [f for f in files if _is_test_file(f)]
    if tests:
        cmd = [sys.executable, "-m", "pytest", *tests, "-q"]
        label = "pytest " + " ".join(tests)
    else:
        modules = [m for m in (_importable_module_for(cwd, f) for f in files) if m]
        preflight_failures = _artifact_preflight_failures(cwd, files)
        cmd = [
            sys.executable,
            "-c",
            _VERIFY_SRC,
            json.dumps(files),
            json.dumps(modules),
            json.dumps(preflight_failures),
        ]
        label = "static checks: syntax + parse + open (" + ", ".join(files) + ")"

    emit({FORGE_EVENT_KEY: "tool", "name": "run", "text": label[:200]})
    try:
        if run_check is not None:
            rc, out = run_check(cmd, str(cwd), timeout)
        else:
            proc = subprocess.run(  # noqa: S603 - cmd is python + repo-relative files we computed
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError) as exc:
        emit({FORGE_EVENT_KEY: "tool_result", "text": f"verification could not run: {exc}", "is_error": True})
        return False, 1, f"verification could not run: {exc}"

    ok = rc == 0
    body = str(out or "").strip()
    detail = f"exit {rc}" + (("\n" + body) if body else "")
    emit({FORGE_EVENT_KEY: "tool_result", "text": detail[:500], "is_error": not ok})
    smoke_files = _browser_smoke_files(cwd, files) if ok else []
    if smoke_files:
        emit(
            {
                FORGE_EVENT_KEY: "tool",
                "name": "run",
                "text": "offline real-browser smoke for changed HTML or linked web assets",
            }
        )
        smoke = smoke_html_artifacts(cwd, smoke_files, timeout=min(timeout, 30))
        smoke_detail = (
            "BROWSER_SMOKE_OK: " if smoke.ok and smoke.attempted else "BROWSER_SMOKE_SKIPPED: "
        ) + smoke.summary
        if smoke.attempted and not smoke.ok:
            smoke_detail = "BROWSER_SMOKE_FAILED: " + smoke.summary
        emit(
            {
                FORGE_EVENT_KEY: "tool_result",
                "text": smoke_detail[:1500],
                "is_error": bool(smoke.attempted and not smoke.ok),
            }
        )
        if smoke.attempted and not smoke.ok:
            return False, 1, smoke_detail
        detail += "\n" + smoke_detail
    return ok, rc, detail[-1500:]


def _snapshot_repair_files(cwd: str | Path, changed_files: list[str]) -> dict[Path, bytes]:
    """Capture existing web sources before a repair that may touch clean owners too."""

    root = Path(cwd).resolve()
    snapshot: dict[Path, bytes] = {}
    candidates = {(root / name).resolve() for name in changed_files}
    candidates.update(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _REPAIR_TRUNCATION_SUFFIXES
    )
    for path in sorted(candidates):
        if path.suffix.lower() not in _REPAIR_TRUNCATION_SUFFIXES or not path.is_relative_to(root):
            continue
        try:
            snapshot[path] = path.read_bytes()
        except OSError:
            continue
    return snapshot


def _restore_catastrophic_repair_truncations(snapshot: dict[Path, bytes]) -> tuple[list[str], list[str]]:
    """Restore web sources a fix pass unexpectedly reduced to a tiny stub."""

    restored: list[str] = []
    failed: list[str] = []
    for path, before in snapshot.items():
        if len(before) < _REPAIR_TRUNCATION_MIN_BYTES:
            continue
        try:
            after_size = path.stat().st_size
        except OSError:
            after_size = 0
        if after_size >= len(before) * _REPAIR_TRUNCATION_RATIO:
            continue
        try:
            path.write_bytes(before)
        except OSError:
            failed.append(path.name)
            continue
        restored.append(path.name)
    return restored, failed


def _verify_and_iterate(
    cwd: str | Path,
    snap_before: dict[str, str],
    emit: Callable[[dict[str, Any]], None],
    run_pass: Callable[[str], tuple[int, str]],
    goal: str,
    *,
    verifier: Any = None,
    max_fix_iters: int = 2,
) -> int:
    """Verify THIS run's changes; on failure, feed the failure back for bounded fixes.

    ``run_pass(prompt) -> (rc, out)`` runs one more edit pass through the SAME CLI.
    Returns the final returncode: ``0`` when verification ultimately passes (or
    there was nothing to verify), else the non-zero exit of the failing check or
    the failing fix pass. Never raises — a fix pass that errors surfaces honestly.
    """
    from thomas.forge.anvil import forge_code_git

    verify = verifier or verify_python_changes
    changed = forge_code_git.delta_since(cwd, snap_before)
    if not changed:
        return 0  # nothing this run touched -> caller surfaces the no-op honestly

    ok, rc, summary = verify(cwd, changed, emit)
    iters = 0
    limit = max(0, int(max_fix_iters))
    while not ok and iters < limit:
        # A fix pass re-invokes the agent, so the kill switch gates it too: if an
        # operator drops the STOP file mid-build, stop iterating and surface the
        # last real failure rather than spawning another build.
        if emergency_stop_active():
            emit({FORGE_EVENT_KEY: "error", "text": "emergency stop active — halting fix loop"})
            return rc or 1
        iters += 1
        emit({FORGE_EVENT_KEY: "meta", "text": f"verification failed (exit {rc}); fix pass {iters}/{limit}"})
        repair_snapshot = _snapshot_repair_files(cwd, changed)
        fix_error: Exception | None = None
        frc = 0
        try:
            frc, _out = run_pass(compose_fix_prompt(goal, summary))
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            fix_error = exc
        restored, restore_failed = _restore_catastrophic_repair_truncations(repair_snapshot)
        if restored or restore_failed:
            detail = ", ".join(restored)
            if restore_failed:
                detail += ("; " if detail else "") + "restore failed for " + ", ".join(restore_failed)
            emit(
                {
                    FORGE_EVENT_KEY: "error",
                    "text": "verification repair was stopped after destructive truncation: " + detail,
                }
            )
            return rc or 1
        if fix_error is not None:
            emit({FORGE_EVENT_KEY: "error", "text": f"fix pass could not run: {fix_error}"})
            return rc or 1
        if frc != 0:
            return frc
        changed = forge_code_git.delta_since(cwd, snap_before)
        if not changed:
            return 0
        ok, rc, summary = verify(cwd, changed, emit)
    return 0 if ok else (rc or 1)
