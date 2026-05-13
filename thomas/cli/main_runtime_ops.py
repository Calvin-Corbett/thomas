"""Shared runtime operations for CLI commands in thomas.cli.main."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import click

from thomas.cli.product_shell import build_status_experience
from thomas.core import agent_presence
from thomas.core.config import AppConfig
from thomas.core.redaction import Redactor

_RUNTIME_OPS_REDACTOR = Redactor()


def resolved_config_path(config: AppConfig) -> Path:
    cfg_path = getattr(config, "config_path", None)
    if isinstance(cfg_path, Path):
        return cfg_path.resolve()
    if isinstance(cfg_path, str) and str(cfg_path).strip():
        return Path(str(cfg_path)).resolve()
    return Path("thomas.toml").resolve()


def _emit_json(payload: Any, **kwargs: Any) -> None:
    click.echo(json.dumps(_RUNTIME_OPS_REDACTOR.redact_obj(payload), **kwargs))


def repo_root_from_cli_file() -> Path:
    return Path(__file__).resolve().parents[2]


def run_repo_cleanup(*, apply: bool, include_ignored: bool) -> dict[str, Any]:
    script_path = repo_root_from_cli_file() / "scripts" / "cleanup_local_junk.py"
    if not script_path.exists():
        raise FileNotFoundError(f"cleanup script not found: {script_path}")
    cmd = [sys.executable, str(script_path), "--json"]
    if apply:
        cmd.append("--apply")
    cmd.append("--ignored" if include_ignored else "--no-ignored")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    raw = str(proc.stdout or "").strip()
    if not raw:
        detail = str(proc.stderr or "").strip() or "cleanup script returned empty output"
        raise RuntimeError(detail)
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"cleanup script returned non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("cleanup script returned invalid JSON payload")
    payload["_exit_code"] = int(proc.returncode)
    if proc.returncode != 0 and not str(proc.stderr or "").strip():
        payload.setdefault("_error", "cleanup script returned non-zero exit status")
    elif str(proc.stderr or "").strip():
        payload["_stderr"] = str(proc.stderr or "").strip()
    return payload


def git_status_porcelain_lines(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(str(proc.stderr or "").strip() or "git status --porcelain failed")
    out: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        line = str(raw or "").rstrip()
        if line:
            out.append(line)
    return out


def status_cmd(
    ctx: click.Context, as_json: bool, strict: bool, strict_worktree: bool, repo_presence: bool = False
) -> None:
    from scripts.forge.gates.repo_hygiene import evaluate_worktree_clean

    from thomas import __version__

    config: AppConfig = ctx.obj["config"]
    cfg_path = resolved_config_path(config)
    errors = config.validate()
    worktree_error = ""
    worktree: dict[str, Any]
    try:
        worktree_raw = evaluate_worktree_clean(git_status_porcelain_lines(repo_root_from_cli_file()))
        worktree = {
            "ok": bool(worktree_raw.get("ok", False)),
            "summary": dict(worktree_raw.get("summary") or {}),
            "violations": list(worktree_raw.get("violations") or []),
        }
    except Exception as exc:
        worktree_error = f"{type(exc).__name__}: {exc}"
        worktree = {
            "ok": None,
            "summary": {},
            "violations": [],
            "error": worktree_error,
        }
    payload = {
        "ok": len(errors) == 0,
        "version": __version__,
        "config_path": str(cfg_path),
        "config_exists": cfg_path.exists(),
        "default_model": str(config.default_model or ""),
        "profiles": sorted(str(k) for k in config.models.keys()),
        "profile_count": len(config.models),
        "server": {
            "access_mode": str(config.server.access_mode or ""),
            "allow_unauthenticated_version": bool(config.server.allow_unauthenticated_version),
        },
        "summary": {
            "error_count": len(errors),
        },
        "errors": [str(e) for e in errors],
        "worktree": worktree,
        "worktree_clean": worktree.get("ok"),
    }
    if repo_presence:
        try:
            payload["repo_presence"] = agent_presence.collect_presence(repo_root=repo_root_from_cli_file())
        except Exception as exc:
            payload["repo_presence"] = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    payload["readiness"] = build_status_experience(payload)

    if as_json:
        _emit_json(payload, ensure_ascii=False)
    else:
        readiness = dict(payload.get("readiness") or {})
        click.echo(f"Thomas {payload['version']}")
        click.echo(f"state: {readiness.get('state', 'unknown')}")
        click.echo(f"summary: {readiness.get('summary', '')}")
        click.echo(f"config: {payload['config_path']}")
        click.echo(f"default model: {payload['default_model']}")
        click.echo(f"profiles: {', '.join(payload['profiles']) or '(none)'}")
        click.echo(f"server mode: {payload['server']['access_mode']}")
        click.echo(f"config ok: {payload['ok']}")
        wt_summary = dict((payload.get("worktree") or {}).get("summary") or {})
        wt_ok = payload.get("worktree_clean")
        if wt_ok is None:
            click.echo("worktree: unavailable")
            if worktree_error:
                click.echo(f"worktree error: {worktree_error}")
        else:
            click.echo(f"worktree clean: {wt_ok}")
            click.echo(
                "worktree: "
                f"staged={int(wt_summary.get('staged_count', 0) or 0)} "
                f"unstaged={int(wt_summary.get('unstaged_count', 0) or 0)} "
                f"untracked={int(wt_summary.get('untracked_count', 0) or 0)}"
            )
            if not wt_ok:
                for msg in list((payload.get("worktree") or {}).get("violations") or [])[:3]:
                    click.echo(f"  - {msg}")
        if payload["errors"]:
            click.echo("errors:")
            for err in payload["errors"]:
                click.echo(f"  - {err}")
        if repo_presence:
            presence_payload = dict(payload.get("repo_presence") or {})
            if presence_payload:
                click.echo(
                    "repo presence: "
                    f"active={int(presence_payload.get('active_count', 0) or 0)} "
                    f"warnings={len(list(presence_payload.get('warnings') or []))} "
                    f"conflicts={len(list(presence_payload.get('conflicts') or []))}"
                )
        note = str(readiness.get("note") or "").strip()
        if note:
            click.echo(f"note: {note}")
        next_steps = [str(step).rstrip() for step in list(readiness.get("next_steps") or []) if str(step).strip()]
        if next_steps:
            click.echo("next steps:")
            for step in next_steps:
                click.echo(f"  - {step}")

    if strict and not bool(payload.get("ok", False)):
        raise SystemExit(2)
    if strict_worktree and payload.get("worktree_clean") is not True:
        raise SystemExit(3)


def repo_clean_cmd(apply: bool, include_ignored: bool, as_json: bool, strict: bool) -> None:
    from scripts.forge.gates.repo_hygiene import evaluate_worktree_clean

    repo_root = repo_root_from_cli_file()
    try:
        cleanup_payload = run_repo_cleanup(apply=bool(apply), include_ignored=bool(include_ignored))
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if as_json:
            _emit_json(payload, ensure_ascii=False)
        else:
            click.echo(payload["error"], err=True)
        raise SystemExit(1)

    cleanup_exit_code = int(cleanup_payload.pop("_exit_code", 0) or 0)
    cleanup_failed = list(cleanup_payload.get("failed") or [])
    cleanup_error = str(cleanup_payload.get("_error") or "").strip()
    cleanup_stderr = str(cleanup_payload.get("_stderr") or "").strip()

    try:
        worktree = evaluate_worktree_clean(git_status_porcelain_lines(repo_root))
    except Exception as exc:
        payload = {
            "ok": False,
            "cleanup": cleanup_payload,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if as_json:
            _emit_json(payload, ensure_ascii=False)
        else:
            click.echo(payload["error"], err=True)
        raise SystemExit(1)

    cleanup_summary = {
        "candidate_count": len(list(cleanup_payload.get("candidates") or [])),
        "removed_count": len(list(cleanup_payload.get("removed") or [])),
        "failed_count": len(cleanup_failed),
        "exit_code": cleanup_exit_code,
    }
    worktree_summary = dict(worktree.get("summary") or {})
    worktree_ok = bool(worktree.get("ok", False))
    cleanup_ok = cleanup_exit_code == 0 and not cleanup_failed
    ok = cleanup_ok and (worktree_ok or not strict)

    payload = {
        "ok": ok,
        "repo_root": str(repo_root),
        "apply": bool(apply),
        "include_ignored": bool(include_ignored),
        "cleanup": cleanup_payload,
        "cleanup_summary": cleanup_summary,
        "worktree": worktree,
    }
    if cleanup_error:
        payload["cleanup_error"] = cleanup_error
    if cleanup_stderr:
        payload["cleanup_stderr"] = cleanup_stderr

    if as_json:
        _emit_json(payload, ensure_ascii=False)
    else:
        click.echo(f"repo: {payload['repo_root']}")
        click.echo(
            "cleanup: "
            f"candidates={cleanup_summary['candidate_count']} "
            f"removed={cleanup_summary['removed_count']} "
            f"failed={cleanup_summary['failed_count']}"
        )
        click.echo(
            "worktree: "
            f"staged={int(worktree_summary.get('staged_count', 0) or 0)} "
            f"unstaged={int(worktree_summary.get('unstaged_count', 0) or 0)} "
            f"untracked={int(worktree_summary.get('untracked_count', 0) or 0)}"
        )
        if cleanup_failed:
            click.echo("cleanup failures:")
            for row in cleanup_failed[:5]:
                path = str((row or {}).get("path", ""))
                err = str((row or {}).get("error", ""))
                click.echo(f"  - {path}: {err}")
        if cleanup_error:
            click.echo(f"cleanup error: {cleanup_error}", err=True)
        if cleanup_stderr:
            click.echo(f"cleanup stderr: {cleanup_stderr}", err=True)
        if strict and not worktree_ok:
            click.echo("strict mode: worktree remains dirty", err=True)

    if not cleanup_ok:
        raise SystemExit(1)
    if strict and not worktree_ok:
        raise SystemExit(2)


def run_provider_checks(config: AppConfig) -> None:
    from thomas.models.discovery import handshake_models_async
    from thomas.server.secrets import SecretStore

    secret_store = SecretStore(config.memory.root_path / ".thomas")

    async def _check_all() -> None:
        _ = __import__("httpx")
        results = []
        for name, mcfg in config.models.items():
            if name == "local":
                continue

            stored_key = secret_store.get(name)
            effective_cfg = mcfg
            if stored_key:
                effective_cfg = replace(mcfg, api_key=stored_key)

            has_key = bool(effective_cfg.api_key)
            if not has_key:
                results.append((name, "skip", "No API key set"))
                continue

            click.echo(f"  {name}: testing...", nl=False)
            try:
                hs = await handshake_models_async(effective_cfg, timeout_s=5.0)
                if hs.ok:
                    count = len(hs.models or [])
                    msg = f"OK ({count} models)" if count else "OK (connected)"
                    click.echo(f"\r  {name}: \033[32m{msg}\033[0m")
                    results.append((name, "ok", msg))
                elif hs.status == "auth_error":
                    click.echo(f"\r  {name}: \033[31mAUTH FAILED\033[0m - check/refresh your API key")
                    results.append((name, "auth_error", hs.error or "auth failed"))
                elif hs.status == "unsupported":
                    click.echo(f"\r  {name}: \033[33mNo /models endpoint\033[0m (may still work for chat)")
                    results.append((name, "unsupported", "no /models"))
                elif hs.status == "offline":
                    click.echo(f"\r  {name}: \033[31mOFFLINE\033[0m - endpoint unreachable")
                    results.append((name, "offline", hs.error or "offline"))
                else:
                    click.echo(f"\r  {name}: \033[31mERROR\033[0m - {hs.error or hs.status}")
                    results.append((name, "error", hs.error or hs.status))
            except Exception as e:
                click.echo(f"\r  {name}: \033[31mERROR\033[0m - {type(e).__name__}: {e}")
                results.append((name, "error", str(e)))

        ok = sum(1 for _, s, _ in results if s == "ok")
        skip = sum(1 for _, s, _ in results if s == "skip")
        fail = len(results) - ok - skip
        click.echo(f"\n  Summary: {ok} connected, {fail} failed, {skip} no key set")
        click.echo("  Tip: run `thomas models validate` for handshake + tool-call smoke checks.")

    asyncio.run(_check_all())


def doctor_cmd(
    ctx: click.Context,
    port: int,
    full: bool,
) -> None:
    from thomas import __version__
    from thomas.agent.guidance import guidance_bootstrap_report

    config: AppConfig = ctx.obj["config"]

    click.echo(f"Thomas {__version__}")

    errors = config.validate()
    if errors:
        click.echo("\nConfig issues:")
        for e in errors:
            click.echo(f"  - {e}")
    else:
        click.echo("\nConfig: OK")

    try:
        report = guidance_bootstrap_report()
        selected = list(report.get("selected_sources") or [])
        click.echo("\nStartup guidance:")
        if selected:
            click.echo("  Active sources: " + ", ".join(selected))
        else:
            click.echo("  Active sources: none (using built-in behavior)")
        for row in list(report.get("sources") or []):
            path = str(row.get("path", ""))
            found = bool(row.get("exists", False))
            used = bool(row.get("selected", False))
            bullet_count = int(row.get("bullet_count", 0) or 0)
            click.echo(
                f"  - {path}: "
                f"{'FOUND' if found else 'missing'}, "
                f"{'used' if used else 'skipped'}, "
                f"bullets={bullet_count}"
            )
    except Exception as e:
        click.echo(f"\nStartup guidance: unavailable ({type(e).__name__}: {e})")

    try:
        import aiohttp  # noqa: F401

        click.echo("Server deps (aiohttp): OK")
    except Exception as e:
        click.echo(f"Server deps (aiohttp): MISSING ({e})")
        click.echo('  Fix: pip install -e ".[server]"')

    in_use = False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.35):
            in_use = True
    except OSError:
        in_use = False

    click.echo(f"\nUI URL: http://127.0.0.1:{int(port)}/")
    click.echo(f"Port {int(port)}: " + ("IN USE (server already running?)" if in_use else "free"))

    local = config.models.get("local")
    if local:
        base = (local.base_url or "").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        tags_url = base.rstrip("/") + "/api/tags"

        try:
            import httpx

            r = httpx.get(tags_url, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                model_count = len(data.get("models", []))
                click.echo(f"Local endpoint (Ollama): OK ({model_count} models)")
            else:
                click.echo(f"Local endpoint (Ollama): {r.status_code} (check Ollama)")
        except Exception as e:
            click.echo(f"Local endpoint (Ollama): not reachable ({type(e).__name__}: {e})")
            click.echo("  Fix: start Ollama (Windows): open Ollama or run `ollama serve`")

    if full:
        click.echo("\n--- Provider Key Test ---")
        run_provider_checks(config)

    click.echo("\nQuick start (Windows): run-ui.cmd")
    if not full:
        click.echo("Run `thomas doctor --full` to test all provider API keys.")


def live_browser_smoke_cmd(
    ctx: click.Context,
    app_url: str,
    cdp_url: str,
    prompt: str,
    expect: str,
    type_delay_ms: int,
    reply_timeout: float,
    launch_browser: bool,
    browser: str,
    show_driver_logs: bool,
) -> None:
    from thomas.cli.live_browser import LiveBrowserSmokeError, run_live_browser_smoke

    config: AppConfig = ctx.obj["config"]
    runtime_root = config.memory.root_path

    click.echo("Live browser smoke test")
    click.echo(f"  app_url: {app_url}")
    click.echo(f"  cdp_url: {cdp_url}")
    click.echo(f"  browser: {browser}")

    try:
        result = run_live_browser_smoke(
            app_url=app_url,
            cdp_url=cdp_url,
            prompt=prompt,
            expect=expect,
            type_delay_ms=int(type_delay_ms),
            wait_timeout_s=float(reply_timeout),
            launch_browser=bool(launch_browser),
            browser=str(browser).strip().lower(),
            runtime_root=runtime_root,
        )
    except LiveBrowserSmokeError as e:
        click.echo(f"Live browser smoke failed: {e}", err=True)
        click.echo(
            "Tip: Start your browser with remote debugging, for example:",
            err=True,
        )
        click.echo(
            '  chrome --remote-debugging-port=9222 --remote-allow-origins=* --new-window "http://127.0.0.1:8899/"',
            err=True,
        )
        sys.exit(2)

    click.echo("")
    click.echo("Result:")
    click.echo(f"  ok: {result.ok}")
    click.echo(f"  launched_browser: {result.launched_browser}")
    click.echo(f"  page_url: {result.page_url}")
    click.echo(f"  expected: {result.expected}")
    click.echo(f"  matched_expected: {result.matched_expected}")
    click.echo(f"  final_text: {result.final_text}")

    if show_driver_logs:
        click.echo("")
        click.echo("--- driver stdout ---")
        click.echo(result.stdout.rstrip() or "(empty)")
        click.echo("--- driver stderr ---")
        click.echo(result.stderr.rstrip() or "(empty)")

    if not result.ok:
        sys.exit(2)


def telegram_run_cmd(
    ctx: click.Context,
    token: str,
    allow_chat_ids: tuple[int, ...],
    allow_chats_csv: str,
    model_name: str | None,
    shared_memory: bool,
    all_memories: bool,
    profile_memory: bool,
    sessions_file: Path | None,
    no_session_persist: bool,
    *,
    build_tools: Callable[[AppConfig], Any],
    build_memory: Callable[[AppConfig], Any],
    logger: Any,
) -> None:
    config: AppConfig = ctx.obj["config"]
    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    selected_model = model_name or config.default_model
    if selected_model not in config.models:
        click.echo(
            f"Unknown model profile '{selected_model}'. " f"Available: {', '.join(config.models.keys())}",
            err=True,
        )
        sys.exit(2)

    token_value = str(token or os.environ.get("THOMAS_TELEGRAM_BOT_TOKEN") or "").strip()
    if not token_value:
        click.echo("Telegram token missing.", err=True)
        click.echo("Set THOMAS_TELEGRAM_BOT_TOKEN or pass --token.", err=True)
        sys.exit(2)

    try:
        from thomas.integrations.telegram import (
            default_sessions_path,
            parse_allowed_chat_ids,
            run_telegram_polling,
        )
    except Exception as e:
        click.echo(f"Telegram integration unavailable: {type(e).__name__}: {e}", err=True)
        sys.exit(1)

    allowlisted: set[int] = set(int(x) for x in allow_chat_ids)
    allowlisted.update(parse_allowed_chat_ids(os.environ.get("THOMAS_TELEGRAM_ALLOWED_CHAT_IDS")))
    allowlisted.update(parse_allowed_chat_ids(allow_chats_csv))

    env_sessions = os.environ.get("THOMAS_TELEGRAM_SESSIONS_FILE")
    if sessions_file is None and env_sessions:
        sessions_file = Path(env_sessions)
    session_store = None if no_session_persist else (sessions_file or default_sessions_path(config))

    tools_registry = build_tools(config)
    memory = build_memory(config)

    click.echo(f"Starting Telegram bot with model profile '{selected_model}'...")
    if allowlisted:
        click.echo("Allowlisted chat ids: " + ", ".join(str(x) for x in sorted(allowlisted)))
    else:
        click.echo("Allowlisted chat ids: none (all chats accepted).")
    click.echo(
        "Shared memory mode: "
        + ("enabled (thread telegram:global)" if shared_memory else "disabled (per-chat thread ids, recommended)")
    )
    click.echo(
        "Memory retrieval policy: " + ("thread episodic + global facts" if all_memories else "thread episodic only")
    )
    click.echo("Profile memory: " + ("enabled" if profile_memory else "disabled"))
    click.echo("Session persistence: " + (str(session_store) if session_store is not None else "disabled"))

    try:
        run_telegram_polling(
            config,
            token=token_value,
            tools=tools_registry,
            memory=memory,
            model_name=selected_model,
            allowed_chat_ids=allowlisted or None,
            sessions_path=session_store,
            shared_memory=shared_memory,
            memory_retrieval_scope="thread",
            include_global_memory=all_memories,
            include_profile_memory=profile_memory,
        )
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    finally:
        if memory is not None:
            try:
                memory.close()
            except Exception as e:
                logger.debug("Failed to close memory engine after telegram stop: %s", e)
