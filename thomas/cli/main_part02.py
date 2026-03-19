@models.command("validate")
@click.option("-m", "--model", "model_name", help="Validate one model profile (default: all profiles).")
@click.option("--timeout", "timeout_s", type=float, default=3.0, show_default=True, help="Handshake timeout seconds.")
@click.option(
    "--tool-timeout",
    "tool_timeout_s",
    type=float,
    default=20.0,
    show_default=True,
    help="Tool-call smoke timeout seconds.",
)
@click.option("--no-tool-smoke", is_flag=True, help="Skip the synthetic tool-calling smoke test.")
@click.option(
    "--strict/--no-strict",
    default=True,
    show_default=True,
    help="Exit non-zero when any validated profile fails.",
)
@click.pass_context
def models_validate(
    ctx: click.Context,
    model_name: str | None,
    timeout_s: float,
    tool_timeout_s: float,
    no_tool_smoke: bool,
    strict: bool,
) -> None:
    """Validate profile readiness for onboarding (connectivity + tool-calling)."""
    from dataclasses import replace

    from thomas.models.protocol import validate_model_profile_async
    from thomas.server.secrets import SecretStore

    config: AppConfig = ctx.obj["config"]
    selected: list[str]
    if model_name:
        if model_name not in config.models:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        selected = [model_name]
    else:
        selected = list(config.models.keys())

    secret_store = SecretStore(config.memory.root_path / ".thomas")

    async def _run() -> list[Any]:
        out = []
        for profile in selected:
            cfg = config.get_model(profile)
            stored_key = secret_store.get(profile)
            if stored_key:
                cfg = replace(cfg, api_key=stored_key)
            report = await validate_model_profile_async(
                cfg,
                handshake_timeout_s=max(0.5, float(timeout_s)),
                tool_timeout_s=max(2.0, float(tool_timeout_s)),
                run_tool_smoke=not bool(no_tool_smoke),
            )
            out.append(report)
        return out

    reports = asyncio.run(_run())
    failures = 0
    click.echo("Model validation:")
    for rep in reports:
        status = "OK" if rep.ok else "FAIL"
        click.echo(f"  {rep.profile}: {status}")
        hs = rep.handshake
        hs_http = f" ({hs.http_status})" if hs.http_status is not None else ""
        click.echo(f"    handshake: {hs.status}{hs_http}")
        if hs.error:
            click.echo(f"      {hs.error}")
        ts = rep.tool_smoke
        click.echo(f"    tool_smoke: {ts.status}")
        if ts.error:
            click.echo(f"      {ts.error}")
        if not rep.ok:
            failures += 1

    passed = len(reports) - failures
    click.echo(f"\nSummary: {passed} passed, {failures} failed")
    if failures > 0 and strict:
        sys.exit(2)


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
def models_pull(ctx: click.Context, model_id: str, profile_name: str | None, set_after: bool) -> None:
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


def _emit_models_compat(action: str, note: str, as_json: bool) -> None:
    payload = {
        "command": "models",
        "action": str(action),
        "compatibility": "partial",
        "note": str(note),
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"models {action}: {note}")


def _models_state_path(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "cli" / "models_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _models_state_now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_models_state(config: AppConfig) -> dict[str, Any]:
    path = _models_state_path(config)
    default: dict[str, Any] = {
        "aliases": {},
        "image": {},
        "image_fallback_profiles": [],
        "updated_at": "",
    }
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
    if not isinstance(raw, dict):
        return default
    aliases = raw.get("aliases")
    image = raw.get("image")
    image_fallback_profiles = raw.get("image_fallback_profiles")
    return {
        "aliases": dict(aliases) if isinstance(aliases, dict) else {},
        "image": dict(image) if isinstance(image, dict) else {},
        "image_fallback_profiles": list(image_fallback_profiles) if isinstance(image_fallback_profiles, list) else [],
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _save_models_state(config: AppConfig, state: dict[str, Any]) -> Path:
    path = _models_state_path(config)
    aliases_raw = state.get("aliases")
    image_raw = state.get("image")
    image_fallback_raw = state.get("image_fallback_profiles")
    aliases = {
        str(k).strip().lower(): str(v).strip()
        for k, v in (aliases_raw.items() if isinstance(aliases_raw, dict) else [])
        if str(k).strip() and str(v).strip()
    }
    image = dict(image_raw) if isinstance(image_raw, dict) else {}
    fallback_profiles = [
        str(x).strip() for x in (image_fallback_raw if isinstance(image_fallback_raw, list) else []) if str(x).strip()
    ]
    payload = {
        "aliases": aliases,
        "image": image,
        "image_fallback_profiles": fallback_profiles,
        "updated_at": _models_state_now_utc(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _provider_env_keys(provider: str) -> list[str]:
    key = str(provider or "").strip().lower()
    mapping: dict[str, list[str]] = {
        "openai_compat": ["OPENAI_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "groq": ["GROQ_API_KEY"],
        "mistral": ["MISTRAL_API_KEY"],
        "xai": ["XAI_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "perplexity": ["PERPLEXITY_API_KEY"],
    }
    return list(mapping.get(key, []))


def _runtime_model_error(*, as_json: bool, message: str, profile: str = "") -> None:
    payload = {
        "ok": False,
        "error": "invalid_request",
        "message": str(message),
    }
    if profile:
        payload["profile"] = profile
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
    else:
        click.echo(str(message), err=True)
    raise SystemExit(2)


def _resolve_repl_profile_from_prefs(config: AppConfig) -> tuple[str, str]:
    """Resolve REPL startup profile and optional model-id override from shared resolver."""
    try:
        from thomas.core.model_resolution import resolve_effective_model

        return resolve_effective_model(
            config,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
        )
    except Exception:
        return str(config.default_model or "").strip(), ""


def _resolve_model_profile_name(config: AppConfig, profile_name: str | None) -> str:
    """Resolve a model profile name case-insensitively against config profiles."""
    try:
        from thomas.core.model_resolution import resolve_model_profile_name as _resolver

        return _resolver(config, profile_name)
    except Exception:
        requested = str(profile_name or "").strip()
        if not requested:
            return ""
        if requested in config.models:
            return requested
        requested_l = requested.lower()
        for profile in config.models:
            if profile.lower() == requested_l:
                return profile
        return ""


def _repl_needs_codex_event_loop(config: AppConfig, active_profile: str) -> bool:
    """Whether the REPL may route to Codex on Windows and needs Proactor."""
    if any(str(cfg.provider or "").strip().lower() == "codex" for cfg in config.models.values()):
        return True

    selected_profile = _resolve_model_profile_name(config, active_profile)
    if not selected_profile:
        return False
    if not config.failover.enabled:
        return False

    for fb_cfg in config.failover_chain(selected_profile):
        if str(fb_cfg.provider or "").strip().lower() == "codex":
            return True
    return False


@models.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_status(ctx: click.Context, as_json: bool) -> None:
    """Show configured model status summary."""
    config: AppConfig = ctx.obj["config"]
    payload = {
        "default_model": str(config.default_model),
        "profiles": sorted(config.models.keys()),
        "profile_count": len(config.models),
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"default_model: {payload['default_model']}")
    click.echo(f"profiles: {', '.join(payload['profiles'])}")
    click.echo(f"profile_count: {payload['profile_count']}")


@models.command("scan")
@click.option("--timeout", "timeout_s", type=float, default=2.0, show_default=True)
@click.pass_context
def models_scan(ctx: click.Context, timeout_s: float) -> None:
    """Compatibility alias for model discovery scans."""
    _run_models_discover(ctx, model_name=None, timeout_s=timeout_s)


@models.command("set")
@click.argument("model_id")
@click.option(
    "--profile", "profile_name", default=None, help="Profile to update (default: current default model profile)."
)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_set(ctx: click.Context, model_id: str, profile_name: str | None, as_json: bool) -> None:
    """Set the active model id for a profile (runtime only)."""
    config: AppConfig = ctx.obj["config"]
    profile = str(profile_name or config.default_model)
    if profile not in config.models:
        payload = {"ok": False, "error": "unknown_profile", "profile": profile}
        if as_json:
            _emit_json(payload, ensure_ascii=False, indent=2)
        else:
            click.echo(f"Unknown profile '{profile}'. Available: {', '.join(config.models.keys())}", err=True)
        raise SystemExit(2)
    config.models[profile].model = str(model_id)
    payload = {
        "ok": True,
        "profile": profile,
        "model": str(model_id),
        "note": "Updated in-memory profile for this run (does not rewrite thomas.toml).",
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
    else:
        click.echo(f"set profile '{profile}' model to '{model_id}'")
        click.echo(payload["note"])


@models.command("set-image")
@click.option("--profile", "profile_name", default="", help="Model profile to bind as the image profile.")
@click.option("--model", "model_id", default="", help="Optional model id override for the image profile.")
@click.option("--clear", is_flag=True, help="Clear runtime image profile override and use default profile/model.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_set_image(
    ctx: click.Context,
    profile_name: str,
    model_id: str,
    clear: bool,
    as_json: bool,
) -> None:
    """Set or inspect runtime image model assignment."""
    config: AppConfig = ctx.obj["config"]
    state = _load_models_state(config)
    changed = False
    if clear:
        state["image"] = {}
        changed = True

    profile_text = str(profile_name or "").strip()
    model_text = str(model_id or "").strip()
    if profile_text or model_text:
        selected_profile = profile_text or str(config.default_model)
        if selected_profile not in config.models:
            _runtime_model_error(
                as_json=as_json,
                profile=selected_profile,
                message=f"Unknown profile '{selected_profile}'. Available: {', '.join(config.models.keys())}",
            )
        selected_model = model_text or str(config.models[selected_profile].model)
        state["image"] = {
            "profile": selected_profile,
            "model": selected_model,
            "updated_at": _models_state_now_utc(),
        }
        changed = True

    if changed:
        _save_models_state(config, state)

    image_row = dict(state.get("image") or {})
    image_profile = str(image_row.get("profile") or "").strip()
    image_model = str(image_row.get("model") or "").strip()
    source = "state"
    if not image_profile or image_profile not in config.models:
        image_profile = str(config.default_model)
        image_model = str(config.models[image_profile].model)
        source = "default_profile"
    elif not image_model:
        image_model = str(config.models[image_profile].model)

    payload = {
        "ok": True,
        "action": "set-image",
        "profile": image_profile,
        "model": image_model,
        "source": source,
        "state_file": str(_models_state_path(config)),
        "available_profiles": sorted(config.models.keys()),
        "note": "Runtime-only mapping (does not rewrite thomas.toml).",
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"image profile: {payload['profile']}")
    click.echo(f"image model: {payload['model']}")
    click.echo(f"source: {payload['source']}")
    click.echo(payload["note"])


@models.command("aliases")
@click.option("--set", "set_pairs", multiple=True, help="Set alias mapping as alias=profile_or_model (repeatable).")
@click.option("--remove", "remove_aliases", multiple=True, help="Remove alias mapping by alias key (repeatable).")
@click.option("--resolve", "resolve_alias", default="", help="Resolve one alias/profile to effective profile+model.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_aliases(
    ctx: click.Context,
    set_pairs: tuple[str, ...],
    remove_aliases: tuple[str, ...],
    resolve_alias: str,
    as_json: bool,
) -> None:
    """Manage runtime model aliases."""
    config: AppConfig = ctx.obj["config"]
    state = _load_models_state(config)
    aliases = {
        str(k).strip().lower(): str(v).strip()
        for k, v in dict(state.get("aliases") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    changed = False

    for raw in set_pairs:
        text = str(raw or "").strip()
        if "=" not in text:
            _runtime_model_error(as_json=as_json, message=f"Invalid --set '{text}'. Expected alias=profile_or_model.")
        alias_raw, target_raw = text.split("=", 1)
        alias = str(alias_raw or "").strip().lower()
        target = str(target_raw or "").strip()
        if not alias or not target:
            _runtime_model_error(as_json=as_json, message=f"Invalid --set '{text}'. Alias and target are required.")
        aliases[alias] = target
        changed = True

    for raw in remove_aliases:
        key = str(raw or "").strip().lower()
        if key and key in aliases:
            aliases.pop(key, None)
            changed = True

    if changed:
        state["aliases"] = aliases
        _save_models_state(config, state)

    rows: list[dict[str, Any]] = []
    for alias, target in sorted(aliases.items(), key=lambda item: item[0]):
        target_type = "profile" if target in config.models else "model"
        model = str(config.models[target].model) if target_type == "profile" else str(target)
        rows.append(
            {
                "alias": alias,
                "target": target,
                "target_type": target_type,
                "model": model,
            }
        )

    resolved_payload: dict[str, Any] | None = None
    resolve_text = str(resolve_alias or "").strip()
    if resolve_text:
        key = resolve_text.lower()
        if key in aliases:
            target = str(aliases[key])
            if target in config.models:
                resolved_payload = {
                    "query": resolve_text,
                    "source": "alias",
                    "profile": target,
                    "model": str(config.models[target].model),
                }
            else:
                resolved_payload = {
                    "query": resolve_text,
                    "source": "alias",
                    "profile": "",
                    "model": target,
                }
        elif resolve_text in config.models:
            resolved_payload = {
                "query": resolve_text,
                "source": "profile",
                "profile": resolve_text,
                "model": str(config.models[resolve_text].model),
            }
        else:
            for profile_name in config.models:
                if str(profile_name).lower() == key:
                    resolved_payload = {
                        "query": resolve_text,
                        "source": "profile",
                        "profile": profile_name,
                        "model": str(config.models[profile_name].model),
                    }
                    break

    payload = {
        "ok": True,
        "action": "aliases",
        "count": len(rows),
        "aliases": rows,
        "state_file": str(_models_state_path(config)),
    }
    if resolved_payload is not None:
        payload["resolved"] = resolved_payload

    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"aliases: {payload['count']}")
    for row in rows:
        click.echo(f"  {row['alias']} -> {row['target']} ({row['target_type']})")
    if resolved_payload is not None:
        click.echo(
            "resolved: "
            f"{resolved_payload.get('query')} -> "
            f"profile={resolved_payload.get('profile') or '(none)'} "
            f"model={resolved_payload.get('model')}"
        )


@models.command("auth")
@click.option("--profile", "profile_name", default="", help="Inspect one model profile (default: all).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_auth(ctx: click.Context, profile_name: str, as_json: bool) -> None:
    """Show effective auth readiness per model profile."""
    from thomas.server.secrets import SecretStore

    config: AppConfig = ctx.obj["config"]
    selected_profile = str(profile_name or "").strip()
    if selected_profile:
        if selected_profile not in config.models:
            _runtime_model_error(
                as_json=as_json,
                profile=selected_profile,
                message=f"Unknown profile '{selected_profile}'. Available: {', '.join(config.models.keys())}",
            )
        profiles = [selected_profile]
    else:
        profiles = sorted(config.models.keys())

    secret_store = SecretStore(config.memory.root_path / ".thomas")
    local_providers = {"ollama", "local"}
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        model_cfg = config.models[profile]
        provider = str(model_cfg.provider or "").strip().lower()
        env_keys = _provider_env_keys(provider)
        env_present = [key for key in env_keys if str(os.environ.get(key) or "").strip()]
        has_config_key = bool(str(model_cfg.api_key or "").strip())
        has_secret = bool(secret_store.has(profile))
        auth_required = provider not in local_providers
        auth_ready = (not auth_required) or has_config_key or has_secret or bool(env_present)
        rows.append(
            {
                "profile": profile,
                "provider": provider,
                "auth_required": auth_required,
                "auth_ready": auth_ready,
                "sources": {
                    "config_api_key": has_config_key,
                    "secret_store": has_secret,
                    "secret_persisted": bool(secret_store.is_persisted(profile)),
                    "env": bool(env_present),
                },
                "env_keys": env_keys,
                "env_keys_present": env_present,
            }
        )

    payload = {
        "ok": True,
        "action": "auth",
        "profile_count": len(rows),
        "ready_count": sum(1 for row in rows if bool(row.get("auth_ready"))),
        "rows": rows,
        "secret_store_path": str(secret_store.storage_info.path),
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"profiles: {payload['profile_count']} (ready: {payload['ready_count']})")
    for row in rows:
        click.echo(
            f"  {row['profile']}: provider={row['provider']} "
            f"auth_ready={row['auth_ready']} required={row['auth_required']}"
        )


@models.command("fallbacks")
@click.option("--for-profile", "primary_profile", default="", help="Primary profile to compute effective chain for.")
@click.option("--set-profile", "set_profiles", multiple=True, help="Set ordered fallback profiles (repeatable).")
@click.option("--enable/--disable", "enabled", default=None, help="Toggle failover enabled.")
@click.option(
    "--chat-auto-failover/--no-chat-auto-failover",
    "chat_auto_failover",
    default=None,
    help="Toggle automatic chat failover.",
)
@click.option("--cooldown-seconds", type=int, default=None, help="Set runtime failover cooldown seconds.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_fallbacks(
    ctx: click.Context,
    primary_profile: str,
    set_profiles: tuple[str, ...],
    enabled: bool | None,
    chat_auto_failover: bool | None,
    cooldown_seconds: int | None,
    as_json: bool,
) -> None:
    """Inspect or update runtime failover profile chain."""
    config: AppConfig = ctx.obj["config"]
    primary = str(primary_profile or config.default_model).strip()
    if primary not in config.models:
        _runtime_model_error(
            as_json=as_json,
            profile=primary,
            message=f"Unknown profile '{primary}'. Available: {', '.join(config.models.keys())}",
        )

    if set_profiles:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in set_profiles:
            name = str(raw or "").strip()
            if not name:
                continue
            if name not in config.models:
                _runtime_model_error(
                    as_json=as_json,
                    profile=name,
                    message=f"Unknown fallback profile '{name}'. Available: {', '.join(config.models.keys())}",
                )
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        config.failover.profiles = ordered
    if enabled is not None:
        config.failover.enabled = bool(enabled)
    if chat_auto_failover is not None:
        config.failover.chat_auto_failover = bool(chat_auto_failover)
    if cooldown_seconds is not None:
        if int(cooldown_seconds) < 0:
            _runtime_model_error(as_json=as_json, message="cooldown_seconds must be >= 0")
        config.failover.cooldown_seconds = int(cooldown_seconds)

    chain = [cfg.name for cfg in config.failover_chain(primary)]
    payload = {
        "ok": True,
        "action": "fallbacks",
        "primary_profile": primary,
        "enabled": bool(config.failover.enabled),
        "chat_auto_failover": bool(config.failover.chat_auto_failover),
        "fallback_on_auth_error": bool(config.failover.fallback_on_auth_error),
        "cooldown_seconds": int(config.failover.cooldown_seconds),
        "configured_profiles": list(config.failover.profiles),
        "effective_chain": chain,
        "note": "Runtime-only updates (does not rewrite thomas.toml).",
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"primary: {payload['primary_profile']}")
    click.echo(f"enabled: {payload['enabled']}")
    click.echo(f"chat_auto_failover: {payload['chat_auto_failover']}")
    click.echo(f"configured_profiles: {', '.join(payload['configured_profiles']) or '(none)'}")
    click.echo(f"effective_chain: {', '.join(payload['effective_chain']) or '(none)'}")
    click.echo(payload["note"])


@models.command("image-fallbacks")
@click.option(
    "--for-profile", "primary_profile", default="", help="Primary profile to derive default image fallback chain."
)
@click.option("--set-profile", "set_profiles", multiple=True, help="Set ordered image fallback profiles (repeatable).")
@click.option("--clear", is_flag=True, help="Clear configured image fallback profiles.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_image_fallbacks(
    ctx: click.Context,
    primary_profile: str,
    set_profiles: tuple[str, ...],
    clear: bool,
    as_json: bool,
) -> None:
    """Inspect or update runtime image fallback profile chain."""
    config: AppConfig = ctx.obj["config"]
    state = _load_models_state(config)
    configured = [str(x).strip() for x in state.get("image_fallback_profiles", []) if str(x).strip()]
    changed = False

    if clear:
        configured = []
        changed = True
    if set_profiles:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in set_profiles:
            name = str(raw or "").strip()
            if not name:
                continue
            if name not in config.models:
                _runtime_model_error(
                    as_json=as_json,
                    profile=name,
                    message=f"Unknown image fallback profile '{name}'. Available: {', '.join(config.models.keys())}",
                )
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        configured = ordered
        changed = True

    if changed:
        state["image_fallback_profiles"] = configured
        _save_models_state(config, state)

    primary = str(primary_profile or config.default_model).strip()
    if primary not in config.models:
        _runtime_model_error(
            as_json=as_json,
            profile=primary,
            message=f"Unknown profile '{primary}'. Available: {', '.join(config.models.keys())}",
        )
    effective = list(configured) if configured else [cfg.name for cfg in config.failover_chain(primary)]

    payload = {
        "ok": True,
        "action": "image-fallbacks",
        "primary_profile": primary,
        "configured_profiles": configured,
        "effective_chain": effective,
        "source": "state" if configured else "derived_from_failover",
        "state_file": str(_models_state_path(config)),
        "note": "Runtime-only updates (does not rewrite thomas.toml).",
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False, indent=2)
        return
    click.echo(f"primary: {payload['primary_profile']}")
    click.echo(f"configured_profiles: {', '.join(payload['configured_profiles']) or '(none)'}")
    click.echo(f"effective_chain: {', '.join(payload['effective_chain']) or '(none)'}")
    click.echo(f"source: {payload['source']}")
    click.echo(payload["note"])


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
        click.echo('Install with: pip install -e ".[server]"', err=True)
        sys.exit(1)


@cli.command()
@click.option("-m", "--model", "model_name", help="Model profile to use")
@click.option(
    "--trace-files/--no-trace-files",
    default=None,
    help="Show files read by REPL on startup and each turn.",
)
@click.pass_context
def repl(ctx: click.Context, model_name: str | None, trace_files: bool | None) -> None:
    """Start the interactive REPL with rich terminal UI."""
    try:
        from thomas.cli.repl import ThomasREPL
    except ImportError as e:
        click.echo(f"REPL requires additional dependencies: {e}", err=True)
        click.echo("Install with: pip install prompt_toolkit>=3.0 rich>=13.0", err=True)
        sys.exit(1)

    config: AppConfig = ctx.obj["config"]
    try:
        from thomas.core.model_resolution import resolve_effective_model

        selected_model = _resolve_model_profile_name(config, model_name)
        if model_name and not selected_model:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)

        resolved_profile, resolved_model_id = resolve_effective_model(
            config,
            cli_profile=selected_model,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
        )
        if not resolved_profile:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        config.default_model = resolved_profile
        if resolved_model_id and resolved_profile in config.models:
            config.models[resolved_profile].model = resolved_model_id
    except Exception:
        resolved_profile = _resolve_model_profile_name(config, config.default_model)
        if not resolved_profile:
            click.echo("No valid model profile configured.", err=True)
            sys.exit(2)
        config.default_model = resolved_profile
    selected_model = config.default_model

    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    tools_registry = _build_tools(config)

    # Keep Windows REPL compatible with prompt_toolkit while allowing Codex
    # flows to spawn its subprocess bridge.
    if sys.platform == "win32":
        if _repl_needs_codex_event_loop(config, selected_model):
            policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        else:
            policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is not None:
            asyncio.set_event_loop_policy(policy_cls())

    if trace_files is None:
        trace_files = str(os.environ.get("THOMAS_REPL_TRACE_FILES", "1")).strip().lower() not in (
            "0",
            "false",
            "off",
            "no",
        )
    repl_instance = ThomasREPL(config, tools_registry, trace_file_reads=trace_files)
    asyncio.run(repl_instance.run())


@cli.command("onboarding-outcomes")
@click.option("--db", "db_path", type=click.Path(exists=False, dir_okay=False), default="", help="Runs DB path.")
@click.option("--days", "window_days", type=int, default=7, show_default=True, help="Lookback window in days.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def onboarding_outcomes_cmd(db_path: str, window_days: int, as_json: bool) -> None:
    """Generate onboarding outcome metrics from observability events."""
    from thomas.observability.onboarding_outcomes import (
        build_onboarding_outcome_report,
        get_outcomes_report,
    )

    days = max(1, int(window_days))
    if str(db_path or "").strip():
        report = build_onboarding_outcome_report(Path(str(db_path).strip()), since_days=days)
    else:
        report = get_outcomes_report(since_days=days)

    if as_json:
        _emit_json(report, ensure_ascii=False)
        return
    summary = dict(report.get("summary") or {})
    click.echo(f"events: {int(summary.get('events', 0) or 0)}")
    click.echo(f"wizard_opened: {int(summary.get('wizard_opened', 0) or 0)}")
    click.echo(f"onboarding_completed: {int(summary.get('onboarding_completed', 0) or 0)}")


@cli.group("release-contracts")
def release_contracts_group() -> None:
    """Release contract governance checks."""


@release_contracts_group.command("check")
@click.option("--registry", "registry_path", type=click.Path(exists=False, dir_okay=False), default="")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when checks fail.")
def release_contracts_check_cmd(registry_path: str, as_json: bool, strict: bool) -> None:
    """Validate the release contract registry."""
    from thomas.system.release_contracts import build_release_contract_report

    report = build_release_contract_report(Path(registry_path).resolve() if registry_path else None)
    if as_json:
        _emit_json(report, ensure_ascii=False)
    else:
        summary = dict(report.get("summary") or {})
        click.echo(f"ok: {bool(report.get('ok', False))}")
        click.echo(f"contract_count: {int(summary.get('contract_count', 0) or 0)}")
        click.echo(f"errors: {int(summary.get('error_count', 0) or 0)}")
        click.echo(f"warnings: {int(summary.get('warning_count', 0) or 0)}")
    if strict and not bool(report.get("ok", False)):
        raise SystemExit(2)


@cli.group("security")
def security_group() -> None:
    """Security governance checks."""


@security_group.command("audit")
@click.option("--repo-root", type=click.Path(exists=False, file_okay=False, dir_okay=True), default="")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when checks fail.")
def security_audit_cmd(repo_root: str, as_json: bool, strict: bool) -> None:
    """Run aggregated security audit checks."""
    from thomas.security.security_audit import run_security_audit

    resolved_root = Path(repo_root).expanduser().resolve() if str(repo_root or "").strip() else Path.cwd().resolve()
    report = run_security_audit(resolved_root, include_incident_drill=False)
    payload = {
        "ok": bool(report.get("ok", False)),
        "command": "security",
        "action": "audit",
        "repo_root": str(report.get("repo_root") or resolved_root),
        "summary": dict(report.get("summary") or {}),
        "checks": dict(report.get("checks") or {}),
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False)
    else:
        summary = payload["summary"]
        click.echo(f"ok: {payload['ok']}")
        click.echo(f"check_count: {int(summary.get('check_count', 0) or 0)}")
        click.echo(f"error_count: {int(summary.get('error_count', 0) or 0)}")
        click.echo(f"warning_count: {int(summary.get('warning_count', 0) or 0)}")
    if strict and not payload["ok"]:
        raise SystemExit(2)


# Public root app alias used by external loaders/tests.
app = cli


def main() -> None:
    cli(obj={})


for _module_name, _register_name in (
    ("thomas.cli.commands.channels", "register_channels_commands"),
    ("thomas.cli.commands.cron", "register_cron_commands"),
    ("thomas.cli.commands.research", "register_research_commands"),
    ("thomas.cli.commands.evolve", "register_evolve_commands"),
    ("thomas.cli.commands.sessions", "register_sessions_commands"),
    ("thomas.cli.commands.webhooks", "register_webhooks_commands"),
    ("thomas.cli.commands.companion", "register_companion_commands"),
    ("thomas.cli.commands.setup_wizard", "register_setup_commands"),
    ("thomas.cli.commands.quickstart", "register_quickstart_commands"),
    ("thomas.cli.commands.shortcuts", "register_shortcuts_commands"),
    ("thomas.cli.commands.updater", "register_update_commands"),
    ("thomas.cli.commands.release", "register_release_commands"),
):
    try:
        _mod = __import__(_module_name, fromlist=[_register_name])
        _register = getattr(_mod, _register_name, None)
        if callable(_register):
            _register(cli)
    except Exception as e:
        log.debug("Failed to register %s.%s: %s", _module_name, _register_name, e)


try:
    from thomas.cli.parity_commands import register_parity_commands

    register_parity_commands(cli)
except Exception as e:
    log.debug("Failed to register parity commands: %s", e)

try:
    from thomas.cli.quality_ops import register_quality_ops

    register_quality_ops(cli)
except Exception as e:
    log.debug("Failed to register quality ops commands: %s", e)


# --- Architecture tools ---
try:
    from thomas.cli.doctor import doctor_command

    cli.add_command(doctor_command)
except Exception as e:
    log.debug("Failed to register doctor command: %s", e)

try:
    from thomas.cli.why import why_command

    cli.add_command(why_command)
except Exception as e:
    log.debug("Failed to register why command: %s", e)

try:
    from thomas.cli.scaffold import scaffold_group

    cli.add_command(scaffold_group)
except Exception as e:
    log.debug("Failed to register scaffold command: %s", e)

try:
    from thomas.cli.generate_agent_docs import generate_agent_docs_command

    cli.add_command(generate_agent_docs_command)
except Exception as e:
    log.debug("Failed to register generate_agent_docs command: %s", e)

try:
    from thomas.cli.sweep import sweep_command

    cli.add_command(sweep_command)
except Exception as e:
    log.debug("Failed to register sweep command: %s", e)
