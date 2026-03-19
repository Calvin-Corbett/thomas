#!/usr/bin/env python3
"""Guard canonical Thomas repository identity (remote slug + local root)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = "docs/ops/repo_identity_policy.json"
ENV_CANONICAL_ROOT = "THOMAS_CANONICAL_REPO_ROOT"
REPO_ROOT_TOKENS = {"<repo_root>", "${repo_root}", "%repo_root%", "{repo_root}", "$repo_root"}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _norm_slug(value: str) -> str:
    slug = _norm(value).strip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    return slug


def _norm_path(value: str | Path) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    while "//" in raw:
        raw = raw.replace("//", "/")
    return raw.rstrip("/").lower()


def _resolve_local_root(value: str | Path, repo_root: Path) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered in REPO_ROOT_TOKENS:
        return _norm_path(repo_root)
    return raw


def _extract_slug_from_remote(url: str) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", normalized)
    if not match:
        return None
    owner = _norm(match.group(1))
    repo = _norm(match.group(2))
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def _run_git(repo_root: Path, args: Sequence[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return str(proc.stdout or "").strip()


def _git_repo_root(path_hint: Path) -> Path:
    out = _run_git(path_hint, ["rev-parse", "--show-toplevel"])
    if not out:
        raise RuntimeError("unable to resolve git repo root")
    return Path(out).resolve()


def _git_remote_urls(repo_root: Path, *, allowed_remote_names: Sequence[str]) -> dict[str, str]:
    remotes_raw = _run_git(repo_root, ["remote"])
    remotes = [name.strip() for name in remotes_raw.splitlines() if name.strip()]
    allowed = {_norm(name) for name in allowed_remote_names if str(name or "").strip()}
    if allowed:
        remotes = [name for name in remotes if _norm(name) in allowed]
    out: dict[str, str] = {}
    for name in remotes:
        url = _run_git(repo_root, ["remote", "get-url", name])
        if url:
            out[name] = url
    return out


def _is_truthy_env(name: str) -> bool:
    return _norm(os.getenv(name, "")) in {"1", "true", "yes", "on", "y"}


def _load_policy(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing policy file: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("repo identity policy must be a JSON object")
    return raw


def evaluate_identity(
    *,
    repo_root: Path,
    remote_urls: dict[str, str],
    canonical_slug: str,
    canonical_roots: Sequence[str],
    enforce_local_root: bool,
) -> dict[str, Any]:
    violations: list[str] = []
    expected_slug = _norm_slug(canonical_slug)

    remote_slugs: dict[str, str] = {}
    for name, url in remote_urls.items():
        parsed = _extract_slug_from_remote(url)
        if parsed:
            remote_slugs[name] = parsed

    if not expected_slug:
        violations.append("canonical repo slug is required")
    elif expected_slug not in {_norm_slug(item) for item in remote_slugs.values()}:
        discovered = ", ".join(sorted({value for value in remote_slugs.values()})) or "none"
        violations.append(
            f"remote slug mismatch: expected `{expected_slug}` but discovered `{discovered}` "
            f"(set by policy {DEFAULT_POLICY_PATH})"
        )

    normalized_repo_root = _norm_path(repo_root)
    normalized_roots = sorted({_norm_path(item) for item in canonical_roots if _norm_path(item)})
    if enforce_local_root and normalized_roots and normalized_repo_root not in normalized_roots:
        allowed = ", ".join(normalized_roots)
        violations.append(
            f"repo root drift detected: current `{normalized_repo_root}` not in canonical roots [{allowed}]"
        )

    return {
        "ok": not violations,
        "expected_slug": expected_slug,
        "remote_urls": remote_urls,
        "remote_slugs": remote_slugs,
        "repo_root": str(repo_root),
        "canonical_roots": normalized_roots,
        "enforce_local_root": bool(enforce_local_root),
        "violations": violations,
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when current clone drifts from canonical Thomas repo identity.")
    parser.add_argument("--repo-root", default=str(ROOT), help="Path inside the repository (default: script root).")
    parser.add_argument(
        "--policy",
        default=DEFAULT_POLICY_PATH,
        help=f"Repo identity policy JSON path (default: {DEFAULT_POLICY_PATH}).",
    )
    parser.add_argument("--expected-slug", default="", help="Canonical repo slug override, for example `corbe/thomas`.")
    parser.add_argument(
        "--canonical-root",
        action="append",
        default=[],
        help="Canonical local root override (repeatable).",
    )
    parser.add_argument(
        "--enforce-local-root",
        dest="enforce_local_root",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enforce canonical local root paths (default: policy-driven, disabled automatically in CI).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    policy_path = Path(args.policy).expanduser()
    if not policy_path.is_absolute():
        policy_path = (ROOT / policy_path).resolve()

    path_hint = Path(args.repo_root).expanduser()
    if not path_hint.is_absolute():
        path_hint = (ROOT / path_hint).resolve()

    gate_name = "repo_identity"
    try:
        policy = _load_policy(policy_path)
        repo_root = _git_repo_root(path_hint)

        policy_slug = str(policy.get("canonical_repo_slug") or "").strip()
        expected_slug = str(args.expected_slug or "").strip() or policy_slug

        policy_roots = [
            _resolve_local_root(item, repo_root)
            for item in list(policy.get("canonical_local_roots") or [])
            if str(item).strip()
        ]
        canonical_roots = [str(item) for item in list(args.canonical_root or []) if str(item).strip()] or policy_roots
        env_root_override = str(os.getenv(ENV_CANONICAL_ROOT, "")).strip()
        if env_root_override:
            canonical_roots = [env_root_override]

        enforce_default = bool(policy.get("enforce_local_root_when_not_ci", True))
        if args.enforce_local_root is None:
            enforce_local_root = enforce_default and not _is_truthy_env("CI")
        else:
            enforce_local_root = bool(args.enforce_local_root)

        allowed_remote_names = [str(item) for item in list(policy.get("allowed_remote_names") or []) if str(item)]
        remote_urls = _git_remote_urls(repo_root, allowed_remote_names=allowed_remote_names)
        result = evaluate_identity(
            repo_root=repo_root,
            remote_urls=remote_urls,
            canonical_slug=expected_slug,
            canonical_roots=canonical_roots,
            enforce_local_root=enforce_local_root,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "gate": gate_name,
            "error": f"repo identity gate failed: {exc}",
            "policy_path": str(policy_path),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Repo identity gate: FAIL")
            print(f"- {payload['error']}")
        return 1

    payload = dict(result)
    payload.update({"gate": gate_name, "policy_path": str(policy_path)})

    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["ok"] else 1

    if payload["ok"]:
        print("Repo identity gate: PASS")
        print(f"- repo root: {payload['repo_root']}")
        print(f"- expected slug: {payload.get('expected_slug')}")
        return 0

    print("Repo identity gate: FAIL")
    for item in payload.get("violations", []):
        print(f"- {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
