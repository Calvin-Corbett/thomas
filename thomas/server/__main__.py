"""Server-only entrypoint for Thomas web UI + HTTP API.

Run with:
  python -m thomas.server --host 127.0.0.1 --port 8899
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

from thomas.core.config import (
    apply_runtime_data_env_defaults,
    load_config,
    normalize_profile_name,
    resolve_thomas_data_dir,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Thomas web UI + HTTP API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", default=8899, type=int, help="Bind port")
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=None,
        help="Path to thomas.toml (default: THOMAS_CONFIG env var or ./thomas.toml)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Base runtime data dir (default: OS app data; Windows uses "
            "LOCALAPPDATA, e.g. C:\\Users\\<you>\\AppData\\Local\\Thomas)."
        ),
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Data profile name. Runtime state is stored under <data-dir>/<profile>/...",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Start fresh by deleting the selected profile dir before startup (requires --profile).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "One-command demo mode (stubbed no-key runtime, demo profile reset, "
            "safe local defaults). Ignores THOMAS_DATA_DIR/THOMAS_PROFILE unless "
            "--data-dir is provided."
        ),
    )
    return parser.parse_args(argv)


def _setup_logging(environment: str) -> None:
    """Configure logging based on environment."""
    log_level_env = os.environ.get("THOMAS_LOG_LEVEL", "").upper()

    if log_level_env:
        level = getattr(logging, log_level_env, logging.WARNING)
    elif environment == "production":
        level = logging.WARNING
    else:
        level = logging.INFO

    log_format_env = os.environ.get("THOMAS_LOG_FORMAT", "").lower()
    if log_format_env == "json" or (environment == "production" and log_format_env != "text"):
        fmt = '{"time":"%(asctime)s","name":"%(name)s","level":"%(levelname)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")

    log_file = str(os.environ.get("THOMAS_LOG_FILE") or "").strip()
    if not log_file:
        return

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        max_bytes = max(1024 * 1024, int(os.environ.get("THOMAS_LOG_MAX_BYTES", "10485760")))
    except Exception:
        max_bytes = 10_485_760
    try:
        backup_count = max(1, int(os.environ.get("THOMAS_LOG_BACKUP_COUNT", "7")))
    except Exception:
        backup_count = 7

    root = logging.getLogger()
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max(1024 * 1024, max_bytes),
        backupCount=max(1, backup_count),
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    root.addHandler(handler)


def _print_startup_banner(config, host: str, port: int) -> None:
    """Log environment, version, and config info on startup."""
    try:
        from thomas import __version__ as version
    except ImportError:
        version = "unknown"

    config_path = getattr(config, "config_path", "defaults")
    env = config.environment
    default_model = config.default_model
    model_count = len(config.models)

    logger = logging.getLogger("thomas.server")
    logger.info("=" * 60)
    logger.info("Thomas v%s starting", version)
    logger.info("  Environment : %s", env)
    logger.info("  Config      : %s", config_path)
    logger.info("  Bind        : %s:%d", host, port)
    logger.info("  Default model: %s (%d profile(s) loaded)", default_model, model_count)
    logger.info("  Shell access: %s", "enabled" if config.tools.allow_shell else "disabled")
    logger.info("  Access mode : %s", config.server.access_mode)

    # ── User space override check ──
    try:
        from thomas.core.user_space import check_conflicts, get_user_dir, list_overrides

        user_dir = get_user_dir()
        overrides = list_overrides()
        if overrides:
            logger.info("  User space  : %s (%d override(s))", user_dir, len(overrides))
            conflicts = check_conflicts()
            if conflicts:
                logger.warning("  ⚠ %d override conflict(s) detected! Run:", len(conflicts))
                logger.warning("    python scripts/thomas_update_check.py")
        else:
            logger.info("  User space  : %s (no overrides)", user_dir)
    except Exception:
        pass  # User space not set up — that's fine

    logger.info("=" * 60)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    if bool(args.demo):
        requested_profile = str(args.profile or "").strip()
        if requested_profile and requested_profile != "demo":
            print("--demo cannot be combined with --profile other than 'demo'.", file=sys.stderr)
            return 2

        os.environ.setdefault("THOMAS_NO_AUTO_UPDATE", "1")
        os.environ.setdefault("THOMAS_GATEWAY_RESPONSES_MODE", "stub")
        args.profile = "demo"
        args.reset = True

        if not args.data_dir:
            args.data_dir = str(
                resolve_thomas_data_dir(
                    None,
                    None,
                    env={"THOMAS_DATA_DIR": "", "THOMAS_PROFILE": ""},
                )
            )

    cfg_path = Path(args.config_path).expanduser() if args.config_path else None
    try:
        profile = normalize_profile_name(args.profile)
    except ValueError as exc:
        print(f"Invalid --profile: {exc}", file=sys.stderr)
        return 2
    if bool(args.reset) and not profile:
        print("--reset requires --profile <name>.", file=sys.stderr)
        return 2

    base_override = Path(args.data_dir).expanduser() if args.data_dir else None
    base_dir = resolve_thomas_data_dir(base_override, None)
    effective_dir = resolve_thomas_data_dir(base_override if base_override is not None else base_dir, profile)
    if bool(args.reset):
        if len(effective_dir.resolve().parts) < 3:
            print(f"Refusing to reset unsafe profile path: {effective_dir}", file=sys.stderr)
            return 2
        shutil.rmtree(effective_dir, ignore_errors=True)
    effective_dir.mkdir(parents=True, exist_ok=True)
    apply_runtime_data_env_defaults(base_dir=base_dir, effective_dir=effective_dir, profile=profile, overwrite=True)

    config = load_config(
        cfg_path,
        data_dir=Path(args.data_dir).expanduser() if args.data_dir else None,
        profile=profile or None,
    )

    _setup_logging(config.environment)
    _print_startup_banner(config, str(args.host), int(args.port))

    errors = config.validate()
    if errors:
        for err in errors:
            print(f"Config error: {err}", file=sys.stderr)
        return 1

    try:
        from thomas.server.app_lifecycle import serve

        serve(config, host=str(args.host), port=int(args.port))
    except ModuleNotFoundError as exc:
        print(f"Server dependencies missing: {exc}", file=sys.stderr)
        print('Install with: python -m pip install -e ".[server]"', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
