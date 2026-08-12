#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

DEFAULT_BLOCKLIST = ["reference_cli", "clawbot"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _intake_root(repo: Path, root_arg: str) -> Path:
    if root_arg:
        return Path(root_arg).expanduser().resolve()
    return repo / "code_intake"


def _ensure_layout(root: Path) -> None:
    dirs = [
        root / "queue" / "incoming",
        root / "queue" / "staged",
        root / "queue" / "applied",
        root / "queue" / "rejected",
        root / "reports",
        root / "templates",
        root / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        keep = d / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _domain_allowed_paths(domain: str) -> list[str]:
    shared = ["tests/prompt_pack", "docs/reference_cli_gap_runs"]
    mapping = {
        "browser": ["thomas/cli/commands/browser", "thomas/browser", *shared],
        "nodes": ["thomas/cli/commands/nodes", "thomas/nodes", "thomas/server/routes/gateway", *shared],
        "messages": ["thomas/cli/commands/messages", "thomas/messages", "thomas/cli/parity_compat.py", *shared],
        "channels": [
            "thomas/cli/commands/channel_ops",
            "thomas/channels",
            "thomas/cli/commands/channels.py",
            "thomas/integrations",
            *shared,
        ],
        "plugins": ["thomas/cli/commands/plugins", "thomas/plugins", "thomas/agent", *shared],
        "gateway": ["thomas/cli/commands/gateway", "thomas/server/routes/gateway", "thomas/server/routes", *shared],
        "memory": ["thomas/cli/commands/memory", "thomas/memory", *shared],
        "security": ["thomas/cli/commands/security", "thomas/security", "thomas/policy", *shared],
        "system": ["thomas/cli/commands/system", "thomas/system", "thomas/core", "thomas/server/routes", *shared],
        "approvals": ["thomas/cli/commands/approvals", "thomas/approvals", "thomas/autonomy", "thomas/memory", *shared],
        "hardening": ["scripts", "tests", "docs", *shared],
    }
    return mapping.get(domain, ["thomas", "tests", "docs"])


def _domain_tests(domain: str) -> list[str]:
    mapping = {
        "browser": ['python -m pytest -q tests/test_cli_parity_commands.py -k "browser"'],
        "nodes": ['python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"'],
        "messages": ['python -m pytest -q tests/test_cli_parity_commands.py -k "message"'],
        "channels": ['python -m pytest -q tests/test_cli_parity_commands.py -k "channels"'],
        "plugins": ['python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"'],
        "gateway": ["python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py"],
        "memory": ["python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py"],
        "security": ["python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py"],
        "system": [
            "python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py"
        ],
        "approvals": ['python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"'],
        "hardening": ["python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py"],
    }
    return mapping.get(domain, ["python -m pytest -q"])


def _drop_id(date_tag: str, batch_id: str, prompt_id: str) -> str:
    return f"D{date_tag}_{batch_id}_{prompt_id}"


def _load_rows(index_path: Path, batch_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with index_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if str(row.get("batch", "")).strip() != batch_id:
                continue
            rows.append(
                {
                    "prompt_id": str(row.get("prompt_id", "")).strip(),
                    "batch": str(row.get("batch", "")).strip(),
                    "lane": str(row.get("lane", "")).strip(),
                    "domain": str(row.get("domain", "")).strip(),
                    "title": str(row.get("title", "")).strip(),
                }
            )
    rows.sort(key=lambda r: r["prompt_id"])
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _manifest(row: dict[str, str], drop_id: str, source: str, strict_name_guard: bool) -> dict[str, Any]:
    domain = row["domain"]
    return {
        "schema_version": 1,
        "drop_id": drop_id,
        "prompt_id": row["prompt_id"],
        "batch_id": row["batch"],
        "title": row["title"],
        "artifact": {
            "type": "unified_diff",
            "path": "change.diff",
            "sha256": "",
        },
        "ownership": {
            "allowed_paths": _domain_allowed_paths(domain),
            "forbidden_paths": [],
        },
        "policy": {
            "strict_name_guard": strict_name_guard,
            "name_guard_blocklist": DEFAULT_BLOCKLIST,
        },
        "tests": {
            "commands": _domain_tests(domain),
        },
        "meta": {
            "source": source,
            "created_at": _now_iso(),
            "notes": f"Lane={row['lane']}; Domain={domain}",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed incoming code-intake drops from the 216 prompt batch index.")
    ap.add_argument("--root", default="", help="Override intake root (default: <repo>/code_intake)")
    ap.add_argument(
        "--index",
        default="docs/REFERENCE_CLI_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv",
        help="Prompt batch CSV index path (repo-relative or absolute)",
    )
    ap.add_argument("--batch-id", required=True, help="Batch id such as B01 .. B27")
    ap.add_argument("--date-tag", default="", help="Date tag in drop id (default: UTC YYYYMMDD)")
    ap.add_argument("--source", default="chatgpt_tab")
    ap.add_argument("--strict-name-guard", action="store_true", default=True)
    ap.add_argument("--no-strict-name-guard", dest="strict_name_guard", action="store_false")
    ap.add_argument("--limit", type=int, default=0, help="Optional max prompts to seed from the batch")
    ap.add_argument("--force", action="store_true", help="Overwrite existing incoming drops with same IDs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = _repo_root()
    root = _intake_root(repo, args.root)

    index_path = Path(args.index)
    if not index_path.is_absolute():
        index_path = (repo / index_path).resolve()
    if not index_path.exists():
        print(f"error: index not found: {index_path}")
        return 2

    batch_id = args.batch_id.strip().upper()
    if not batch_id.startswith("B"):
        print("error: --batch-id should look like B01")
        return 2

    rows = _load_rows(index_path, batch_id)
    if not rows:
        print(f"error: no rows found for batch {batch_id} in {index_path}")
        return 2
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    if not args.dry_run:
        _ensure_layout(root)

    date_tag = args.date_tag.strip() or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    incoming = root / "queue" / "incoming"

    created = 0
    skipped = 0
    for row in rows:
        did = _drop_id(date_tag, row["batch"], row["prompt_id"])
        drop_dir = incoming / did
        if drop_dir.exists():
            if args.force:
                if not args.dry_run:
                    for p in drop_dir.glob("*"):
                        if p.is_file():
                            p.unlink()
                        else:
                            # safety: drop dirs are generated with files only
                            pass
            else:
                print(f"skip exists: {did}")
                skipped += 1
                continue

        if not args.dry_run:
            drop_dir.mkdir(parents=True, exist_ok=True)
            mf = _manifest(row, did, source=args.source, strict_name_guard=bool(args.strict_name_guard))
            _write_json(drop_dir / "manifest.json", mf)
            (drop_dir / "change.diff").write_text("# paste unified diff here\n", encoding="utf-8")
        created += 1
        print(f"seeded: {did} ({row['prompt_id']} - {row['title']})")

    print(f"batch: {batch_id}")
    print(f"created: {created}")
    print(f"skipped: {skipped}")
    print(f"incoming_dir: {incoming}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
