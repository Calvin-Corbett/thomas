"""Thomas runtime configuration validator."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from thomas.core.config import AppConfig, load_config

NO_KEY_PROVIDERS = {"", "local", "ollama", "codex"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
FALSE_ENV_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class ConfigFinding:
    level: str
    code: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }


def _is_local_url(raw_url: str) -> bool:
    text = str(raw_url or "").strip()
    if not text:
        return True
    try:
        parsed = urlparse(text)
    except (ValueError, TypeError):
        return False
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return False
    return host in LOCAL_HOSTS or host.endswith(".local")


def _provider_needs_key(provider: str, base_url: str) -> bool:
    p = str(provider or "").strip().lower()
    if p in NO_KEY_PROVIDERS:
        return False
    if _is_local_url(base_url):
        return False
    return True


def _parse_env_flag(name: str) -> tuple[bool | None, str | None]:
    raw = os.getenv(name)
    if raw is None:
        return None, None
    text = str(raw).strip().lower()
    if not text:
        return None, None
    if text in TRUE_ENV_VALUES:
        return True, None
    if text in FALSE_ENV_VALUES:
        return False, None
    return None, str(raw)


def _has_any_env_value(keys: Iterable[str]) -> bool:
    for key in keys:
        if str(os.getenv(key) or "").strip():
            return True
    return False


def _findings_from_config_validation(errors: Iterable[str]) -> list[ConfigFinding]:
    out: list[ConfigFinding] = []
    for err in errors:
        text = str(err or "").strip()
        if not text:
            continue
        out.append(
            ConfigFinding(
                level="error",
                code="config.validation",
                message=text,
                remediation="Fix the config value and rerun validator.",
            )
        )
    return out


def evaluate_config(
    config: AppConfig,
    *,
    secret_lookup: Callable[[str], str | None] | None = None,
) -> list[ConfigFinding]:
    findings: list[ConfigFinding] = []
    findings.extend(_findings_from_config_validation(config.validate()))

    mode = str(config.server.access_mode or "").strip().lower()
    if mode == "remote" and bool(config.server.allow_unauthenticated_version):
        findings.append(
            ConfigFinding(
                level="warning",
                code="server.remote.allow_unauthenticated_version",
                message="`server.allow_unauthenticated_version=true` in remote mode expands unauthenticated surface.",
                remediation="Set `server.allow_unauthenticated_version=false` for remote deployments.",
            )
        )

    webhook_signatures_flag, webhook_signatures_invalid = _parse_env_flag("THOMAS_WEBHOOK_REQUIRE_SIGNATURES")
    if webhook_signatures_invalid is not None:
        findings.append(
            ConfigFinding(
                level="warning",
                code="webhooks.require_signatures.invalid_env",
                message=(
                    f"Environment value `THOMAS_WEBHOOK_REQUIRE_SIGNATURES={webhook_signatures_invalid}` is invalid."
                ),
                remediation=(
                    "Use `THOMAS_WEBHOOK_REQUIRE_SIGNATURES=1` to require signatures or "
                    "`THOMAS_WEBHOOK_REQUIRE_SIGNATURES=0` for local-only development."
                ),
            )
        )

    webhook_signatures_enforced = (
        bool(webhook_signatures_flag) if webhook_signatures_flag is not None else mode == "remote"
    )
    if mode == "remote" and webhook_signatures_flag is False:
        findings.append(
            ConfigFinding(
                level="error",
                code="server.remote.webhook_signatures_disabled",
                message=(
                    "Remote mode is configured with `THOMAS_WEBHOOK_REQUIRE_SIGNATURES=0`, "
                    "which disables signature enforcement on public webhook receive routes."
                ),
                remediation=("Unset `THOMAS_WEBHOOK_REQUIRE_SIGNATURES` or set it to `1` before exposing remote mode."),
            )
        )

    if mode == "remote" and webhook_signatures_enforced:
        if not _has_any_env_value(("THOMAS_GITHUB_WEBHOOK_SECRET", "THOMAS_GITHUB_WEBHOOK_SECRETS")):
            findings.append(
                ConfigFinding(
                    level="warning",
                    code="webhooks.github.signature_secret_missing",
                    message=(
                        "Remote mode webhook signature enforcement is active but no GitHub webhook secret is configured."
                    ),
                    remediation=(
                        "Set `THOMAS_GITHUB_WEBHOOK_SECRET` (or `THOMAS_GITHUB_WEBHOOK_SECRETS`) "
                        "or keep `/webhooks/receive/github` inaccessible."
                    ),
                )
            )
        if not _has_any_env_value(("THOMAS_STRIPE_WEBHOOK_SECRET", "THOMAS_STRIPE_WEBHOOK_SECRETS")):
            findings.append(
                ConfigFinding(
                    level="warning",
                    code="webhooks.stripe.signature_secret_missing",
                    message=(
                        "Remote mode webhook signature enforcement is active but no Stripe webhook secret is configured."
                    ),
                    remediation=(
                        "Set `THOMAS_STRIPE_WEBHOOK_SECRET` (or `THOMAS_STRIPE_WEBHOOK_SECRETS`) "
                        "or keep `/webhooks/receive/stripe` inaccessible."
                    ),
                )
            )

    if bool(config.tools.allow_shell):
        findings.append(
            ConfigFinding(
                level="warning",
                code="tools.allow_shell",
                message="`tools.allow_shell=true` enables arbitrary command execution.",
                remediation="Disable shell tools unless there is a documented operational need.",
            )
        )

    if bool(config.failover.enabled) and len(config.models) < 2:
        findings.append(
            ConfigFinding(
                level="warning",
                code="failover.effective_profiles",
                message="Failover is enabled but only one model profile is configured.",
                remediation="Add at least one fallback profile or disable failover.",
            )
        )

    if secret_lookup is None:
        # Resolve server SecretStore lazily to avoid hard module-edge coupling.
        secret_store_module = import_module("thomas.server.secrets")
        secret_store_cls = secret_store_module.SecretStore
        secret_store = secret_store_cls(config.memory.root_path / ".thomas")
        secret_lookup = secret_store.get

    default_profile = str(config.default_model or "").strip()

    for name, model in config.models.items():
        provider = str(model.provider or "").strip().lower()
        base_url = str(model.base_url or "").strip()
        has_key = bool(str(model.api_key or "").strip() or secret_lookup(name))

        if _provider_needs_key(provider, base_url) and not has_key:
            is_default = name == default_profile
            findings.append(
                ConfigFinding(
                    level="error" if is_default else "warning",
                    code="models.default_profile_missing_key" if is_default else "models.profile_missing_key",
                    message=(
                        f"Profile '{name}' uses provider '{provider}' at non-local URL but has no API key configured."
                    ),
                    remediation=("Set a key via secrets/settings and re-run profile validation."),
                )
            )

        if base_url.startswith("http://") and not _is_local_url(base_url):
            findings.append(
                ConfigFinding(
                    level="warning",
                    code="models.insecure_remote_http",
                    message=f"Profile '{name}' uses insecure remote base URL '{base_url}'.",
                    remediation="Use HTTPS for non-local providers.",
                )
            )

    return findings


def build_report_for_config(
    cfg: AppConfig,
    *,
    config_path: Path | None = None,
    secret_lookup: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    findings = evaluate_config(cfg, secret_lookup=secret_lookup)
    errors = [item.to_dict() for item in findings if item.level == "error"]
    warnings = [item.to_dict() for item in findings if item.level == "warning"]
    return {
        "ok": len(errors) == 0,
        "config_path": str(config_path.resolve()) if config_path else str(Path("thomas.toml").resolve()),
        "default_model": str(cfg.default_model or ""),
        "model_profiles": sorted(str(k) for k in cfg.models.keys()),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
    }


def validate_config(config_path: Path | None = None) -> dict[str, Any]:
    cfg = load_config(config_path)
    return build_report_for_config(cfg, config_path=config_path)


def format_text_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Config: {report.get('config_path', '')}")
    lines.append(f"Default profile: {report.get('default_model', '')}")
    lines.append(f"Result: {'OK' if report.get('ok') else 'FAILED'}")

    errors = list(report.get("errors") or [])
    warnings = list(report.get("warnings") or [])

    if errors:
        lines.append("")
        lines.append("Errors:")
        for item in errors:
            lines.append(f"- [{item.get('code', 'unknown')}] {item.get('message', '')}")
            lines.append(f"  Fix: {item.get('remediation', '')}")

    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for item in warnings:
            lines.append(f"- [{item.get('code', 'unknown')}] {item.get('message', '')}")
            lines.append(f"  Fix: {item.get('remediation', '')}")

    if not errors and not warnings:
        lines.append("")
        lines.append("No issues detected.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Thomas runtime configuration and emit support-grade diagnostics."
    )
    parser.add_argument("--config", dest="config", default=None, help="Path to thomas.toml (optional).")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    config_path = Path(args.config).resolve() if args.config else None
    report = validate_config(config_path)

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text_report(report))

    return 0 if bool(report.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
