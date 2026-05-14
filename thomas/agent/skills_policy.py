"""Trust and risk policy helpers for runtime skill selection."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

from thomas.skills import discover_native_skill_roots

_RISK_KEYWORDS = {
    "deploy",
    "deployment",
    "production",
    "prod",
    "rollback",
    "migration",
    "database",
    "drop",
    "destroy",
    "delete",
    "rm -rf",
    "credentials",
    "secret",
    "token",
    "billing",
    "payment",
    "auth",
    "security",
    "firewall",
    "dns",
    "infra",
    "infrastructure",
}


def _ordered_unique(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = str(item or "").strip()
        if not key:
            continue
        norm = key.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(key)
    return out


def _normalize_skill_name(value: str) -> str:
    return str(value or "").strip().lower()


def _is_enabled_env(name: str, default: bool = True) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return bool(default)
    return raw not in {"0", "false", "no", "off"}


def _path_prefix(child: Path, parent: Path) -> bool:
    try:
        c = child.resolve()
    except Exception:
        c = child
    try:
        p = parent.resolve()
    except Exception:
        p = parent
    child_key = str(c).lower()
    parent_key = str(p).lower().rstrip("\\/")
    if not parent_key:
        return False
    return child_key == parent_key or child_key.startswith(parent_key + os.sep)


def _memory_root_path(config: Any) -> Path:
    memory = getattr(config, "memory", None)
    root_path = getattr(memory, "root_path", None)
    if isinstance(root_path, Path):
        return root_path
    if root_path:
        return Path(str(root_path)).expanduser()
    root_text = getattr(memory, "root", None)
    if root_text:
        return Path(str(root_text)).expanduser()
    return (Path.cwd() / "runtime").resolve()



def _default_trusted_skill_roots(config: Any, *, cwd: Path | None = None) -> list[Path]:
    _ = config
    return [path for path, _origin in discover_native_skill_roots(cwd=cwd)]


@dataclass
class RuntimeSkillTrustPolicy:
    mode: str = "enforce"  # enforce | permissive | off
    require_hash: bool = False
    trusted_roots: list[Path] = field(default_factory=list)
    allow_skill_names: list[str] = field(default_factory=list)
    deny_skill_names: list[str] = field(default_factory=list)
    sha256_by_name: dict[str, str] = field(default_factory=dict)
    sha256_by_file: dict[str, str] = field(default_factory=dict)
    source_file: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "require_hash": bool(self.require_hash),
            "trusted_roots": [str(p) for p in self.trusted_roots],
            "allow_skill_names": list(self.allow_skill_names),
            "deny_skill_names": list(self.deny_skill_names),
            "source_file": str(self.source_file or ""),
        }


def _trust_policy_file(config: Any) -> Path:
    env_path = str(os.environ.get("THOMAS_RUNTIME_SKILLS_TRUST_FILE") or "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return _memory_root_path(config) / ".thomas" / "cli" / "skills_trust.json"


def load_runtime_skill_trust_policy(config: Any, *, cwd: Path | None = None) -> RuntimeSkillTrustPolicy:
    mode = str(os.environ.get("THOMAS_RUNTIME_SKILLS_TRUST_MODE") or "").strip().lower()
    if mode not in {"enforce", "permissive", "off"}:
        mode = "enforce"
    require_hash = _is_enabled_env("THOMAS_RUNTIME_SKILLS_REQUIRE_HASH", default=False)
    trusted_roots = list(_default_trusted_skill_roots(config, cwd=cwd))
    allow_skill_names: list[str] = []
    deny_skill_names: list[str] = []
    sha256_by_name: dict[str, str] = {}
    sha256_by_file: dict[str, str] = {}
    source_file = ""

    policy_path = _trust_policy_file(config)
    if policy_path.exists():
        try:
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            source_file = str(policy_path)
            mode_raw = str(raw.get("mode") or "").strip().lower()
            if mode_raw in {"enforce", "permissive", "off"}:
                mode = mode_raw
            if "require_hash" in raw:
                require_hash = bool(raw.get("require_hash"))

            roots_raw = raw.get("trusted_roots")
            if isinstance(roots_raw, list):
                for item in roots_raw:
                    path_text = str(item or "").strip()
                    if not path_text:
                        continue
                    p = Path(path_text).expanduser()
                    if p.exists() and p.is_dir():
                        trusted_roots.append(p)

            allow_raw = raw.get("allow_skill_names")
            if isinstance(allow_raw, list):
                for item in allow_raw:
                    norm = _normalize_skill_name(str(item or ""))
                    if norm:
                        allow_skill_names.append(norm)

            deny_raw = raw.get("deny_skill_names")
            if isinstance(deny_raw, list):
                for item in deny_raw:
                    norm = _normalize_skill_name(str(item or ""))
                    if norm:
                        deny_skill_names.append(norm)

            hashes_raw = raw.get("sha256")
            if isinstance(hashes_raw, dict):
                for key, value in hashes_raw.items():
                    digest = str(value or "").strip().lower()
                    if not re.fullmatch(r"[0-9a-f]{64}", digest):
                        continue
                    key_text = str(key or "").strip()
                    if not key_text:
                        continue
                    if key_text.lower().startswith("name:"):
                        sha256_by_name[_normalize_skill_name(key_text[5:])] = digest
                    elif key_text.lower().startswith("file:"):
                        file_key = str(Path(key_text[5:]).expanduser()).lower()
                        sha256_by_file[file_key] = digest
                    else:
                        sha256_by_name[_normalize_skill_name(key_text)] = digest

    trusted_unique: list[Path] = []
    seen_roots: set[str] = set()
    for root in trusted_roots:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        key = str(resolved).lower()
        if key in seen_roots:
            continue
        seen_roots.add(key)
        trusted_unique.append(resolved)

    return RuntimeSkillTrustPolicy(
        mode=mode,
        require_hash=bool(require_hash),
        trusted_roots=trusted_unique,
        allow_skill_names=_ordered_unique(allow_skill_names),
        deny_skill_names=_ordered_unique(deny_skill_names),
        sha256_by_name=dict(sha256_by_name),
        sha256_by_file=dict(sha256_by_file),
        source_file=source_file,
    )


def classify_skill_risk(name: str, description: str, excerpt: str) -> tuple[str, list[str]]:
    blob = "\n".join([str(name or ""), str(description or ""), str(excerpt or "")]).lower()
    tags: list[str] = []
    for token in sorted(_RISK_KEYWORDS):
        if token in blob:
            tags.append(token)
    if not tags:
        return "low", []
    return "high", tags


def is_globally_approved(prompt_text: str) -> bool:
    src = str(prompt_text or "").lower()
    return any(
        phrase in src
        for phrase in (
            "approve risky skills",
            "approved risky skills",
            "allow risky skills",
            "risky skills approved",
        )
    )


def has_skill_approval_phrase(prompt_text: str, skill_name: str) -> bool:
    src = str(prompt_text or "").lower()
    if not src:
        return False
    normalized = _normalize_skill_name(skill_name).replace("_", " ").replace("-", " ")
    escaped = re.escape(normalized)
    patterns = (
        rf"\bapprove\b[^\n]{{0,40}}\b{escaped}\b",
        rf"\ballow\b[^\n]{{0,40}}\b{escaped}\b",
        rf"\bauthorized?\b[^\n]{{0,40}}\b{escaped}\b",
    )
    return any(re.search(pat, src) for pat in patterns)


def evaluate_skill_trust(
    *,
    skill_name: str,
    skill_file: str,
    skill_sha256: str,
    policy: RuntimeSkillTrustPolicy,
) -> tuple[bool, str]:
    name_norm = _normalize_skill_name(skill_name)
    if name_norm in set(policy.deny_skill_names):
        return False, "deny_list"
    if policy.mode == "off":
        return True, "trust_off"
    if name_norm in set(policy.allow_skill_names):
        trusted = True
        reason = "allow_list"
    else:
        trusted = False
        reason = "untrusted_root"
        skill_file_path = Path(skill_file)
        for root in policy.trusted_roots:
            if _path_prefix(skill_file_path, root):
                trusted = True
                reason = "trusted_root"
                break
    if not trusted and policy.mode == "permissive":
        return True, "permissive_untrusted_root"

    if trusted and policy.require_hash:
        expected = ""
        file_key = str(Path(skill_file).expanduser()).lower()
        if file_key in policy.sha256_by_file:
            expected = str(policy.sha256_by_file[file_key]).lower()
        if not expected:
            expected = str(policy.sha256_by_name.get(name_norm, "")).lower()
        digest = str(skill_sha256 or "").lower()
        if not expected:
            return False, "missing_hash"
        if digest != expected:
            return False, "hash_mismatch"
        return True, "hash_match"

    return trusted, reason
