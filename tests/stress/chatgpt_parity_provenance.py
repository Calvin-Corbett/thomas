"""Immutable provenance and runtime-attribution helpers for parity runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

from chatgpt_parity_probes import ProbeContext

from thomas.server.model_runtime_receipt import validate_model_runtime_receipt

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _evaluator_hashes() -> dict[str, str]:
    return {
        path.relative_to(_REPO_ROOT).as_posix(): _sha256_bytes(path.read_bytes())
        for path in sorted(_HERE.glob("chatgpt_parity*.py"))
    }


def _runtime_tree_sha256(repo_root: Path | None = None) -> str:
    root = repo_root or _REPO_ROOT
    digest = hashlib.sha256()
    runtime_suffixes = {
        ".cjs",
        ".css",
        ".html",
        ".js",
        ".jsx",
        ".mjs",
        ".py",
        ".scss",
        ".toml",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
    paths = sorted(
        path
        for path in (root / "thomas").rglob("*")
        if path.is_file() and path.suffix.lower() in runtime_suffixes and "__pycache__" not in path.parts
    )
    for optional in (root / "pyproject.toml", root / "thomas.toml"):
        if optional.is_file():
            paths.append(optional)
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _public_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an absolute HTTP(S) origin")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    return urllib.parse.urlunsplit((parsed.scheme, netloc, "", "", ""))


def _relevant_worktree_diff_sha(paths: list[str], rubric_path: Path) -> tuple[bool, str]:
    tracked_paths = [*paths, "thomas", "pyproject.toml", "thomas.toml"]
    if rubric_path.is_relative_to(_REPO_ROOT):
        tracked_paths.append(rubric_path.relative_to(_REPO_ROOT).as_posix())
    diff_result = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", *tracked_paths],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
    )
    status_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *tracked_paths],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
    )
    payload = status_result.stdout + b"\0" + diff_result.stdout
    return bool(status_result.stdout), _sha256_bytes(payload)


def _runtime_attribution(context: ProbeContext, *, profile: str, model_id: str) -> dict[str, Any]:
    receipts = context.runtime_cache.get("model_runtime_receipts", [])
    delegated_execution_ids = {
        str(value) for value in context.runtime_cache.get("delegated_execution_ids", []) if str(value).strip()
    }
    observed: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, receipt in enumerate(receipts if isinstance(receipts, list) else []):
        if not isinstance(receipt, dict):
            failures.append(f"receipt {index} is not an object")
            continue
        requested = receipt.get("requested") if isinstance(receipt.get("requested"), dict) else {}
        active = receipt.get("active") if isinstance(receipt.get("active"), dict) else {}
        observed.append(receipt)
        if (
            validate_model_runtime_receipt(
                receipt,
                requested_profile=profile,
                requested_model_id=model_id,
            )
            is None
        ):
            failures.append(f"receipt {index} is not a valid successful runtime receipt")
        if str(requested.get("profile") or "") != profile:
            failures.append(f"receipt {index} requested profile mismatch")
        if model_id and str(requested.get("model") or "") != model_id:
            failures.append(f"receipt {index} requested model mismatch")
        if str(active.get("profile") or "") != profile:
            failures.append(f"receipt {index} active profile mismatch")
        if model_id and str(active.get("model") or "") != model_id:
            failures.append(f"receipt {index} active model mismatch")
        if bool(receipt.get("failover_used")):
            failures.append(f"receipt {index} used failover")
        if str(receipt.get("trace_error") or ""):
            failures.append(f"receipt {index} trace unavailable: {receipt['trace_error']}")
    if not observed:
        failures.append("no model_runtime receipt was emitted by live chat")
    observed_delegations = {
        str(receipt.get("execution_id") or "") for receipt in observed if str(receipt.get("execution_id") or "")
    }
    missing_delegations = sorted(delegated_execution_ids - observed_delegations)
    if missing_delegations:
        failures.append("delegated model_runtime receipt missing for: " + ", ".join(missing_delegations))
    unique_observed = {
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")): receipt for receipt in observed
    }
    return {
        "status": "verified" if not failures else "unverified",
        "requested_profile": profile,
        "requested_model_id": model_id,
        "receipt_count": len(observed),
        "delegated_execution_count": len(delegated_execution_ids),
        "delegated_receipt_count": len(observed_delegations),
        "missing_delegated_execution_ids": missing_delegations,
        "observed": list(unique_observed.values()),
        "failures": failures,
    }


def _normalized_selected_rubric(rubric: dict[str, Any], selected: set[str]) -> dict[str, Any]:
    families = [family for family in rubric["families"] if not selected or family["id"] in selected]
    if not selected:
        return {**rubric, "families": families}
    selected_weight = sum(float(family["weight"]) for family in families)
    normalized = [{**family, "weight": float(family["weight"]) / selected_weight} for family in families]
    return {**rubric, "families": normalized}


def _build_provenance(
    *,
    args: argparse.Namespace,
    rubric_path: Path,
    selected: set[str],
    generated_at: str,
    runtime_attribution: dict[str, Any],
) -> dict[str, Any]:
    evaluator_hashes = _evaluator_hashes()
    dirty, diff_sha256 = _relevant_worktree_diff_sha(list(evaluator_hashes), rubric_path)
    provenance = {
        "schema_version": "thomas-chatgpt-parity-run-v1",
        "run_id": args.run_id,
        "generated_at": generated_at,
        "base_url": _public_base_url(args.base_url),
        "profile": args.profile,
        "model_id": args.model_id,
        "git_sha": _git_sha(),
        "relevant_worktree_dirty": dirty,
        "relevant_worktree_diff_sha256": diff_sha256,
        "rubric_sha256": _sha256_bytes(rubric_path.read_bytes()),
        "evaluator_sha256": evaluator_hashes,
        "runtime_tree_sha256": _runtime_tree_sha256(),
        "runtime_attribution": runtime_attribution,
        "tests_executed": bool(args.run_tests),
        "coverage": "targeted" if selected else "full",
        "selected_families": sorted(selected) if selected else ["all"],
    }
    provenance["provenance_id"] = _sha256_bytes(
        json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return provenance


__all__ = [
    "_build_provenance",
    "_normalized_selected_rubric",
    "_public_base_url",
    "_runtime_attribution",
    "_runtime_tree_sha256",
]
