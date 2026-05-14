"""Side-by-side Snake benchmark runner for Thomas vs OpenClaw."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from thomas.benchmarks.benchmark_lane import audit_benchmark_event
from thomas.demo.agentic_benchmark_runners import _run_thomas_api_task
from thomas.demo.harness import build_execution_plan, compute_summary

ROOT = Path(__file__).resolve().parents[2]
OPENCLAW_ROOT = Path(r"C:\Users\corbe\openclaw-h2h")
OPENCLAW_HOME = Path(r"C:\Users\corbe")
THOMAS_PAGE_PORT = 8891
OPENCLAW_PAGE_PORT = 8892
OPENCLAW_PROFILE = "h2h2"
RUNS_DIR = ROOT / "output" / "benchmarks" / "snake"
THOMAS_PAGE_URL = f"http://127.0.0.1:{THOMAS_PAGE_PORT}"
OPENCLAW_PAGE_URL = f"http://127.0.0.1:{OPENCLAW_PAGE_PORT}"
DEFAULT_THOMAS_API_BASE = "http://127.0.0.1:8899"
DEFAULT_THOMAS_PORT = 8910
TIMEOUT_SECONDS = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _python_exe() -> str:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _windows_detached_flags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def _thomas_api_base(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("snake-%Y%m%d-%H%M%S")


def _resolve_benchmark_session_id(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    return text or _run_id()


def _next_attempt_number(session_dir: Path) -> int:
    highest = 0
    if session_dir.exists():
        for child in session_dir.iterdir():
            if not child.is_dir():
                continue
            name = str(child.name or "")
            if not name.startswith("attempt-"):
                continue
            try:
                highest = max(highest, int(name.split("-", 1)[1]))
            except (IndexError, ValueError):
                continue
    return highest + 1


def _attempt_dir(session_dir: Path, attempt_number: int) -> Path:
    return session_dir / f"attempt-{int(attempt_number):02d}"


def _list_stale_attempt_roots(session_dir: Path, active_attempt_number: int) -> list[str]:
    stale: list[str] = []
    if not session_dir.exists():
        return stale
    for child in sorted(session_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name == f"attempt-{int(active_attempt_number):02d}":
            continue
        stale.append(str(child.resolve()))
    return stale


def _build_prompt(*, output_root: Path, local_url: str, competitor: str, benchmark_mode: bool) -> str:
    benchmark_note = (
        "Benchmark mode is enabled for this run. The repo may be dirty, but you are authorized "
        "to write only inside the output root below.\n"
        if benchmark_mode
        else ""
    )
    return (
        f"{benchmark_note}"
        f"Build a complete static Snake game inside {output_root}.\n"
        "Rules:\n"
        "- Work only inside that output root.\n"
        "- Do not modify product code, configs, or any path outside the output root.\n"
        "- Use only plain HTML, CSS, and JavaScript. No frameworks. No build step.\n"
        "- Required files: index.html, game.js, style.css, progress.md, proof.json.\n"
        "- progress.md must start with: Original prompt: Build a complete static Snake game\n"
        "- proof.json must contain these keys: status, local_url, finish_timestamp, claimed_features, known_limitations.\n"
        "- proof.json local_url must be exactly: "
        f"{local_url}\n"
        "- UI contract: canvas#game, #score, #status, button#start-btn, and button#restart-btn if you use a separate restart control.\n"
        "- Game contract: single centered canvas, start screen, arrow keys and WASD, live score, food spawning, wall collision, self collision, restart flow, and no console errors.\n"
        "- Deterministic hooks are mandatory.\n"
        '- window.render_game_to_text() must return a concise JSON string with mode, score, direction, snake, food, width, height, and a coordinate_note.\n'
        "- window.advanceTime(ms) must advance the game deterministically without relying on requestAnimationFrame.\n"
        "- Leave a short build/test log in progress.md.\n"
        f"- This is the {competitor} side of a head-to-head benchmark.\n"
        "Reply only when finished with the absolute path to proof.json and a one-line verdict.\n"
    )


def _task_pack(prompt_thomas: str, prompt_openclaw: str) -> dict[str, Any]:
    return {
        "id": "snake-h2h",
        "name": "Snake Head-to-Head",
        "version": 1,
        "description": "Static Snake game benchmark for Thomas and OpenClaw.",
        "protocol": [
            "Same prompt contract for both competitors.",
            "Static output only; no product-code edits allowed.",
            "Result quality is judged after artifact and browser validation.",
        ],
        "weights": {"success_rate": 0.4, "speed": 0.2, "follow_up": 0.1, "quality": 0.3},
        "quality_scale": {"min": 1, "max": 5},
        "tasks": [
            {
                "id": "snake_static_game",
                "title": "Build a static Snake game",
                "prompt": "See competitor-specific prompt artifacts in this run directory.",
                "success_criteria": "Writes all required files and serves a playable Snake page.",
                "time_budget_seconds": TIMEOUT_SECONDS,
            }
        ],
        "prompt_artifacts": {
            "thomas": prompt_thomas,
            "openclaw": prompt_openclaw,
        },
    }


def _parse_openclaw_json(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    text = str(raw_text or "").strip()
    if not text:
        return None, ""
    if text.startswith("{"):
        try:
            return json.loads(text), text
        except json.JSONDecodeError:
            return None, text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blob = text[start : end + 1]
        try:
            return json.loads(blob), blob
        except json.JSONDecodeError:
            return None, text
    return None, text


async def _wait_for_http_ok(url: str, *, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=10.0, write=10.0, pool=10.0)) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url)
                if response.status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for {url}")


def _start_thomas_benchmark_runtime(
    *,
    run_dir: Path,
    benchmark_root: Path,
    run_id: str,
    port: int,
) -> dict[str, Any]:
    logs_dir = run_dir / "thomas_runtime"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "stdout.log"
    stderr_path = logs_dir / "stderr.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "THOMAS_BENCHMARK_MODE": "1",
            "THOMAS_BENCHMARK_RUN_ID": run_id,
            "THOMAS_BENCHMARK_REASON": "snake head-to-head benchmark",
            "THOMAS_BENCHMARK_ROOT": str(benchmark_root.resolve()),
        }
    )
    process = subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "run-ui.ps1"),
            "-NoBrowser",
            "-NoTray",
            "-Port",
            str(int(port)),
        ],
        cwd=str(ROOT),
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env,
        creationflags=_windows_detached_flags(),
    )
    return {
        "process": process,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "api_base": _thomas_api_base(int(port)),
        "port": int(port),
    }


def _ensure_server_process(directory: Path, port: int, log_prefix: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    stdout_path = directory / f"{log_prefix}.stdout.log"
    stderr_path = directory / f"{log_prefix}.stderr.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            _python_exe(),
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(directory),
        ],
        cwd=str(ROOT),
        stdout=stdout_handle,
        stderr=stderr_handle,
        creationflags=_windows_detached_flags(),
    )
    return {
        "process": process,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
    }


async def _run_openclaw_task(
    prompt: str,
    raw_path: Path,
    *,
    session_id: str,
    workdir: Path,
) -> tuple[str, float, str]:
    start = time.monotonic()
    escaped_session_id = str(session_id).replace("'", "''")
    escaped_profile = str(OPENCLAW_PROFILE).replace("'", "''")
    command = (
        "$prompt = @'\n"
        f"{prompt}\n"
        "'@; "
        f"$sessionId = '{escaped_session_id}'; "
        f"$profile = '{escaped_profile}'; "
        "openclaw --no-color --profile $profile agent --session-id $sessionId "
        f"--message $prompt --thinking xhigh --timeout {TIMEOUT_SECONDS} --json"
    )
    process = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    text = stdout.decode("utf-8", errors="replace")
    raw_path.write_text(text, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"OpenClaw exited with code {process.returncode}")
    parsed, blob = _parse_openclaw_json(text)
    reply = ""
    if parsed:
        payloads = list((parsed.get("result") or {}).get("payloads") or [])
        if payloads:
            reply = str((payloads[0] or {}).get("text") or "")
    return reply, round(max(0.0, time.monotonic() - start), 3), blob


def _artifact_quality(root: Path) -> tuple[bool, int, str]:
    required = ["index.html", "game.js", "style.css", "progress.md", "proof.json"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        return False, 1, f"missing files: {', '.join(missing)}"
    try:
        proof = json.loads((root / "proof.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, 2, f"invalid proof.json: {exc}"
    status = str(proof.get("status") or "").strip().lower()
    if status not in {"ok", "ready", "complete", "completed", "success"}:
        return False, 3, f"proof.json status={status or 'missing'}"
    return True, 5, "artifacts present"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _render_report(*, run_id: str, records: list[dict[str, Any]]) -> str:
    by_name = {str(row["competitor"]): row for row in records}
    thomas = by_name["thomas"]
    openclaw = by_name["openclaw"]
    lines = [
        f"# Snake Head-to-Head ({run_id})",
        "",
        f"- Benchmark session: `{thomas.get('benchmark_session_id') or openclaw.get('benchmark_session_id') or '--'}`",
        f"- Attempt: `{thomas.get('attempt_number') or openclaw.get('attempt_number') or '--'}`",
        f"- Thomas page: `{THOMAS_PAGE_URL}`",
        f"- OpenClaw page: `{OPENCLAW_PAGE_URL}`",
        "",
        "| Competitor | Success | Time (s) | Quality | Served Root | Scored Root | Notes |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
        f"| Thomas | {thomas['success']} | {thomas['elapsed_seconds']} | {thomas['quality_score']} | {thomas['served_root']} | {thomas['scored_root']} | {thomas['notes']} |",
        f"| OpenClaw | {openclaw['success']} | {openclaw['elapsed_seconds']} | {openclaw['quality_score']} | {openclaw['served_root']} | {openclaw['scored_root']} | {openclaw['notes']} |",
        "",
    ]
    return "\n".join(lines) + "\n"


async def run_benchmark(args: argparse.Namespace) -> Path:
    if bool(args.no_open_browser):
        raise RuntimeError("Visible benchmark execution is required; background-only benchmark runs are disabled.")

    benchmark_session_id = _resolve_benchmark_session_id(str(args.benchmark_session_id or args.run_id or ""))
    session_dir = RUNS_DIR / benchmark_session_id
    attempt_number = _next_attempt_number(session_dir)
    run_id = f"{benchmark_session_id}-attempt-{attempt_number:02d}"
    run_dir = _attempt_dir(session_dir, attempt_number)
    run_dir.mkdir(parents=True, exist_ok=True)
    thomas_root = run_dir / "thomas"
    openclaw_root = OPENCLAW_ROOT / "output" / "benchmarks" / "snake" / benchmark_session_id / f"attempt-{attempt_number:02d}" / "openclaw"
    thomas_root.mkdir(parents=True, exist_ok=True)
    openclaw_root.mkdir(parents=True, exist_ok=True)
    stale_attempt_roots = _list_stale_attempt_roots(session_dir, attempt_number)
    managed_thomas_runtime = None
    thomas_api_base = str(args.thomas_api_base or DEFAULT_THOMAS_API_BASE)
    if bool(args.start_thomas):
        managed_thomas_runtime = _start_thomas_benchmark_runtime(
            run_dir=run_dir,
            benchmark_root=thomas_root,
            run_id=run_id,
            port=int(args.thomas_port),
        )
        thomas_api_base = str(managed_thomas_runtime["api_base"])
        await _wait_for_http_ok(f"{thomas_api_base}/api/health", timeout_seconds=120)

    page_servers = {
        "thomas": _ensure_server_process(thomas_root, THOMAS_PAGE_PORT, "page_server"),
        "openclaw": _ensure_server_process(openclaw_root, OPENCLAW_PAGE_PORT, "page_server"),
    }
    await _wait_for_http_ok(THOMAS_PAGE_URL)
    await _wait_for_http_ok(OPENCLAW_PAGE_URL)

    prompt_thomas = _build_prompt(
        output_root=thomas_root,
        local_url=THOMAS_PAGE_URL,
        competitor="Thomas",
        benchmark_mode=True,
    )
    prompt_openclaw = _build_prompt(
        output_root=openclaw_root,
        local_url=OPENCLAW_PAGE_URL,
        competitor="OpenClaw",
        benchmark_mode=False,
    )
    (run_dir / "prompt.thomas.txt").write_text(prompt_thomas, encoding="utf-8")
    (run_dir / "prompt.openclaw.txt").write_text(prompt_openclaw, encoding="utf-8")

    benchmark_context = {
        "run_id": run_id,
        "lane": "benchmark",
        "reason": "snake head-to-head benchmark",
        "root": str(thomas_root.resolve()),
        "audit_path": str((thomas_root / "benchmark_audit.jsonl").resolve()),
    }
    audit_benchmark_event(
        benchmark_context,
        event="benchmark_run_start",
        decision="STARTED",
        payload={
            "benchmark_session_id": benchmark_session_id,
            "attempt_number": attempt_number,
            "thomas_root": str(thomas_root),
            "openclaw_root": str(openclaw_root),
            "thomas_page_url": THOMAS_PAGE_URL,
            "openclaw_page_url": OPENCLAW_PAGE_URL,
            "thomas_api_base": thomas_api_base,
            "stale_attempt_roots": stale_attempt_roots,
            "is_visible_active_attempt": True,
        },
    )

    webbrowser.open_new(THOMAS_PAGE_URL)
    webbrowser.open_new(OPENCLAW_PAGE_URL)

    thomas_raw = run_dir / "thomas.raw.json"
    openclaw_raw = run_dir / "openclaw.raw.json"
    thomas_started_at = _now_iso()
    openclaw_started_at = _now_iso()

    async def _run_thomas() -> tuple[str, float, dict[str, Any]]:
        result = await _run_thomas_api_task(
            api_base=thomas_api_base,
            api_token="",
            profile="codex",
            prompt=prompt_thomas,
            mode="thinking",
            token_economy="max",
            max_iterations=20,
            watch=bool(args.watch),
            watch_prefix="[thomas/snake]",
        )
        _write_json(thomas_raw, result)
        reply = str(result.get("text") or "")
        return reply, float(result.get("elapsed_seconds") or 0.0), result

    async def _run_openclaw() -> tuple[str, float, str]:
        reply, elapsed, raw_blob = await _run_openclaw_task(
            prompt_openclaw,
            openclaw_raw,
            session_id=f"snake-{run_id}",
            workdir=openclaw_root,
        )
        return reply, elapsed, raw_blob

    thomas_task = asyncio.create_task(_run_thomas())
    openclaw_task = asyncio.create_task(_run_openclaw())
    thomas_reply, thomas_elapsed, thomas_result = await thomas_task
    openclaw_reply, openclaw_elapsed, openclaw_blob = await openclaw_task

    thomas_ok, thomas_quality, thomas_notes = _artifact_quality(thomas_root)
    openclaw_ok, openclaw_quality, openclaw_notes = _artifact_quality(openclaw_root)

    task_pack = _task_pack(prompt_thomas, prompt_openclaw)
    records = [
        {
            "task_id": "snake_static_game",
            "competitor": "thomas",
            "benchmark_session_id": benchmark_session_id,
            "attempt_number": attempt_number,
            "success": thomas_ok,
            "elapsed_seconds": thomas_elapsed,
            "follow_up_prompts": 0,
            "quality_score": thomas_quality,
            "evidence": str(thomas_root / "proof.json"),
            "served_root": str(thomas_root.resolve()),
            "scored_root": str(thomas_root.resolve()),
            "is_visible_active_attempt": True,
            "notes": thomas_notes,
            "captured_at": _now_iso(),
        },
        {
            "task_id": "snake_static_game",
            "competitor": "openclaw",
            "benchmark_session_id": benchmark_session_id,
            "attempt_number": attempt_number,
            "success": openclaw_ok,
            "elapsed_seconds": openclaw_elapsed,
            "follow_up_prompts": 0,
            "quality_score": openclaw_quality,
            "evidence": str(openclaw_root / "proof.json"),
            "served_root": str(openclaw_root.resolve()),
            "scored_root": str(openclaw_root.resolve()),
            "is_visible_active_attempt": True,
            "notes": openclaw_notes,
            "captured_at": _now_iso(),
        },
    ]
    execution_plan = build_execution_plan(
        task_pack=task_pack,
        competitors=["thomas", "openclaw"],
        randomize=False,
        seed=None,
    )
    summary = compute_summary(task_pack, records)
    _write_json(run_dir / "task_pack.snapshot.json", task_pack)
    _write_json(run_dir / "results.raw.json", records)
    _write_json(run_dir / "execution_plan.json", execution_plan)
    _write_json(
        session_dir / "benchmark_session.json",
        {
            "benchmark_session_id": benchmark_session_id,
            "active_attempt_number": attempt_number,
            "active_run_id": run_id,
            "active_run_dir": str(run_dir.resolve()),
            "visible_execution_required": True,
            "stale_attempt_roots": stale_attempt_roots,
            "updated_at": _now_iso(),
        },
    )
    _write_json(
        run_dir / "scorecard.json",
        {
            "benchmark_session_id": benchmark_session_id,
            "attempt_number": attempt_number,
            "run_id": run_id,
            "created_at": _now_iso(),
            "task_pack_id": task_pack["id"],
            "task_pack_version": task_pack["version"],
            "competitors": ["thomas", "openclaw"],
            "served_root": {
                "thomas": str(thomas_root.resolve()),
                "openclaw": str(openclaw_root.resolve()),
            },
            "scored_root": {
                "thomas": str(thomas_root.resolve()),
                "openclaw": str(openclaw_root.resolve()),
            },
            "is_visible_active_attempt": True,
            "stale_attempt_roots": stale_attempt_roots,
            "summary": summary,
        },
    )
    (run_dir / "report.md").write_text(_render_report(run_id=run_id, records=records), encoding="utf-8")

    benchmark_payload = {
        "benchmark_session_id": benchmark_session_id,
        "attempt_number": attempt_number,
        "run_id": run_id,
        "generated_at": _now_iso(),
        "visible_execution_required": True,
        "stale_attempt_roots": stale_attempt_roots,
        "thomas": {
            "root": str(thomas_root),
            "page_url": THOMAS_PAGE_URL,
            "started_at": thomas_started_at,
            "elapsed_seconds": thomas_elapsed,
            "success": thomas_ok,
            "quality_score": thomas_quality,
            "served_root": str(thomas_root.resolve()),
            "scored_root": str(thomas_root.resolve()),
            "is_visible_active_attempt": True,
            "reply": thomas_reply,
            "notes": thomas_notes,
            "raw_path": str(thomas_raw),
            "proof_path": str(thomas_root / "proof.json"),
        },
        "openclaw": {
            "root": str(openclaw_root),
            "page_url": OPENCLAW_PAGE_URL,
            "started_at": openclaw_started_at,
            "elapsed_seconds": openclaw_elapsed,
            "success": openclaw_ok,
            "quality_score": openclaw_quality,
            "served_root": str(openclaw_root.resolve()),
            "scored_root": str(openclaw_root.resolve()),
            "is_visible_active_attempt": True,
            "reply": openclaw_reply,
            "notes": openclaw_notes,
            "raw_path": str(openclaw_raw),
            "proof_path": str(openclaw_root / "proof.json"),
        },
        "servers": {
            "thomas_execution": {
                "mode": "api",
                "api_base": thomas_api_base,
                "profile": "codex",
                "token_economy": "max",
            },
            "thomas_page": {
                "url": THOMAS_PAGE_URL,
                "stdout_path": str(page_servers["thomas"]["stdout_path"]),
                "stderr_path": str(page_servers["thomas"]["stderr_path"]),
            },
            "openclaw_page": {
                "url": OPENCLAW_PAGE_URL,
                "stdout_path": str(page_servers["openclaw"]["stdout_path"]),
                "stderr_path": str(page_servers["openclaw"]["stderr_path"]),
            },
        },
        "managed_thomas_runtime": None
        if managed_thomas_runtime is None
        else {
            "api_base": thomas_api_base,
            "port": managed_thomas_runtime["port"],
            "stdout_path": str(managed_thomas_runtime["stdout_path"]),
            "stderr_path": str(managed_thomas_runtime["stderr_path"]),
            "pid": int(managed_thomas_runtime["process"].pid),
        },
        "summary": summary,
        "openclaw_json_blob": openclaw_blob,
        "thomas_result": thomas_result,
    }
    _write_json(run_dir / "snake_benchmark.json", benchmark_payload)
    audit_benchmark_event(
        benchmark_context,
        event="benchmark_run_complete",
        decision="SUCCESS" if thomas_ok else "FAILED",
        payload={
            "benchmark_session_id": benchmark_session_id,
            "attempt_number": attempt_number,
            "thomas_elapsed_seconds": thomas_elapsed,
            "openclaw_elapsed_seconds": openclaw_elapsed,
            "thomas_success": thomas_ok,
            "openclaw_success": openclaw_ok,
            "report_path": str(run_dir / "report.md"),
        },
    )
    return run_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Thomas vs OpenClaw Snake benchmark.")
    parser.add_argument("--run-id", default="", help="Optional run id override.")
    parser.add_argument(
        "--benchmark-session-id",
        default="",
        help="Stable benchmark session id. Reusing it creates explicit numbered attempts.",
    )
    parser.add_argument(
        "--thomas-api-base",
        default=DEFAULT_THOMAS_API_BASE,
        help=f"Thomas API base URL (default: {DEFAULT_THOMAS_API_BASE}).",
    )
    parser.add_argument(
        "--start-thomas",
        action="store_true",
        help="Start a dedicated Thomas benchmark runtime with benchmark env vars.",
    )
    parser.add_argument(
        "--thomas-port",
        type=int,
        default=DEFAULT_THOMAS_PORT,
        help=f"Port for a dedicated Thomas benchmark runtime (default: {DEFAULT_THOMAS_PORT}).",
    )
    parser.add_argument("--watch", action="store_true", help="Stream Thomas benchmark progress to stdout.")
    parser.add_argument("--no-open-browser", action="store_true", help="Do not open the benchmark pages in a browser.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = asyncio.run(run_benchmark(args))
    print(f"Snake benchmark completed: {run_dir}")
    print(f"  - {run_dir / 'snake_benchmark.json'}")
    print(f"  - {run_dir / 'report.md'}")
    print(f"  - {run_dir / 'scorecard.json'}")
    print(f"  - Thomas page: {THOMAS_PAGE_URL}")
    print(f"  - OpenClaw page: {OPENCLAW_PAGE_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
