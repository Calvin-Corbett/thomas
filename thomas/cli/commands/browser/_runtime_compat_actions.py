"""Runtime implementations for browser compatibility commands."""

from __future__ import annotations

from thomas.cli.commands.browser._runtime_compat_shared import *  # noqa: F401,F403


def main_action_evaluate_script(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser action-evaluate-script"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("script", nargs="?", default="")
        parser.add_argument("--script", dest="script_opt", default="")
        parser.add_argument("--arg", dest="arg_json", default="")
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        script_text = (
            str(getattr(args, "script_opt", "") or "").strip() or str(getattr(args, "script", "") or "").strip()
        )
        if not script_text:
            _raise_invalid_input("A JavaScript expression is required (positional or --script).")

        handles = _resolve_handles_for_args(args)
        evaluate_fn = _require_method(
            handles.page,
            "evaluate",
            code="browser_page_evaluate_unsupported",
            message="Active page does not expose an evaluate() method.",
        )

        arg_raw = str(getattr(args, "arg_json", "") or "").strip()
        if arg_raw:
            arg_value = _parse_json_value(arg_raw, field_name="--arg")
            result = _call_maybe_async(evaluate_fn, script_text, arg_value)
        else:
            result = _call_maybe_async(evaluate_fn, script_text)

        return _build_session_success(
            command,
            handles,
            summary=f"Evaluated script in session '{handles.session_name}'.",
            result=_to_jsonable(result),
        )

    return _run_command(
        command=command,
        description="Evaluate JavaScript in the active browser page.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_context_set_user_agent(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser context-set-user-agent"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("user_agent")
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        user_agent = str(getattr(args, "user_agent", "") or "").strip()
        if not user_agent:
            _raise_invalid_input("user_agent cannot be empty.")

        handles = _resolve_handles_for_args(args)

        applied: list[str] = []
        set_headers = getattr(handles.context, "set_extra_http_headers", None)
        if callable(set_headers):
            _call_maybe_async(set_headers, {"User-Agent": user_agent})
            applied.append("set_extra_http_headers")

        add_init_script = getattr(handles.context, "add_init_script", None)
        if callable(add_init_script):
            script = (
                "Object.defineProperty(navigator, 'userAgent', " "{get: () => %s, configurable: true});"
            ) % json.dumps(user_agent)
            _call_maybe_async(add_init_script, script)
            applied.append("add_init_script")

        if not applied:
            raise BrowserCompatCommandError(
                code="browser_context_user_agent_unsupported",
                category="not_supported",
                message="Browser context does not support setting user-agent at runtime.",
                exit_code=4,
            )

        handles.session_state._thomas_user_agent = user_agent
        return _build_session_success(
            command,
            handles,
            summary=f"User-agent updated for session '{handles.session_name}'.",
            user_agent=user_agent,
            applied=applied,
        )

    return _run_command(
        command=command,
        description="Set user-agent overrides for the active browser context.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_context_set_viewport(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser context-set-viewport"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--width", type=int, required=True)
        parser.add_argument("--height", type=int, required=True)
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        width = int(getattr(args, "width", 0))
        height = int(getattr(args, "height", 0))
        if width <= 0 or height <= 0:
            _raise_invalid_input("width and height must be positive integers.")

        handles = _resolve_handles_for_args(args)
        set_viewport = _require_method(
            handles.page,
            "set_viewport_size",
            code="browser_page_viewport_unsupported",
            message="Active page does not support set_viewport_size().",
        )
        _call_maybe_async(set_viewport, {"width": width, "height": height})
        handles.session_state._thomas_viewport = {"width": width, "height": height}

        return _build_session_success(
            command,
            handles,
            summary=f"Viewport set to {width}x{height} for session '{handles.session_name}'.",
            viewport={"width": width, "height": height},
        )

    return _run_command(
        command=command,
        description="Set viewport size for the active browser page.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_context_set_geolocation(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser context-set-geolocation"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--lat", type=float, required=True)
        parser.add_argument("--lon", type=float, required=True)
        parser.add_argument("--accuracy", type=float, default=0.0)
        parser.add_argument("--origin", default="")
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        lat = float(getattr(args, "lat", 0.0))
        lon = float(getattr(args, "lon", 0.0))
        accuracy = float(getattr(args, "accuracy", 0.0))
        origin = str(getattr(args, "origin", "") or "").strip()

        if lat < -90.0 or lat > 90.0:
            _raise_invalid_input("--lat must be between -90 and 90.")
        if lon < -180.0 or lon > 180.0:
            _raise_invalid_input("--lon must be between -180 and 180.")
        if accuracy < 0.0:
            _raise_invalid_input("--accuracy must be non-negative.")

        handles = _resolve_handles_for_args(args)
        set_geolocation = _require_method(
            handles.context,
            "set_geolocation",
            code="browser_context_geolocation_unsupported",
            message="Browser context does not support set_geolocation().",
        )
        _call_maybe_async(
            set_geolocation,
            {
                "latitude": lat,
                "longitude": lon,
                "accuracy": accuracy,
            },
        )

        granted = False
        grant_permissions = getattr(handles.context, "grant_permissions", None)
        if callable(grant_permissions):
            if origin:
                _call_maybe_async(grant_permissions, ["geolocation"], origin=origin)
            else:
                _call_maybe_async(grant_permissions, ["geolocation"])
            granted = True

        handles.session_state._thomas_geolocation = {
            "latitude": lat,
            "longitude": lon,
            "accuracy": accuracy,
            "origin": origin,
        }

        return _build_session_success(
            command,
            handles,
            summary=f"Geolocation set for session '{handles.session_name}'.",
            geolocation={
                "latitude": lat,
                "longitude": lon,
                "accuracy": accuracy,
                "origin": origin,
                "permission_granted": granted,
            },
        )

    return _run_command(
        command=command,
        description="Set browser context geolocation and geolocation permission.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_network_set_offline(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser network-set-offline"

    def _configure(parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--offline", dest="offline", action="store_true")
        group.add_argument("--online", dest="offline", action="store_false")
        parser.set_defaults(offline=True)
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        offline = bool(getattr(args, "offline", True))
        handles = _resolve_handles_for_args(args)
        set_offline = _require_method(
            handles.context,
            "set_offline",
            code="browser_context_offline_unsupported",
            message="Browser context does not support set_offline().",
        )
        _call_maybe_async(set_offline, offline)
        handles.session_state._thomas_offline = offline

        return _build_session_success(
            command,
            handles,
            summary=(f"Network set to {'offline' if offline else 'online'} " f"for session '{handles.session_name}'."),
            offline=offline,
        )

    return _run_command(
        command=command,
        description="Toggle offline/online mode for the active browser context.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_network_emulate_conditions(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser network-emulate-conditions"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--profile",
            default="slow-4g",
            choices=["offline", "slow-3g", "fast-3g", "slow-4g", "wifi", "custom"],
        )
        parser.add_argument("--latency-ms", type=int, default=-1)
        parser.add_argument("--download-kbps", type=int, default=-1)
        parser.add_argument("--upload-kbps", type=int, default=-1)
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--offline", dest="offline_override", action="store_const", const=True)
        group.add_argument("--online", dest="offline_override", action="store_const", const=False)
        parser.set_defaults(offline_override=None)
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        profiles: dict[str, dict[str, int | bool]] = {
            "offline": {"offline": True, "latency_ms": 0, "download_kbps": 0, "upload_kbps": 0},
            "slow-3g": {"offline": False, "latency_ms": 400, "download_kbps": 400, "upload_kbps": 200},
            "fast-3g": {"offline": False, "latency_ms": 150, "download_kbps": 1600, "upload_kbps": 750},
            "slow-4g": {"offline": False, "latency_ms": 80, "download_kbps": 9000, "upload_kbps": 3000},
            "wifi": {"offline": False, "latency_ms": 30, "download_kbps": 30000, "upload_kbps": 15000},
            "custom": {"offline": False, "latency_ms": 0, "download_kbps": 0, "upload_kbps": 0},
        }

        profile = str(getattr(args, "profile", "custom") or "custom")
        selected = dict(profiles.get(profile, profiles["custom"]))

        latency_ms = int(getattr(args, "latency_ms", -1))
        download_kbps = int(getattr(args, "download_kbps", -1))
        upload_kbps = int(getattr(args, "upload_kbps", -1))
        if latency_ms >= 0:
            selected["latency_ms"] = latency_ms
        if download_kbps >= 0:
            selected["download_kbps"] = download_kbps
        if upload_kbps >= 0:
            selected["upload_kbps"] = upload_kbps

        override = getattr(args, "offline_override", None)
        if override is not None:
            selected["offline"] = bool(override)

        handles = _resolve_handles_for_args(args)

        set_offline = _require_method(
            handles.context,
            "set_offline",
            code="browser_context_offline_unsupported",
            message="Browser context does not support set_offline() required for network profile changes.",
        )
        _call_maybe_async(set_offline, bool(selected.get("offline", False)))

        profile_payload = {
            "profile": profile,
            "offline": bool(selected.get("offline", False)),
            "latency_ms": int(selected.get("latency_ms", 0)),
            "download_kbps": int(selected.get("download_kbps", 0)),
            "upload_kbps": int(selected.get("upload_kbps", 0)),
            "throttling_supported": False,
        }
        handles.session_state._thomas_network_profile = profile_payload

        return _build_session_success(
            command,
            handles,
            summary=f"Applied network profile '{profile}' to session '{handles.session_name}'.",
            network_profile=profile_payload,
        )

    return _run_command(
        command=command,
        description="Apply a browser network profile (offline toggle + persisted profile metadata).",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_permissions_grant(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser permissions-grant"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("permissions", nargs="+")
        parser.add_argument("--origin", default="")
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        permissions = sorted({str(x).strip() for x in (getattr(args, "permissions", []) or []) if str(x).strip()})
        if not permissions:
            _raise_invalid_input("At least one permission is required.")
        origin = str(getattr(args, "origin", "") or "").strip()

        handles = _resolve_handles_for_args(args)
        grant_permissions = _require_method(
            handles.context,
            "grant_permissions",
            code="browser_context_permissions_unsupported",
            message="Browser context does not support grant_permissions().",
        )
        if origin:
            _call_maybe_async(grant_permissions, permissions, origin=origin)
        else:
            _call_maybe_async(grant_permissions, permissions)

        target_origin = origin or "*"
        state = _permissions_get(handles.session_state)
        merged = sorted({*state.get(target_origin, []), *permissions})
        state[target_origin] = merged
        _permissions_set(handles.session_state, state)

        return _build_session_success(
            command,
            handles,
            summary=f"Granted {len(permissions)} permission(s) in session '{handles.session_name}'.",
            origin=target_origin,
            granted=permissions,
            tracked_permissions=state,
        )

    return _run_command(
        command=command,
        description="Grant browser permissions in the active context.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_permissions_revoke(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser permissions-revoke"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("permissions", nargs="*")
        parser.add_argument("--origin", default="")
        parser.add_argument("--all", dest="revoke_all", action="store_true", default=False)
        parser.add_argument("--session", dest="session_name", default="")

    def _execute(args: Any) -> dict[str, Any]:
        revoke_all = bool(getattr(args, "revoke_all", False))
        permissions = sorted({str(x).strip() for x in (getattr(args, "permissions", []) or []) if str(x).strip()})
        if not revoke_all and not permissions:
            _raise_invalid_input("Provide permission names or pass --all.")

        origin = str(getattr(args, "origin", "") or "").strip()
        target_origin = origin or "*"

        handles = _resolve_handles_for_args(args)
        clear_permissions = _require_method(
            handles.context,
            "clear_permissions",
            code="browser_context_permissions_unsupported",
            message="Browser context does not support clear_permissions().",
        )
        _call_maybe_async(clear_permissions)

        state = _permissions_get(handles.session_state)
        if revoke_all:
            state = {}
            revoked = ["*"]
        else:
            current = set(state.get(target_origin, []))
            revoked = sorted(set(permissions) & current)
            remaining = sorted(current - set(permissions))
            if remaining:
                state[target_origin] = remaining
            else:
                state.pop(target_origin, None)

        if state:
            grant_permissions = getattr(handles.context, "grant_permissions", None)
            if not callable(grant_permissions):
                raise BrowserCompatCommandError(
                    code="browser_context_permissions_unsupported",
                    category="not_supported",
                    message=(
                        "Browser context cleared permissions but cannot re-grant remaining permissions "
                        "(grant_permissions() missing)."
                    ),
                    exit_code=4,
                )
            for origin_key, values in state.items():
                if origin_key == "*":
                    _call_maybe_async(grant_permissions, values)
                else:
                    _call_maybe_async(grant_permissions, values, origin=origin_key)

        _permissions_set(handles.session_state, state)

        return _build_session_success(
            command,
            handles,
            summary=f"Revoked permissions in session '{handles.session_name}'.",
            origin=target_origin,
            revoked=revoked,
            tracked_permissions=state,
        )

    return _run_command(
        command=command,
        description="Revoke browser permissions (selective or all).",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


def main_artifact_har_export(argv: Optional[Sequence[str]] = None) -> int:
    command = "browser artifact-har-export"

    def _configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("out", nargs="?", default="")
        parser.add_argument("--out", dest="out_opt", default="")
        parser.add_argument("--session", dest="session_name", default="")
        parser.add_argument("--pretty", action="store_true", default=False)

    def _execute(args: Any) -> dict[str, Any]:
        out_path = _resolve_output_path(
            str(getattr(args, "out_opt", "") or "").strip() or str(getattr(args, "out", "") or "").strip(),
            default_name="browser_capture.har",
        )
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise BrowserCompatCommandError(
                code="browser_artifact_write_failed",
                category="external_failure",
                message=f"Unable to create output directory '{out_path.parent}': {exc}",
                exit_code=1,
            ) from exc

        handles = _resolve_handles_for_args(args)

        page_url = _extract_page_url(handles.page)
        page_title = _extract_page_title(handles.page)

        metadata = {
            "session": handles.session_name,
            "user_agent": getattr(handles.session_state, "_thomas_user_agent", ""),
            "viewport": _to_jsonable(getattr(handles.session_state, "_thomas_viewport", {})),
            "geolocation": _to_jsonable(getattr(handles.session_state, "_thomas_geolocation", {})),
            "network_profile": _to_jsonable(getattr(handles.session_state, "_thomas_network_profile", {})),
            "permissions": _permissions_get(handles.session_state),
        }

        now = _utc_iso()
        har_payload: dict[str, Any] = {
            "log": {
                "version": "1.2",
                "creator": {"name": "thomas.browser.compat", "version": "1"},
                "pages": [
                    {
                        "id": "page_1",
                        "startedDateTime": now,
                        "title": page_title or page_url or "thomas-browser-session",
                        "pageTimings": {},
                    }
                ],
                "entries": [],
            },
            "_thomas": metadata,
        }
        if page_url:
            har_payload["log"]["pages"][0]["title"] = page_title or page_url
            har_payload["_thomas"]["page_url"] = page_url

        indent = 2 if bool(getattr(args, "pretty", False)) else None
        try:
            out_path.write_text(
                json.dumps(har_payload, ensure_ascii=False, indent=indent),
                encoding="utf-8",
            )
        except Exception as exc:
            raise BrowserCompatCommandError(
                code="browser_artifact_write_failed",
                category="external_failure",
                message=f"Failed to write HAR artifact to '{out_path}': {exc}",
                exit_code=1,
            ) from exc

        return _build_session_success(
            command,
            handles,
            summary=f"HAR artifact exported to '{out_path}'.",
            artifact_path=str(out_path),
            bytes_written=int(out_path.stat().st_size),
            page_url=page_url,
            entries_count=int(len(har_payload["log"]["entries"])),
        )

    return _run_command(
        command=command,
        description="Export current browser session metadata as a HAR artifact.",
        argv=argv,
        configure=_configure,
        execute=_execute,
    )


__all__ = [
    "main_action_evaluate_script",
    "main_context_set_user_agent",
    "main_context_set_viewport",
    "main_context_set_geolocation",
    "main_network_set_offline",
    "main_network_emulate_conditions",
    "main_permissions_grant",
    "main_permissions_revoke",
    "main_artifact_har_export",
]
