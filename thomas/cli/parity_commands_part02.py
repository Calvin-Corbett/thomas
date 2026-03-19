@gateway.command("run")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8899, show_default=True, type=int)
@click.option("--auto-port/--strict-port", default=True, show_default=True)
@click.option("--detach/--foreground", default=True, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def gateway_run(
    ctx: click.Context,
    host: str,
    port: int,
    auto_port: bool,
    detach: bool,
    as_json: bool,
) -> None:
    """Start the gateway server."""
    config: AppConfig = ctx.obj["config"]
    selected_port = _resolve_bind_port(host, int(port), bool(auto_port), announce=None if as_json else click.echo)

    if not detach:
        from thomas.server.app import serve as serve_app

        serve_app(config, host=host, port=selected_port)
        return

    state = _load_gateway_state(config)
    prior_pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    if prior_pid > 0 and _is_pid_running(prior_pid):
        payload = {
            "ok": True,
            "already_running": True,
            "pid": prior_pid,
            "host": str(state.get("host") or host),
            "port": int(state.get("port") or selected_port),
            "url": f"http://{state.get('host', host)}:{int(state.get('port', selected_port))}/",
        }
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(f"Gateway already running (pid={payload['pid']}) at {payload['url']}")
        return

    cfg_path = str(ctx.obj.get("config_path") or "").strip()
    if not cfg_path:
        cfg_path = str(os.environ.get("THOMAS_CONFIG") or "").strip()
    log_path = _gateway_log_file(config)
    proc = _gateway_spawn(config_path=cfg_path, host=host, port=selected_port, log_path=log_path)
    time.sleep(1.2)
    running = _is_pid_running(int(proc.pid))
    probe = _probe_gateway(host, selected_port, token=config.server.api_token)
    payload = {
        "ok": bool(running),
        "pid": int(proc.pid),
        "host": host,
        "port": int(selected_port),
        "url": f"http://{host}:{int(selected_port)}/",
        "log_file": str(log_path),
        "healthy": bool(probe.get("healthy", False)),
    }
    if running:
        _save_gateway_state(
            config,
            {
                "pid": int(proc.pid),
                "host": host,
                "port": int(selected_port),
                "started_at": _utc_iso(),
                "log_file": str(log_path),
            },
        )
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Gateway pid: {payload['pid']}")
    click.echo(f"URL: {payload['url']}")
    click.echo(f"Healthy: {payload['healthy']}")
    click.echo(f"Log: {payload['log_file']}")


@gateway.command("status")
@click.option("--host", default=None, help="Override probe host.")
@click.option("--port", default=None, type=int, help="Override probe port.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def gateway_status(ctx: click.Context, host: str | None, port: int | None, as_json: bool) -> None:
    """Show gateway process + API health status."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, state = _active_gateway_target(config, host, port)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    process_running = bool(pid > 0 and _is_pid_running(pid))
    probe = _probe_gateway(use_host, use_port, token=config.server.api_token)
    payload = {
        "pid": pid,
        "process_running": process_running,
        "host": use_host,
        "port": int(use_port),
        "url": f"http://{use_host}:{int(use_port)}/",
        "state_file": str(_gateway_state_file(config)),
        "log_file": str(state.get("log_file") or _gateway_log_file(config)),
        "probe": probe,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"pid: {pid}")
    click.echo(f"process_running: {process_running}")
    click.echo(f"url: {payload['url']}")
    click.echo(f"tcp_open: {probe.get('tcp_open')}")
    click.echo(f"healthy: {probe.get('healthy')}")
    version = probe.get("version", {})
    models = probe.get("models", {})
    engines = probe.get("engines", {})
    click.echo(f"/api/version: ok={version.get('ok')} status={version.get('status')}")
    click.echo(f"/api/models: ok={models.get('ok')} status={models.get('status')}")
    click.echo(f"/api/engines: ok={engines.get('ok')} status={engines.get('status')}")


@gateway.command("stop")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def gateway_stop(ctx: click.Context, as_json: bool) -> None:
    """Stop the detached gateway process."""
    config: AppConfig = ctx.obj["config"]
    state = _load_gateway_state(config)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    if pid <= 0:
        payload = {"ok": False, "error": "no gateway pid in state", "state_file": str(_gateway_state_file(config))}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        raise click.ClickException(str(payload["error"]))
    running = _is_pid_running(pid)
    killed = False
    if running:
        killed = _kill_pid(pid)
        if not killed and not _is_pid_running(pid):
            killed = True
    _clear_gateway_state(config)
    payload = {
        "ok": bool((not _is_pid_running(pid)) and ((not running) or killed)),
        "pid": pid,
        "was_running": running,
        "killed": killed,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"pid: {pid}")
    click.echo(f"was_running: {running}")
    click.echo(f"killed: {killed}")
    click.echo(f"ok: {payload['ok']}")


@gateway.command("logs")
@click.option("--lines", default=120, show_default=True, type=int, help="Number of tail lines.")
@click.pass_context
def gateway_logs(ctx: click.Context, lines: int) -> None:
    """Print recent gateway log lines."""
    config: AppConfig = ctx.obj["config"]
    state = _load_gateway_state(config)
    log_file = Path(str(state.get("log_file") or _gateway_log_file(config)))
    if not log_file.exists():
        raise click.ClickException(f"Gateway log file not found: {log_file}")
    tail = _tail_file(log_file, lines=max(1, int(lines)))
    click.echo(tail)


@gateway.command("url")
@click.option("--host", default=None, help="Override host.")
@click.option("--port", default=None, type=int, help="Override port.")
@click.pass_context
def gateway_url(ctx: click.Context, host: str | None, port: int | None) -> None:
    """Print gateway UI URL."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, _state = _active_gateway_target(config, host, port)
    click.echo(f"http://{use_host}:{int(use_port)}/")


register_pack_proxy_commands(
    gateway,
    package="thomas.cli.commands.gateway",
    family_hint="gateway",
)


@click.command(name="dashboard")
@click.option("--open/--print-only", default=True, show_default=True, help="Open the UI in your browser.")
@click.option("--host", default=None, help="Override host.")
@click.option("--port", default=None, type=int, help="Override port.")
@click.pass_context
def dashboard(ctx: click.Context, open: bool, host: str | None, port: int | None) -> None:
    """Open the local dashboard UI."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, _state = _active_gateway_target(config, host, port)
    url = f"http://{use_host}:{int(use_port)}/"
    if open:
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            click.echo(f"Failed to open browser: {type(e).__name__}: {e}", err=True)
    click.echo(url)


@click.command(name="health")
@click.option("--host", default=None, help="Override host.")
@click.option("--port", default=None, type=int, help="Override port.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def health_cmd(ctx: click.Context, host: str | None, port: int | None, as_json: bool) -> None:
    """Fetch gateway health details."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, _state = _active_gateway_target(config, host, port)
    payload = _probe_gateway(use_host, use_port, token=config.server.api_token)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"url: {payload.get('base_url')}")
    click.echo(f"healthy: {payload.get('healthy')}")
    click.echo(f"tcp_open: {payload.get('tcp_open')}")
    version = payload.get("version", {})
    models = payload.get("models", {})
    engines = payload.get("engines", {})
    click.echo(f"/api/version -> ok={version.get('ok')} status={version.get('status')}")
    click.echo(f"/api/models -> ok={models.get('ok')} status={models.get('status')}")
    click.echo(f"/api/engines -> ok={engines.get('ok')} status={engines.get('status')}")


def _sessions_count(config: AppConfig) -> int:
    root = config.memory.root_path / ".thomas" / "chats"
    if not root.exists():
        return 0
    return len(list(root.glob("*.json")))


@click.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def status_cmd(ctx: click.Context, as_json: bool) -> None:
    """Show top-level Thomas status summary."""
    config: AppConfig = ctx.obj["config"]
    channel_store = _read_json(config.memory.root_path / ".thomas" / "channels.json", {"providers": {}})
    providers = channel_store.get("providers", {}) if isinstance(channel_store, dict) else {}
    if not isinstance(providers, dict):
        providers = {}

    def _provider_configured(name: str, token_env: str, webhook_env: str = "") -> bool:
        token = str(os.environ.get(token_env) or "").strip()
        webhook = str(os.environ.get(webhook_env) or "").strip() if webhook_env else ""
        row = providers.get(name, {})
        if isinstance(row, dict):
            token = token or str(row.get("token") or "").strip()
            webhook = webhook or str(row.get("webhook") or "").strip()
        return bool(token or webhook)

    cfg_telegram = _provider_configured("telegram", "THOMAS_TELEGRAM_BOT_TOKEN")
    cfg_discord = _provider_configured("discord", "THOMAS_DISCORD_BOT_TOKEN", "THOMAS_DISCORD_WEBHOOK_URL")
    cfg_slack = _provider_configured("slack", "THOMAS_SLACK_BOT_TOKEN", "THOMAS_SLACK_WEBHOOK_URL")
    channels_payload = {
        "telegram_configured": bool(cfg_telegram),
        "discord_configured": bool(cfg_discord),
        "slack_configured": bool(cfg_slack),
        "configured_count": int(bool(cfg_telegram)) + int(bool(cfg_discord)) + int(bool(cfg_slack)),
        "total_count": 3,
    }
    host, port, state = _active_gateway_target(config, None, None)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    process_running = bool(pid > 0 and _is_pid_running(pid))
    probe = _probe_gateway(host, port, token=config.server.api_token)
    payload = {
        "models": {"count": len(config.models), "default": str(config.default_model or "")},
        "channels": channels_payload,
        "gateway": {
            "pid": pid,
            "process_running": process_running,
            "url": f"http://{host}:{int(port)}/",
            "healthy": bool(probe.get("healthy", False)),
        },
        "sessions": {"count": _sessions_count(config)},
        "quality": {
            "enabled": bool(config.quality.enabled),
            "enforce": bool(config.quality.enforce),
            "require_verification_for_coding": bool(config.quality.require_verification_for_coding),
            "require_tests_for_code_edits": bool(config.quality.require_tests_for_code_edits),
            "require_monolith_guard_for_coding": bool(config.quality.require_monolith_guard_for_coding),
        },
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"models: {payload['models']['count']} (default={payload['models']['default']})")
    click.echo(f"channels: {payload['channels']['configured_count']}/{payload['channels']['total_count']} configured")
    click.echo(
        f"gateway: running={payload['gateway']['process_running']}, healthy={payload['gateway']['healthy']}, url={payload['gateway']['url']}"
    )
    click.echo(f"sessions: {payload['sessions']['count']}")
    click.echo(
        f"quality: enabled={payload['quality']['enabled']}, enforce={payload['quality']['enforce']}, verify={payload['quality']['require_verification_for_coding']}, tests={payload['quality']['require_tests_for_code_edits']}, monolith_guard={payload['quality']['require_monolith_guard_for_coding']}"
    )


def register_parity_commands(cli: click.Group) -> None:
    """Register parity command families on the main CLI group."""
    from thomas.cli.parity_compat import register_compat_commands

    commands = [
        agents,
        devices,
        sandbox,
        plugins,
        gateway,
        dashboard,
        status_cmd,
        health_cmd,
    ]
    for cmd in commands:
        name = str(getattr(cmd, "name", "") or "").strip()
        if not name:
            continue
        if name in cli.commands:
            continue
        cli.add_command(cmd)

    register_compat_commands(cli)
