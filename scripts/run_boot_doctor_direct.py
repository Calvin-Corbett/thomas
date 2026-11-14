"""Direct Boot Doctor report runner.

Used as a fallback when regular CLI dispatch is broken.
"""

from __future__ import annotations

import argparse
import traceback
from datetime import datetime, timezone
from pathlib import Path

from thomas.bootdoctor.collaborators import stored_api_key, windows_authorize
from thomas.core.boot_checks import config_file_path
from thomas.core.boot_doctor import run_boot_doctor
from thomas.core.config import AppConfig, load_config


def _fallback_report_path(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return (root / "runtime" / "boot_doctor" / f"boot_doctor_{stamp}.txt").resolve()


def _write_failure_report(path: Path, *, reason: str, port: int, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "\n".join(
            [
                "Thomas Boot Doctor Report (Direct Fallback)",
                f"Generated (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                f"Reason: {reason}",
                f"Port: {int(port)}",
                "",
                f"Failure: {type(exc).__name__}: {exc}",
                "",
                "Traceback:",
                traceback.format_exc().rstrip(),
                "",
                "Offline Recovery Steps:",
                f"- Run `run-ui.cmd -NoTray -Port {int(port)}`.",
                f"- Re-run `python scripts/run_boot_doctor_direct.py --port {int(port)}`.",
            ]
        ).rstrip()
        + "\n"
    )
    path.write_text(text, encoding="utf-8")


def _load_config_safe(config_path: str) -> tuple[AppConfig, str]:
    given = str(config_path or "").strip()
    try:
        return load_config(Path(given).expanduser().resolve() if given else None), ""
    except Exception as exc:
        # The same file Boot Doctor's offline check reads, so the warning and the report name one file.
        where = config_file_path(Path.cwd(), given)
        return AppConfig(), f"config load failed for {where} ({type(exc).__name__}: {exc}); using defaults"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Boot Doctor directly without thomas CLI dispatch.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--port", type=int, default=8899, help="Port to diagnose.")
    parser.add_argument("--reason", default="startup failure", help="Reason included in report.")
    parser.add_argument("--report", default="", help="Optional report path.")
    parser.add_argument("--config", default="", help="Optional config path.")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI summary in report.")
    parser.add_argument("--no-auto-repair", action="store_true", help="Disable automatic repair attempts.")
    parser.add_argument("--relaunch", action="store_true", help="Leave a recovered Thomas server running after repair.")
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root = root.resolve()

    report_path = None
    if str(args.report or "").strip():
        report_path = Path(args.report).expanduser()
        if not report_path.is_absolute():
            report_path = root / report_path
        report_path = report_path.resolve()

    config, warning = _load_config_safe(args.config)
    if warning:
        print(f"[bootdoctor-direct] warning: {warning}")

    try:
        out = run_boot_doctor(
            config=config,
            root=root,
            port=int(args.port),
            reason=str(args.reason or "").strip() or "startup failure",
            report_path=report_path,
            auto_repair=not bool(args.no_auto_repair),
            allow_ai=not bool(args.no_ai),
            relaunch=bool(args.relaunch),
            # The file the runner loaded is the one the offline check must test.
            config_path=Path(args.config).expanduser() if str(args.config or "").strip() else None,
            authorize=windows_authorize,
            secret_lookup=stored_api_key,
        )
        print(out)
        return 0
    except Exception as exc:
        target = report_path or _fallback_report_path(root)
        _write_failure_report(
            target,
            reason=str(args.reason or "").strip() or "startup failure",
            port=int(args.port),
            exc=exc,
        )
        print(target)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
