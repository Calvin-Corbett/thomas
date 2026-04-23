"""Baseline and raw-prompt Codex runners for swarm comparisons."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from thomas.demo.project_swarm_contracts import (
    DEFAULT_PROJECT_PROMPT,
    copy_tree,
    count_lines,
    evaluate_baseline_product,
)
from thomas.demo.project_swarm_runtime import run_command_with_timeout


def _resolve_codex_command() -> str | None:
    codex_exe = shutil.which("codex.exe")
    if codex_exe and "WindowsApps" not in codex_exe:
        return codex_exe
    return shutil.which("codex.cmd") or codex_exe or shutil.which("codex")


def _codex_exec_base_command(codex_cmd: str) -> list[str]:
    return [
        codex_cmd,
        "-c",
        "mcp_servers.playwright.enabled=false",
        "exec",
        "--full-auto",
    ]


def run_codex_baseline(args: Any) -> dict[str, Any]:
    run_root = args.repo_root / "output" / "benchmarks" / args.run_id
    reuse_raw = str(getattr(args, "baseline_reuse_dir", "") or "").strip()
    if reuse_raw:
        temp_root = Path(reuse_raw).expanduser().resolve()
        elapsed = float(getattr(args, "baseline_elapsed_seconds", 0.0) or 0.0)
        returncode = 124
        stdout = "reused timed-out baseline workspace"
        stderr = ""
        timed_out = True
    else:
        temp_root = Path(tempfile.gettempdir()) / f"codex_project_baseline_{args.run_id}_{int(time.time())}"
        temp_root.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=temp_root, capture_output=True, text=True, check=False)
        codex_cmd = _resolve_codex_command()
        if not codex_cmd:
            raise FileNotFoundError("codex CLI was not found on PATH")
        returncode, stdout, stderr, timed_out, elapsed = run_command_with_timeout(
            [*_codex_exec_base_command(codex_cmd), "-C", str(temp_root), _baseline_prompt(args)],
            cwd=temp_root,
            timeout_s=int(args.baseline_timeout),
        )
    dst = run_root / "codex_baseline"
    copy_tree(temp_root, dst)
    evaluation = evaluate_baseline_product(dst)
    metrics = {
        "kind": "codex_baseline",
        "root": str(dst),
        "seconds": elapsed,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "evaluator": evaluation,
        "lines": count_lines(dst),
    }
    metrics["passed"] = int(returncode == 0 and evaluation["failed"] == 0)
    metrics["lines_per_minute"] = round(metrics["lines"]["nonblank"] / max(elapsed / 60.0, 0.001), 2)
    (dst / "codex_baseline_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def run_codex_prompt_only(args: Any) -> dict[str, Any]:
    run_root = args.repo_root / "output" / "prompt_comparisons" / args.run_id
    prompt = str(getattr(args, "project_prompt", "") or "").strip() or DEFAULT_PROJECT_PROMPT
    dst = run_root / "codex_raw"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "PROMPT.txt").write_text(prompt + "\n", encoding="utf-8")
    returncode = 0
    stdout = ""
    stderr = ""
    timed_out = False
    try:
        response_text, elapsed = _run_codex_prompt_only_chat(args, prompt)
        payload = _validate_raw_prompt_only_payload(response_text)
        (dst / "codex_raw_response.txt").write_text(response_text, encoding="utf-8")
        for row in payload["files"]:
            target = dst.joinpath(*str(row["path"]).split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(row["content"]), encoding="utf-8")
        workspace = dict(payload.get("workspace") or {})
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        elapsed = 0.0
        returncode = 1
        stderr = str(exc)
        workspace = {"file_count": 1, "sample_files": ["PROMPT.txt"]}
    metrics = {
        "kind": "codex_raw_prompt",
        "root": str(dst),
        "prompt": prompt,
        "seconds": elapsed,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "transport": "chat",
        "lines": count_lines(dst),
        "workspace": workspace,
    }
    (dst / "codex_raw_prompt_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def _run_codex_prompt_only_chat(args: Any, prompt: str) -> tuple[str, float]:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "prompt_only_worker_chat.py"
    temp_root = Path(tempfile.gettempdir()) / f"codex_raw_prompt_{args.run_id}_{int(time.time() * 1000)}"
    temp_root.mkdir(parents=True, exist_ok=True)
    prompt_path = temp_root / "prompt.txt"
    output_path = temp_root / "assistant.txt"
    prompt_path.write_text(_raw_prompt_only_request(prompt), encoding="utf-8")
    raw_timeout = int(getattr(args, "raw_timeout", 0) or 0)
    request_timeout_s = max(900, raw_timeout) if raw_timeout > 0 else 1800
    cmd = [
        sys.executable,
        str(script_path),
        "--mode",
        "structured",
        "--system-prompt",
        "Return one JSON object only. No markdown. No prose outside JSON.",
        "--prompt-file",
        str(prompt_path),
        "--output-file",
        str(output_path),
        "--request-timeout-s",
        str(request_timeout_s),
        "--max-tokens",
        "16000",
    ]
    config_path = str(getattr(args, "config", "") or "").strip()
    profile = str(getattr(args, "profile", "") or "").strip()
    if config_path:
        cmd.extend(["--config", config_path])
    if profile:
        cmd.extend(["--profile", profile])
    returncode, stdout, stderr, timed_out, elapsed = run_command_with_timeout(
        cmd,
        cwd=repo_root,
        timeout_s=raw_timeout,
    )
    if output_path.exists():
        text = output_path.read_text(encoding="utf-8")
        if text.strip():
            return text, elapsed
    detail = (str(stderr or "").strip() or str(stdout or "").strip())[-4000:]
    if timed_out:
        raise ValueError(f"raw Codex chat timed out: {detail or 'no output'}")
    raise ValueError(f"raw Codex chat failed: {detail or f'exit {returncode}'}")


def _raw_prompt_only_request(project_prompt: str) -> str:
    return (
        "Build the requested browser project and return one JSON object only with this exact shape:\n"
        "{\n"
        '  "summary": "short summary",\n'
        '  "files": [\n'
        '    {"path": "index.html", "content": "..."},\n'
        '    {"path": "styles.css", "content": "..."},\n'
        '    {"path": "app.js", "content": "..."}\n'
        "  ]\n"
        "}\n\n"
        f"Task:\n{project_prompt}\n\n"
        "Rules:\n"
        "- Create exactly these three files: index.html, styles.css, and app.js.\n"
        "- Use plain HTML, CSS, and JavaScript only. No external dependencies.\n"
        "- index.html must load styles.css and app.js as external files.\n"
        "- app.js must contain real behavior, not placeholders.\n"
        "- Fully include the file contents in the JSON response.\n"
        "- Do not return markdown.\n"
    )


def _validate_raw_prompt_only_payload(response_text: str) -> dict[str, Any]:
    from thomas.demo.project_swarm_runner import (
        _extract_json_payload,
        _project_files_sample,
        _safe_workspace_relpath,
        _validate_prompt_only_file_content,
    )

    payload = _extract_json_payload(response_text)
    if not isinstance(payload, dict):
        raise ValueError("raw Codex did not return an object")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("raw Codex returned no files")
    expected = ("index.html", "styles.css", "app.js")
    files_by_path: dict[str, str] = {}
    for raw in raw_files:
        if not isinstance(raw, dict):
            continue
        rel_path = _safe_workspace_relpath(str(raw.get("path") or ""))
        if rel_path not in expected or rel_path in files_by_path:
            continue
        files_by_path[rel_path] = _validate_prompt_only_file_content(rel_path, str(raw.get("content") or ""))
    missing = [path for path in expected if path not in files_by_path]
    if missing:
        raise ValueError(f"raw Codex did not return required files: {', '.join(missing)}")
    files = [{"path": path, "content": files_by_path[path]} for path in expected]
    return {
        "summary": str(payload.get("summary") or "").strip() or "Direct raw Codex browser project output.",
        "files": files,
        "workspace": _project_files_sample(files),
    }


def _workspace_file_sample(root: Path, *, limit: int = 120) -> dict[str, Any]:
    files: list[str] = []
    total = 0
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            total += 1
            if len(files) < limit:
                files.append(str(path.relative_to(root)))
    return {"file_count": total, "sample_files": files}


def _baseline_prompt(args: Any) -> str:
    project_prompt = str(getattr(args, "project_prompt", "") or "").strip() or DEFAULT_PROJECT_PROMPT
    return (
        f"{project_prompt}\n\n"
        "Build it as a browser project in this folder. Create index.html, src/game.mjs, and src/styles.css. "
        "No external dependencies. Include an interactive surface, useful state/output, and a way to verify the core flow."
    )
