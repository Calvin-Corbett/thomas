"""CLI entry point for Thomas.

Commands:
  thomas chat "prompt"          Single-shot query
  thomas repl                   Interactive REPL
  thomas serve --port 8899      HTTP server (Phase 5)
  thomas config show            Show active configuration
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Optional

try:
    import click
except ImportError:
    print("Thomas requires 'click'. Install with: pip install click")
    sys.exit(1)

from thomas.core.config import load_config, AppConfig
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.tools.registry import ToolRegistry
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.shell import register_shell_tools
from thomas.tools.git import register_git_tools
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.agent.guidance import guidance_bootstrap_report
from thomas.agent.loop import AgentLoop

log = logging.getLogger(__name__)


def _parse_model_switch_prompt(
    prompt: str, config: AppConfig
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse natural-language model switch requests.
    Returns (model_name, new_prompt, message).
    - model_name: selected model or None
    - new_prompt: remaining prompt to answer (None if no user question)
    - message: optional user-facing message to print and exit early
    """
    text = prompt.strip()
    if not text:
        return None, None, None

    lower = text.lower()
    # List models
    if "model" in lower and any(k in lower for k in ("list", "show", "what models", "available")):
        available = ", ".join(config.models.keys())
        return None, None, f"Available models: {available} (current: {config.default_model})"

    import re
    m = re.match(r"^(switch|use|set|change)\\s+(to\\s+)?(model\\s+)?(?P<name>[\\w\\-\\.:]+)(?P<rest>.*)$", lower)
    if not m:
        return None, None, None

    name = m.group("name")
    rest = (m.group("rest") or "").strip()
    for key in config.models.keys():
        if key.lower() == name:
            name = key
            break

    if name not in config.models:
        available = ", ".join(config.models.keys())
        return None, None, f"Unknown model '{name}'. Available: {available}"

    # Allow inline question: "use model X: question"
    if rest.startswith(":"):
        rest = rest[1:].strip()

    return name, (rest or None), None


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_tools(config: AppConfig) -> ToolRegistry:
    """Register all available tools based on configuration."""
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(registry, sandbox, config.tools.max_file_size)
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)
    return registry


def _build_memory(config: AppConfig):
    """Try to create and start the memory engine. Returns None on failure."""
    try:
        from thomas.memory.autonomy import AutonomyMemoryEngine

        enable_v2 = str(os.environ.get("THOMAS_MEMORY_V2_ENABLED", "1")).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        engine = AutonomyMemoryEngine(config, enable_v2=enable_v2, enable_legacy=True)
        engine.start()
        return engine
    except ImportError:
        logging.getLogger(__name__).warning("Memory engine import failed; continuing without memory.")
        return None
    except Exception as e:
        logging.getLogger(__name__).warning("Memory engine failed to start: %s", e)
        return None


def _build_library(config: AppConfig):
    """Create the research library store (best effort)."""
    try:
        from thomas.library import ResearchLibrary, default_library_root

        return ResearchLibrary(default_library_root(config))
    except Exception as e:
        logging.getLogger(__name__).warning("Library init failed: %s", e)
        return None


async def _run_chat(config: AppConfig, prompt: str, model_name: Optional[str]) -> None:
    """Run a single chat interaction with streaming output."""
    active_profile = model_name or config.default_model
    model_config = config.get_model(active_profile)
    llm = LLMClient(
        model_config,
        fallback_configs=config.failover_chain(active_profile),
        failover_enabled=config.failover.enabled,
        failover_cooldown_s=config.failover.cooldown_seconds,
        failover_on_auth_error=config.failover.fallback_on_auth_error,
    )
    tools = _build_tools(config)
    memory = _build_memory(config)
    agent = AgentLoop(config, llm, tools, memory=memory, thread_id="cli")

    try:
        tool_active = False
        async for event in agent.run(prompt):
            if event.type == EventType.TEXT_DELTA:
                sys.stdout.write(event.data["text"])
                sys.stdout.flush()

            elif event.type == EventType.TOOL_CALL_START:
                name = event.data["tool_name"]
                if not tool_active:
                    sys.stdout.write("\n")
                sys.stdout.write(f"\033[90m[calling {name}...]\033[0m ")
                sys.stdout.flush()
                tool_active = True

            elif event.type == EventType.TOOL_RESULT:
                ok = event.data["ok"]
                name = event.data["tool_name"]
                ms = event.data["duration_ms"]
                status = "\033[32mok\033[0m" if ok else "\033[31mfailed\033[0m"
                sys.stdout.write(f"\033[90m[{name}: {status} {ms:.0f}ms]\033[0m\n")
                sys.stdout.flush()
                tool_active = False

            elif event.type == EventType.AGENT_ERROR:
                sys.stderr.write(f"\n\033[31mError: {event.data['error']}\033[0m\n")

            elif event.type == EventType.AGENT_DONE:
                iters = event.data["iterations"]
                tc = event.data["tool_calls"]
                sys.stdout.write("\n")
                if tc > 0:
                    sys.stdout.write(
                        f"\033[90m({iters} iteration{'s' if iters != 1 else ''}, "
                        f"{tc} tool call{'s' if tc != 1 else ''})\033[0m\n"
                    )

        # Print token usage
        usage = llm.session_usage
        if usage.total_tokens > 0:
            sys.stdout.write(
                f"\033[90m[tokens: {usage.prompt_tokens} prompt + "
                f"{usage.completion_tokens} completion = {usage.total_tokens} total]\033[0m\n"
            )
    finally:
        await llm.close()
        if memory:
            memory.close()


@click.group(invoke_without_command=True)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("-c", "--config", "config_path", type=click.Path(exists=False), help="Config file path")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, config_path: Optional[str]) -> None:
    """Thomas - cutting-edge local-first AI coding assistant."""
    _setup_logging(verbose)
    path = Path(config_path) if config_path else None
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(path)
    ctx.obj["verbose"] = verbose

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("prompt")
@click.option("-m", "--model", "model_name", help="Model profile to use (e.g. 'local', 'cloud')")
@click.pass_context
def chat(ctx: click.Context, prompt: str, model_name: Optional[str]) -> None:
    """Send a single prompt and get a response."""
    config: AppConfig = ctx.obj["config"]

    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    # Natural-language model switching for single-shot chat
    if model_name is None:
        nl_model, nl_prompt, nl_message = _parse_model_switch_prompt(prompt, config)
        if nl_message:
            click.echo(nl_message)
            return
        if nl_model:
            model_name = nl_model
            if nl_prompt is None:
                click.echo(f"Switched to model '{model_name}' for this run. Ask a question.")
                return
            prompt = nl_prompt

    asyncio.run(_run_chat(config, prompt, model_name))


@cli.command("config")
@click.argument("action", type=click.Choice(["show"]))
@click.pass_context
def config_cmd(ctx: click.Context, action: str) -> None:
    """Show or manage configuration."""
    config: AppConfig = ctx.obj["config"]
    if action == "show":
        click.echo("Models:")
        for name, m in config.models.items():
            default = " (default)" if name == config.default_model else ""
            click.echo(f"  {name}{default}:")
            click.echo(f"    provider: {m.provider}")
            click.echo(f"    base_url: {m.base_url}")
            click.echo(f"    model: {m.model}")
            click.echo(f"    max_tokens: {m.max_tokens}")
            click.echo(f"    context_window: {m.context_window}")

        click.echo(f"\nMemory root: {config.memory.root}")
        click.echo(f"Tools sandbox: {config.tools.sandbox_root}")
        click.echo(f"Shell allowed: {config.tools.allow_shell}")
        click.echo(
            "Failover: "
            f"enabled={config.failover.enabled}, "
            f"profiles={config.failover.profiles or 'auto'}, "
            f"cooldown={config.failover.cooldown_seconds}s"
        )
        click.echo(f"Max iterations: {config.max_agent_iterations}")

        errors = config.validate()
        if errors:
            click.echo("\nValidation errors:")
            for e in errors:
                click.echo(f"  - {e}")


@cli.command()
@click.option("--port", default=8899, show_default=True, type=int, help="UI server port to check")
@click.option("--full", is_flag=True, help="Test all cloud provider API keys (requires network)")
@click.pass_context
def doctor(ctx: click.Context, port: int, full: bool) -> None:
    """Diagnose common setup issues and print the UI URL to open."""
    from thomas import __version__

    config: AppConfig = ctx.obj["config"]

    click.echo(f"Thomas {__version__}")

    errors = config.validate()
    if errors:
        click.echo("\nConfig issues:")
        for e in errors:
            click.echo(f"  - {e}")
    else:
        click.echo("\nConfig: OK")

    # Startup guidance visibility
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

    # Server deps
    try:
        import aiohttp  # noqa: F401
        click.echo("Server deps (aiohttp): OK")
    except Exception as e:
        click.echo(f"Server deps (aiohttp): MISSING ({e})")
        click.echo("  Fix: pip install -e \".[server]\"")

    # Port check
    in_use = False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.35):
            in_use = True
    except OSError:
        in_use = False

    click.echo(f"\nUI URL: http://127.0.0.1:{int(port)}/")
    click.echo(f"Port {int(port)}: " + ("IN USE (server already running?)" if in_use else "free"))

    # Local model endpoint quick check (best effort)
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

    # Full provider key check
    if full:
        click.echo("\n--- Provider Key Test ---")
        _run_provider_checks(config)

    click.echo("\nQuick start (Windows): run-ui.cmd")
    if not full:
        click.echo("Run `thomas doctor --full` to test all provider API keys.")


def _run_provider_checks(config: AppConfig) -> None:
    """Test all cloud provider API keys by hitting their /models endpoint."""
    from thomas.models.discovery import handshake_models_async
    from thomas.server.secrets import SecretStore
    from dataclasses import replace

    secret_store = SecretStore(config.memory.root_path / ".thomas")

    async def _check_all():
        import httpx

        results = []
        for name, mcfg in config.models.items():
            if name == "local":
                continue

            # Check if we have a key from secret store or config
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
                    click.echo(f"\r  {name}: \033[31mAUTH FAILED\033[0m — check/refresh your API key")
                    results.append((name, "auth_error", hs.error or "auth failed"))
                elif hs.status == "unsupported":
                    click.echo(f"\r  {name}: \033[33mNo /models endpoint\033[0m (may still work for chat)")
                    results.append((name, "unsupported", "no /models"))
                elif hs.status == "offline":
                    click.echo(f"\r  {name}: \033[31mOFFLINE\033[0m — endpoint unreachable")
                    results.append((name, "offline", hs.error or "offline"))
                else:
                    click.echo(f"\r  {name}: \033[31mERROR\033[0m — {hs.error or hs.status}")
                    results.append((name, "error", hs.error or hs.status))
            except Exception as e:
                click.echo(f"\r  {name}: \033[31mERROR\033[0m — {type(e).__name__}: {e}")
                results.append((name, "error", str(e)))

        # Summary
        ok = sum(1 for _, s, _ in results if s == "ok")
        skip = sum(1 for _, s, _ in results if s == "skip")
        fail = len(results) - ok - skip
        click.echo(f"\n  Summary: {ok} connected, {fail} failed, {skip} no key set")

    asyncio.run(_check_all())


@cli.group()
@click.pass_context
def models(ctx: click.Context) -> None:
    """Model utilities: list profiles, discover endpoint models, pull local models."""


@models.command("list")
@click.pass_context
def models_list(ctx: click.Context) -> None:
    """List configured model profiles."""
    config: AppConfig = ctx.obj["config"]
    click.echo("Model profiles:")
    for name, m in config.models.items():
        default = " (default)" if name == config.default_model else ""
        click.echo(f"  {name}{default}")
        click.echo(f"    provider: {m.provider}")
        click.echo(f"    base_url: {m.base_url}")
        click.echo(f"    model: {m.model}")
        # Only print non-default fields when they matter.
        if getattr(m, "chat_path", "/chat/completions") != "/chat/completions":
            click.echo(f"    chat_path: {m.chat_path}")
        if getattr(m, "models_path", "/models") != "/models":
            click.echo(f"    models_path: {m.models_path}")


@models.command("discover")
@click.option("-m", "--model", "model_name", help="Model profile to query (default: current default)")
@click.option("--timeout", "timeout_s", type=float, default=2.0, show_default=True)
@click.pass_context
def models_discover(ctx: click.Context, model_name: Optional[str], timeout_s: float) -> None:
    """Discover model ids available at an endpoint (best effort)."""
    config: AppConfig = ctx.obj["config"]
    cfg = config.get_model(model_name)

    from thomas.models.discovery import discover_models

    found = discover_models(cfg, timeout_s=timeout_s)
    if not found:
        click.echo(f"No models discovered at {cfg.base_url}.")
        return

    click.echo(f"Models at {cfg.base_url}:")
    for i, dm in enumerate(found, start=1):
        click.echo(f"  {i:>2}. {dm.id}")


@models.command("pull")
@click.argument("model_id")
@click.option(
    "-p",
    "--profile",
    "profile_name",
    help="Config profile to update in-memory after pull (default: current default).",
)
@click.option(
    "--set",
    "set_after",
    is_flag=True,
    help="After pull, set the profile's model id for this run (does not edit thomas.toml).",
)
@click.pass_context
def models_pull(
    ctx: click.Context, model_id: str, profile_name: Optional[str], set_after: bool
) -> None:
    """Pull a local model via Ollama (requires the `ollama` CLI)."""
    import shutil
    import subprocess  # nosec

    if shutil.which("ollama") is None:
        click.echo("ollama not found in PATH. Install Ollama first: https://ollama.com", err=True)
        sys.exit(2)

    cmd = ["ollama", "pull", model_id]
    click.echo("Running: " + " ".join(cmd))
    rc = subprocess.call(cmd)  # nosec
    if rc != 0:
        sys.exit(rc)

    if set_after:
        config: AppConfig = ctx.obj["config"]
        profile = profile_name or config.default_model
        if profile not in config.models:
            click.echo(
                f"Unknown profile '{profile}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        config.models[profile].model = model_id
        click.echo(f"Set profile '{profile}' model id to: {model_id}")


@cli.group()
@click.pass_context
def codex(ctx: click.Context) -> None:
    """Codex integration — use your ChatGPT subscription with Thomas."""


@codex.command("login")
@click.pass_context
def codex_login(ctx: click.Context) -> None:
    """Sign in to ChatGPT (opens browser). Uses your ChatGPT Plus/Pro subscription."""
    async def _login() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            click.echo("Checking auth status...")
            acct = await bridge.check_auth()
            if acct.logged_in:
                click.echo(f"Already signed in: {acct.email} ({acct.plan_type} plan)")
                return
            click.echo("Opening browser to sign in with ChatGPT...")
            acct = await bridge.login_chatgpt()
            click.echo(f"Signed in: {acct.email} ({acct.plan_type} plan)")
            click.echo("You can now use: thomas chat -m codex \"your prompt\"")
            click.echo("Or set default_model = \"codex\" in thomas.toml")
        finally:
            await bridge.stop()

    asyncio.run(_login())


@codex.command("status")
@click.pass_context
def codex_status(ctx: click.Context) -> None:
    """Check ChatGPT authentication status."""
    async def _status() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            acct = await bridge.check_auth()
            if acct.logged_in:
                click.echo(f"Signed in: {acct.email}")
                click.echo(f"  Plan: {acct.plan_type}")
                click.echo(f"  Auth: {acct.auth_type}")
                # List available models
                try:
                    models_list = await bridge.list_models()
                    if models_list:
                        click.echo("  Models:")
                        for m in models_list:
                            d = " (default)" if m.is_default else ""
                            click.echo(f"    {m.id}{d}")
                except Exception as e:
                    log.debug("Failed to list codex models in status: %s", e)
            else:
                click.echo("Not signed in. Run: thomas codex login")
        finally:
            await bridge.stop()

    asyncio.run(_status())


@codex.command("logout")
@click.pass_context
def codex_logout(ctx: click.Context) -> None:
    """Sign out of ChatGPT."""
    async def _logout() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            await bridge.logout()
            click.echo("Signed out.")
        finally:
            await bridge.stop()

    asyncio.run(_logout())


@codex.command("models")
@click.pass_context
def codex_models(ctx: click.Context) -> None:
    """List models available through your ChatGPT plan."""
    async def _models() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            acct = await bridge.check_auth()
            if not acct.logged_in:
                click.echo("Not signed in. Run: thomas codex login")
                return
            models_found = await bridge.list_models()
            if not models_found:
                click.echo("No models found.")
                return
            click.echo(f"Models available ({acct.plan_type} plan):")
            for m in models_found:
                d = " (default)" if m.is_default else ""
                name = f" — {m.display_name}" if m.display_name else ""
                click.echo(f"  {m.id}{name}{d}")
        finally:
            await bridge.stop()

    asyncio.run(_models())


@cli.group()
@click.pass_context
def doppelganger(ctx: click.Context) -> None:
    """Blue/green upgrade sandbox utilities (Doppelganger Protocol)."""


@doppelganger.command("status")
@click.pass_context
def dg_status(ctx: click.Context) -> None:
    """Show blue/green paths and whether the green slot is present."""
    from thomas.upgrade.doppelganger import get_paths

    p = get_paths()
    click.echo("Doppelganger paths:")
    click.echo(f"  blue_root      : {p.blue_root}")
    click.echo(f"  dg_root        : {p.dg_root}")
    click.echo(f"  green_root     : {p.green_root} ({'present' if p.green_root.exists() else 'missing'})")
    click.echo(f"  green_runtime  : {p.green_runtime}")
    click.echo(f"  green_venv     : {p.green_venv} ({'present' if p.green_venv.exists() else 'missing'})")
    click.echo(f"  backups_root   : {p.backups_root}")


@doppelganger.command("sync")
@click.pass_context
def dg_sync(ctx: click.Context) -> None:
    """Sync Blue -> Green (creates/updates the green sandbox working copy)."""
    from thomas.upgrade.doppelganger import get_paths, sync_blue_to_green

    p = get_paths()
    p.dg_root.mkdir(parents=True, exist_ok=True)
    sync_blue_to_green(p)
    click.echo(f"Synced Blue -> Green at: {p.green_root}")


@doppelganger.command("test")
@click.option(
    "--sync-from-blue",
    is_flag=True,
    help="Sync Blue -> Green before running tests (WARNING: overwrites green).",
)
@click.pass_context
def dg_test(ctx: click.Context, sync_from_blue: bool) -> None:
    """Run tests in Green (uses isolated green venv)."""
    from thomas.upgrade.doppelganger import get_paths, run_green_tests, sync_blue_to_green

    p = get_paths()
    if sync_from_blue:
        sync_blue_to_green(p)
    if not p.green_root.exists():
        click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
        sys.exit(2)
    run_green_tests(p)
    click.echo("Green tests: OK")


@doppelganger.command("serve-green")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8902, show_default=True, type=int)
@click.option(
    "--sync-from-blue",
    is_flag=True,
    help="Sync Blue -> Green before serving (WARNING: overwrites green).",
)
@click.pass_context
def dg_serve_green(ctx: click.Context, host: str, port: int, sync_from_blue: bool) -> None:
    """Run the server from Green using an isolated runtime root (no real memory/secrets)."""
    from thomas.upgrade.doppelganger import get_paths, run_green_server, sync_blue_to_green

    p = get_paths()
    if sync_from_blue:
        sync_blue_to_green(p)
    if not p.green_root.exists():
        click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
        sys.exit(2)
    click.echo(f"Green UI: http://{host}:{int(port)}/ (memory root: {p.green_runtime})")
    run_green_server(p, host=host, port=int(port))


@doppelganger.command("promote")
@click.option(
    "--stop-port",
    default=8899,
    show_default=True,
    type=int,
    help="If a Thomas server is listening on this port, attempt to stop it before promotion.",
)
@click.pass_context
def dg_promote(ctx: click.Context, stop_port: int) -> None:
    """Promote Green -> Blue (with backup)."""
    from thomas.upgrade.doppelganger import get_paths, latest_backup, promote_green_to_blue

    p = get_paths()
    if not p.green_root.exists():
        click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
        sys.exit(2)

    before = latest_backup(p)
    backup = promote_green_to_blue(p, stop_port=int(stop_port))
    click.echo(f"Promoted Green -> Blue. Backup created at: {backup}")
    if before:
        click.echo(f"Previous latest backup was: {before}")


@doppelganger.command("rollback")
@click.option(
    "--backup",
    "backup_path",
    type=click.Path(exists=False),
    help="Specific backup directory to restore (default: latest).",
)
@click.pass_context
def dg_rollback(ctx: click.Context, backup_path: Optional[str]) -> None:
    """Rollback Blue to the latest (or specified) backup snapshot."""
    from thomas.upgrade.doppelganger import get_paths, rollback

    p = get_paths()
    b = Path(backup_path).resolve() if backup_path else None
    restored = rollback(p, backup_dir=b)
    click.echo(f"Restored Blue from backup: {restored}")


@cli.group()
@click.pass_context
def telegram(ctx: click.Context) -> None:
    """Telegram bot integration."""


@telegram.command("run")
@click.option(
    "--token",
    "token",
    default="",
    help="Telegram bot token (or set THOMAS_TELEGRAM_BOT_TOKEN).",
)
@click.option(
    "--allow-chat",
    "allow_chat_ids",
    multiple=True,
    type=int,
    help="Allow this Telegram chat id (repeatable).",
)
@click.option(
    "--allow-chats",
    "allow_chats_csv",
    default="",
    help="Additional allowlisted chat ids as CSV (e.g. 123,456).",
)
@click.option(
    "-m",
    "--model",
    "model_name",
    help="Model profile for Telegram chats (default: current default model).",
)
@click.option(
    "--shared-memory/--isolated-memory",
    "shared_memory",
    default=False,
    show_default=True,
    help="Share one long-term memory stream across all Telegram chats.",
)
@click.option(
    "--all-memories/--chat-memories-only",
    "all_memories",
    default=True,
    show_default=True,
    help="Include curated global memory (facts/profile) in addition to this chat thread.",
)
@click.option(
    "--profile-memory/--no-profile-memory",
    "profile_memory",
    default=True,
    show_default=True,
    help="Include long-term profile hints in Telegram memory retrieval.",
)
@click.option(
    "--sessions-file",
    "sessions_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path for persisted Telegram session state.",
)
@click.option(
    "--no-session-persist",
    "no_session_persist",
    is_flag=True,
    help="Disable on-disk Telegram session persistence.",
)
@click.pass_context
def telegram_run(
    ctx: click.Context,
    token: str,
    allow_chat_ids: tuple[int, ...],
    allow_chats_csv: str,
    model_name: Optional[str],
    shared_memory: bool,
    all_memories: bool,
    profile_memory: bool,
    sessions_file: Optional[Path],
    no_session_persist: bool,
) -> None:
    """Run a Telegram bot that routes messages through Thomas."""
    config: AppConfig = ctx.obj["config"]
    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    selected_model = model_name or config.default_model
    if selected_model not in config.models:
        click.echo(
            f"Unknown model profile '{selected_model}'. "
            f"Available: {', '.join(config.models.keys())}",
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

    tools_registry = _build_tools(config)
    memory = _build_memory(config)

    click.echo(f"Starting Telegram bot with model profile '{selected_model}'...")
    if allowlisted:
        click.echo("Allowlisted chat ids: " + ", ".join(str(x) for x in sorted(allowlisted)))
    else:
        click.echo("Allowlisted chat ids: none (all chats accepted).")
    click.echo(
        "Shared memory mode: "
        + (f"enabled (thread telegram:global)" if shared_memory else "disabled (per-chat thread ids, recommended)")
    )
    click.echo(
        "Memory retrieval policy: "
        + (
            "thread episodic + global facts"
            if all_memories
            else "thread episodic only"
        )
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
                log.debug("Failed to close memory engine after telegram stop: %s", e)


@cli.command()
@click.pass_context
def tools(ctx: click.Context) -> None:
    """List available tools."""
    config: AppConfig = ctx.obj["config"]
    registry = _build_tools(config)

    for cat in registry.list_categories():
        click.echo(f"\n{cat}:")
        for tool in registry.list_tools(cat):
            click.echo(f"  {tool.name} - {tool.description[:80]}")


@cli.group()
@click.pass_context
def library(ctx: click.Context) -> None:
    """Manage the durable research library (separate from chat memory)."""


@library.command("where")
@click.pass_context
def library_where(ctx: click.Context) -> None:
    """Show library root path and key files."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    click.echo(f"Library root: {store.root}")
    click.echo(f"Catalog: {store.index_path}")
    click.echo(f"Index: {store.toc_path}")


@library.command("list")
@click.option("--category", "category", default="", help="Filter by category.")
@click.option("--query", "query", default="", help="Search query.")
@click.option("--limit", "limit", type=int, default=25, show_default=True)
@click.pass_context
def library_list(ctx: click.Context, category: str, query: str, limit: int) -> None:
    """List library entries."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    rows = store.list_entries(
        category=(category.strip() or None),
        query=(query.strip() or None),
        limit=max(1, int(limit)),
    )
    if not rows:
        click.echo("No library entries found.")
        return
    click.echo(f"Found {len(rows)} entries:")
    for row in rows:
        rid = str(row.get("id", ""))
        title = str(row.get("title", rid))
        cat = str(row.get("category", "uncategorized"))
        src = str(row.get("source", ""))
        click.echo(f"- {rid} [{cat}] {title}")
        if src:
            click.echo(f"  source: {src}")


@library.command("show")
@click.argument("entry_id")
@click.pass_context
def library_show(ctx: click.Context, entry_id: str) -> None:
    """Show one library entry (metadata + content)."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    row = store.get_entry(entry_id)
    if row is None:
        click.echo(f"Entry not found: {entry_id}", err=True)
        sys.exit(2)
    click.echo(f"id: {row.get('id')}")
    click.echo(f"title: {row.get('title')}")
    click.echo(f"category: {row.get('category')}")
    click.echo(f"source: {row.get('source')}")
    tags = row.get("tags") or []
    if isinstance(tags, list) and tags:
        click.echo("tags: " + ", ".join(str(t) for t in tags))
    click.echo("")
    click.echo(str(row.get("content", "")))


@library.command("add")
@click.option("--title", "title", required=True, help="Entry title.")
@click.option("--category", "category", default="research-notes", show_default=True)
@click.option("--summary", "summary", default="", help="Short summary.")
@click.option("--source", "source", default="", help="Source URL or citation note.")
@click.option("--tags", "tags", default="", help="Comma-separated tags.")
@click.option("--content", "content", default="", help="Inline content text.")
@click.option("--content-file", "content_file", type=click.Path(exists=True, dir_okay=False), default="")
@click.option("--query", "query", default="", help="Original research query.")
@click.pass_context
def library_add(
    ctx: click.Context,
    title: str,
    category: str,
    summary: str,
    source: str,
    tags: str,
    content: str,
    content_file: str,
    query: str,
) -> None:
    """Add a new library entry."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)

    payload = str(content or "").strip()
    if content_file:
        payload = Path(content_file).read_text(encoding="utf-8", errors="replace").strip()
    if not payload:
        click.echo("Missing content. Use --content or --content-file.", err=True)
        sys.exit(2)

    tag_list = [x.strip() for x in str(tags or "").split(",") if x.strip()]
    row = store.add_entry(
        title=title,
        category=category,
        content=payload,
        summary=summary,
        source=source,
        tags=tag_list,
        query=query,
        auto_captured=False,
        dedupe=True,
    )
    click.echo(f"Saved: {row.get('id')} -> {row.get('path')}")


@library.command("reindex")
@click.pass_context
def library_reindex(ctx: click.Context) -> None:
    """Rebuild table of contents from catalog."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    store.rebuild_toc()
    click.echo(f"Rebuilt: {store.toc_path}")


@library.command("curate")
@click.option("--force", is_flag=True, help="Ignore curator interval cooldown.")
@click.pass_context
def library_curate(ctx: click.Context, force: bool) -> None:
    """Run one memory curator pass (promote chat/library knowledge into durable memory)."""
    config: AppConfig = ctx.obj["config"]
    memory = _build_memory(config)
    if memory is None:
        click.echo("Memory engine unavailable.", err=True)
        sys.exit(1)
    try:
        runner = getattr(memory, "run_curator", None)
        if not callable(runner):
            click.echo("Curator unavailable for current memory backend.", err=True)
            sys.exit(2)
        result = runner(force=bool(force))
        if not isinstance(result, dict):
            result = {"ran": False, "reason": "invalid_result"}
        click.echo("Curator run:")
        for key in (
            "ran",
            "reason",
            "episodes_scanned",
            "library_entries_scanned",
            "hints_promoted",
            "facts_promoted",
            "duplicates_skipped",
            "last_episode_id",
            "last_library_ts_utc",
        ):
            if key in result:
                click.echo(f"- {key}: {result.get(key)}")
    finally:
        try:
            memory.close()
        except Exception as e:
            log.debug("Failed to close memory engine after library curate: %s", e)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8899, show_default=True, type=int, help="Bind port")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Run the web UI + HTTP API server."""
    config: AppConfig = ctx.obj["config"]
    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    try:
        from thomas.server.app import serve as serve_app
        serve_app(config, host=host, port=port)
    except ModuleNotFoundError as e:
        # Most commonly: aiohttp missing.
        click.echo(f"Server dependencies missing: {e}", err=True)
        click.echo("Install with: pip install -e \".[server]\"", err=True)
        sys.exit(1)


@cli.command()
@click.option("-m", "--model", "model_name", help="Model profile to use")
@click.pass_context
def repl(ctx: click.Context, model_name: Optional[str]) -> None:
    """Start the interactive REPL with rich terminal UI."""
    try:
        from thomas.cli.repl import ThomasREPL
    except ImportError as e:
        click.echo(f"REPL requires additional dependencies: {e}", err=True)
        click.echo("Install with: pip install prompt_toolkit>=3.0 rich>=13.0", err=True)
        sys.exit(1)

    config: AppConfig = ctx.obj["config"]
    if model_name:
        config.default_model = model_name

    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    tools_registry = _build_tools(config)

    # On Windows, prompt_toolkit may need the SelectorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    repl_instance = ThomasREPL(config, tools_registry)
    asyncio.run(repl_instance.run())


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
