#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

QUEUE_NAMES = ("incoming", "staged", "applied", "rejected")
DEFAULT_BLOCKLIST = ["openclaw", "clawbot"]
ARTIFACT_TYPES = {"unified_diff", "feature_pack", "file_bundle"}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _intake_root(repo: Path, root_arg: Optional[str]) -> Path:
    if root_arg:
        return Path(root_arg).expanduser().resolve()
    return repo / "code_intake"


def _queue_dir(root: Path, queue: str) -> Path:
    return root / "queue" / queue


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_rel_path(raw: str) -> str:
    return raw.replace("\\", "/").strip()


def _safe_repo_rel(path_str: str) -> bool:
    path = PurePosixPath(_norm_rel_path(path_str))
    if path.is_absolute():
        return False
    if not path.parts:
        return False
    if any(part == ".." for part in path.parts):
        return False
    return True


def parse_diff_touched_paths(diff_text: str) -> set[str]:
    touched: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            rel = line[len("+++ b/") :].split("\t", 1)[0].strip()
            if rel and rel != "/dev/null":
                touched.add(_norm_rel_path(rel))
            continue
        if line.startswith("+++ "):
            rel = line[len("+++ ") :].split("\t", 1)[0].strip()
            if rel and rel != "/dev/null":
                touched.add(_norm_rel_path(rel))
    return touched


def parse_diff_added_lines(diff_text: str) -> list[str]:
    out: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        if line.startswith("+++"):
            continue
        out.append(line[1:])
    return out


def detect_blocked_tokens(lines: Iterable[str], tokens: Iterable[str]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    token_list = [t.strip().lower() for t in tokens if t and t.strip()]
    for raw in lines:
        lower = raw.lower()
        for token in token_list:
            if token and token in lower:
                hits.append({"token": token, "line": raw[:500]})
    return hits


def _matches_prefix(path: str, prefixes: Iterable[str]) -> bool:
    p = _norm_rel_path(path)
    for pref in prefixes:
        pre = _norm_rel_path(pref).rstrip("/")
        if not pre:
            continue
        if p == pre or p.startswith(pre + "/"):
            return True
    return False


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

    template = root / "templates" / "drop_manifest.template.json"
    if not template.exists():
        _write_json(template, _default_manifest_template())


def _default_manifest_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "drop_id": "D2026XXXX_001",
        "prompt_id": "P001",
        "batch_id": "B01",
        "title": "short title",
        "artifact": {
            "type": "unified_diff",
            "path": "change.diff",
            "sha256": "",
        },
        "ownership": {
            "allowed_paths": [
                "thomas/cli/commands",
                "tests",
                "docs",
            ],
            "forbidden_paths": [],
        },
        "policy": {
            "strict_name_guard": True,
            "name_guard_blocklist": DEFAULT_BLOCKLIST,
        },
        "tests": {
            "commands": [],
        },
        "meta": {
            "source": "chatgpt_tab",
            "created_at": _now_iso(),
            "notes": "",
        },
    }


def _find_drop(root: Path, drop_id: str, queue_hint: Optional[str] = None) -> tuple[str, Path]:
    if queue_hint:
        p = _queue_dir(root, queue_hint) / drop_id
        if p.exists():
            return queue_hint, p
        raise FileNotFoundError(f"drop {drop_id} not found in queue '{queue_hint}'")
    for queue in QUEUE_NAMES:
        p = _queue_dir(root, queue) / drop_id
        if p.exists():
            return queue, p
    raise FileNotFoundError(f"drop {drop_id} not found in queues: {', '.join(QUEUE_NAMES)}")


def _validate_manifest(manifest_path: Path, repo: Path, run_git_apply_check: bool = True) -> dict[str, Any]:
    payload = _read_json(manifest_path)
    drop_dir = manifest_path.parent
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    touched_paths: list[str] = []
    blocked: list[dict[str, str]] = []

    drop_id = str(payload.get("drop_id") or "").strip()
    if not drop_id:
        errors.append({"code": "missing_drop_id", "message": "manifest.drop_id is required"})

    artifact = payload.get("artifact") or {}
    art_type = str(artifact.get("type") or "").strip()
    art_rel = _norm_rel_path(str(artifact.get("path") or "").strip())
    if art_type not in ARTIFACT_TYPES:
        errors.append(
            {
                "code": "invalid_artifact_type",
                "message": f"artifact.type must be one of {sorted(ARTIFACT_TYPES)}",
            }
        )
    if not art_rel:
        errors.append({"code": "missing_artifact_path", "message": "artifact.path is required"})
    elif not _safe_repo_rel(art_rel):
        errors.append({"code": "unsafe_artifact_path", "message": f"artifact.path is unsafe: {art_rel}"})

    artifact_path = drop_dir / art_rel if art_rel else None
    if artifact_path and not artifact_path.exists():
        errors.append({"code": "artifact_missing", "message": f"artifact not found: {artifact_path}"})

    if artifact_path and artifact_path.is_file():
        actual_sha = _sha256_file(artifact_path)
    else:
        actual_sha = ""

    expected_sha = str(artifact.get("sha256") or "").strip().lower()
    if expected_sha and artifact_path and artifact_path.is_file():
        if expected_sha != actual_sha:
            errors.append(
                {
                    "code": "artifact_sha_mismatch",
                    "message": f"artifact sha256 mismatch: expected {expected_sha}, got {actual_sha}",
                }
            )

    ownership = payload.get("ownership") or {}
    allowed = [_norm_rel_path(str(x)) for x in (ownership.get("allowed_paths") or []) if str(x).strip()]
    forbidden = [_norm_rel_path(str(x)) for x in (ownership.get("forbidden_paths") or []) if str(x).strip()]

    policy = payload.get("policy") or {}
    strict_name_guard = bool(policy.get("strict_name_guard", True))
    blocklist = policy.get("name_guard_blocklist") or DEFAULT_BLOCKLIST
    blocklist = [str(x).strip() for x in blocklist if str(x).strip()]

    git_check = {"ran": False, "returncode": 0, "stdout": "", "stderr": ""}

    if artifact_path and artifact_path.exists() and art_type == "unified_diff":
        if artifact_path.is_dir():
            errors.append({"code": "diff_is_directory", "message": "unified_diff artifact must be a file"})
        else:
            diff_text = artifact_path.read_text(encoding="utf-8", errors="replace")
            touched_paths = sorted(parse_diff_touched_paths(diff_text))

            if not touched_paths:
                warnings.append({"code": "no_touched_paths", "message": "no touched paths parsed from diff"})

            for rel in touched_paths:
                if not _safe_repo_rel(rel):
                    errors.append({"code": "unsafe_touched_path", "message": f"unsafe touched path: {rel}"})
                if allowed and not _matches_prefix(rel, allowed):
                    errors.append(
                        {
                            "code": "path_outside_allowed",
                            "message": f"path outside allowed_paths: {rel}",
                        }
                    )
                if forbidden and _matches_prefix(rel, forbidden):
                    errors.append(
                        {
                            "code": "path_in_forbidden",
                            "message": f"path inside forbidden_paths: {rel}",
                        }
                    )

            blocked = detect_blocked_tokens(parse_diff_added_lines(diff_text), blocklist)
            if blocked:
                msg = f"blocked naming tokens detected in added lines ({len(blocked)} hit(s))"
                if strict_name_guard:
                    errors.append({"code": "name_guard_violation", "message": msg})
                else:
                    warnings.append({"code": "name_guard_warning", "message": msg})

            if run_git_apply_check and not errors:
                cmd = [
                    "git",
                    "-C",
                    str(repo),
                    "apply",
                    "--check",
                    "--whitespace=nowarn",
                    str(artifact_path),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                git_check = {
                    "ran": True,
                    "returncode": int(proc.returncode),
                    "stdout": (proc.stdout or "")[:4000],
                    "stderr": (proc.stderr or "")[:4000],
                }
                if proc.returncode != 0:
                    errors.append({"code": "git_apply_check_failed", "message": "git apply --check failed"})

    if artifact_path and artifact_path.exists() and art_type == "feature_pack":
        if artifact_path.is_file():
            warnings.append(
                {
                    "code": "feature_pack_file_artifact",
                    "message": "feature_pack artifact is a file; extract into a directory for auto-apply",
                }
            )
        else:
            has_pack = (artifact_path / "pack").exists() or (drop_dir / "pack").exists()
            has_applier = (artifact_path / "apply_feature_pack.py").exists() or (drop_dir / "apply_feature_pack.py").exists()
            if not has_pack:
                warnings.append({"code": "missing_pack_dir", "message": "feature_pack has no pack/ directory"})
            if not has_applier:
                warnings.append({"code": "missing_apply_script", "message": "feature_pack has no apply_feature_pack.py"})

    if artifact_path and artifact_path.exists() and art_type == "file_bundle":
        warnings.append(
            {
                "code": "manual_apply_required",
                "message": "file_bundle validation can pass, but auto-apply is manual by design",
            }
        )

    report: dict[str, Any] = {
        "validated_at": _now_iso(),
        "drop_id": drop_id,
        "manifest_path": str(manifest_path),
        "artifact": {
            "type": art_type,
            "path": art_rel,
            "exists": bool(artifact_path and artifact_path.exists()),
            "sha256": actual_sha,
        },
        "touched_paths": touched_paths,
        "blocked_token_hits": blocked,
        "git_apply_check": git_check,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }
    return report


def _write_report(root: Path, drop_id: str, report_type: str, payload: dict[str, Any]) -> Path:
    out = root / "reports" / f"{drop_id}.{report_type}.json"
    _write_json(out, payload)
    return out


def _print_summary(report: dict[str, Any]) -> None:
    print(f"drop_id: {report.get('drop_id')}")
    print(f"ok: {report.get('ok')}")
    print(f"errors: {len(report.get('errors') or [])}")
    print(f"warnings: {len(report.get('warnings') or [])}")
    art = report.get("artifact") or {}
    print(f"artifact: {art.get('type')} -> {art.get('path')}")
    touched = report.get("touched_paths") or []
    if touched:
        print(f"touched_paths ({len(touched)}):")
        for rel in touched[:30]:
            print(f"  - {rel}")
        if len(touched) > 30:
            print(f"  ... +{len(touched) - 30} more")
    for err in report.get("errors") or []:
        print(f"ERROR[{err.get('code')}]: {err.get('message')}")
    for warn in report.get("warnings") or []:
        print(f"WARN[{warn.get('code')}]: {warn.get('message')}")


def _cmd_init(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)
    print(f"initialized: {root}")
    print("queues: incoming, staged, applied, rejected")
    print(f"template: {root / 'templates' / 'drop_manifest.template.json'}")
    return 0


def _cmd_new(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)

    drop_id = args.drop_id.strip()
    if not drop_id:
        print("error: --drop-id is required", file=sys.stderr)
        return 2

    drop_dir = _queue_dir(root, "incoming") / drop_id
    if drop_dir.exists() and not args.force:
        print(f"error: drop already exists: {drop_dir} (use --force to replace)", file=sys.stderr)
        return 2
    if drop_dir.exists():
        shutil.rmtree(drop_dir)
    drop_dir.mkdir(parents=True, exist_ok=True)

    art_type = args.artifact_type
    if art_type == "unified_diff":
        art_name = args.artifact_name or "change.diff"
    elif art_type == "feature_pack":
        art_name = args.artifact_name or "bundle"
    else:
        art_name = args.artifact_name or "bundle"

    manifest = _default_manifest_template()
    manifest["drop_id"] = drop_id
    manifest["prompt_id"] = args.prompt_id or ""
    manifest["batch_id"] = args.batch_id or ""
    manifest["title"] = args.title or ""
    manifest["artifact"]["type"] = art_type
    manifest["artifact"]["path"] = art_name
    manifest["ownership"]["allowed_paths"] = list(args.allowed_path or [])
    manifest["ownership"]["forbidden_paths"] = list(args.forbidden_path or [])
    manifest["tests"]["commands"] = list(args.test_command or [])
    manifest["meta"]["source"] = args.source or "chatgpt_tab"
    manifest["meta"]["created_at"] = _now_iso()
    manifest["meta"]["notes"] = args.notes or ""

    if art_type == "unified_diff":
        (drop_dir / art_name).write_text(
            "# paste unified diff here\n",
            encoding="utf-8",
        )
    else:
        (drop_dir / art_name).mkdir(parents=True, exist_ok=True)
        (drop_dir / art_name / ".gitkeep").write_text("", encoding="utf-8")

    manifest_path = drop_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    print(f"created drop: {drop_dir}")
    print(f"manifest: {manifest_path}")
    print(f"artifact placeholder: {drop_dir / art_name}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)

    try:
        queue, drop_dir = _find_drop(root, args.drop_id, queue_hint=args.queue)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    manifest_path = drop_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"error: manifest missing: {manifest_path}", file=sys.stderr)
        return 2

    report = _validate_manifest(manifest_path, repo, run_git_apply_check=not args.skip_git_check)
    report["queue"] = queue
    out = _write_report(root, args.drop_id, "validation", report)

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        _print_summary(report)
        print(f"report: {out}")
    return 0 if report.get("ok") else 2


def _cmd_stage(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)

    try:
        queue, drop_dir = _find_drop(root, args.drop_id, queue_hint="incoming")
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    del queue
    manifest_path = drop_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"error: manifest missing: {manifest_path}", file=sys.stderr)
        return 2

    report = _validate_manifest(manifest_path, repo, run_git_apply_check=True)
    _write_report(root, args.drop_id, "validation", report)
    if not report.get("ok"):
        _print_summary(report)
        print("stage aborted: validation failed", file=sys.stderr)
        return 2

    staged_dir = _queue_dir(root, "staged") / args.drop_id
    if staged_dir.exists():
        print(f"error: staged drop already exists: {staged_dir}", file=sys.stderr)
        return 2
    shutil.move(str(drop_dir), str(staged_dir))

    stage_report = {
        "drop_id": args.drop_id,
        "staged_at": _now_iso(),
        "from": str(drop_dir),
        "to": str(staged_dir),
        "ok": True,
    }
    out = _write_report(root, args.drop_id, "stage", stage_report)
    print(f"staged: {staged_dir}")
    print(f"report: {out}")
    return 0


def _apply_unified_diff(repo: Path, artifact_path: Path, execute: bool) -> tuple[bool, str]:
    cmd = [
        "git",
        "-C",
        str(repo),
        "apply",
        "--whitespace=nowarn",
        str(artifact_path),
    ]
    if not execute:
        return True, "dry-run only; run with --execute to apply"
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, "git apply succeeded"
    return False, f"git apply failed: {proc.stderr[:1000] or proc.stdout[:1000]}"


def _apply_feature_pack(repo: Path, drop_dir: Path, artifact_path: Path, execute: bool) -> tuple[bool, str]:
    applier = drop_dir / "apply_feature_pack.py"
    if not applier.exists() and artifact_path.is_dir():
        alt = artifact_path / "apply_feature_pack.py"
        if alt.exists():
            applier = alt
    if not applier.exists():
        return False, "apply_feature_pack.py not found in drop root or artifact directory"

    if (drop_dir / "pack").exists():
        pack_dir = drop_dir / "pack"
    elif artifact_path.is_dir() and (artifact_path / "pack").exists():
        pack_dir = artifact_path / "pack"
    elif artifact_path.is_dir():
        pack_dir = artifact_path
    else:
        return False, "feature_pack artifact is not a directory"

    if not execute:
        return True, f"dry-run only; would run: python {applier} --repo {repo} --pack {pack_dir}"

    cmd = [sys.executable, str(applier), "--repo", str(repo), "--pack", str(pack_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, "feature pack apply script succeeded"
    return False, f"feature pack apply failed: {proc.stderr[:1000] or proc.stdout[:1000]}"


def _cmd_apply(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)

    try:
        queue, drop_dir = _find_drop(root, args.drop_id, queue_hint="staged")
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    del queue
    manifest_path = drop_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"error: manifest missing: {manifest_path}", file=sys.stderr)
        return 2

    report = _validate_manifest(manifest_path, repo, run_git_apply_check=True)
    if not report.get("ok"):
        _write_report(root, args.drop_id, "validation", report)
        _print_summary(report)
        print("apply aborted: validation failed", file=sys.stderr)
        return 2

    manifest = _read_json(manifest_path)
    art = manifest.get("artifact") or {}
    art_type = str(art.get("type") or "")
    art_rel = _norm_rel_path(str(art.get("path") or ""))
    artifact_path = drop_dir / art_rel

    if art_type == "unified_diff":
        ok, msg = _apply_unified_diff(repo, artifact_path, execute=bool(args.execute))
    elif art_type == "feature_pack":
        ok, msg = _apply_feature_pack(repo, drop_dir, artifact_path, execute=bool(args.execute))
    elif art_type == "file_bundle":
        ok, msg = False, "file_bundle auto-apply is not implemented; use manual merge flow"
    else:
        ok, msg = False, f"unsupported artifact type: {art_type}"

    apply_report = {
        "drop_id": args.drop_id,
        "applied_at": _now_iso(),
        "execute": bool(args.execute),
        "ok": bool(ok),
        "message": msg,
        "artifact_type": art_type,
        "artifact_path": str(artifact_path),
    }
    out = _write_report(root, args.drop_id, "apply", apply_report)

    if ok and args.execute:
        target = _queue_dir(root, "applied") / args.drop_id
        if target.exists():
            print(f"error: cannot move to applied; destination exists: {target}", file=sys.stderr)
            print(f"report: {out}")
            return 2
        shutil.move(str(drop_dir), str(target))
        print(f"applied + moved: {target}")
        print(f"report: {out}")
        return 0

    if (not ok) and bool(args.reject_on_fail):
        target = _queue_dir(root, "rejected") / args.drop_id
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(drop_dir), str(target))
        print(f"moved to rejected: {target}")

    print("apply result:")
    print(f"- ok: {ok}")
    print(f"- message: {msg}")
    print(f"- report: {out}")
    if not args.execute:
        print("- note: run with --execute to apply changes")
    return 0 if ok else 2


def _cmd_reject(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)

    try:
        queue, drop_dir = _find_drop(root, args.drop_id, queue_hint=args.queue)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if queue == "rejected":
        print(f"already rejected: {drop_dir}")
        return 0

    target = _queue_dir(root, "rejected") / args.drop_id
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(drop_dir), str(target))
    report = {
        "drop_id": args.drop_id,
        "rejected_at": _now_iso(),
        "from_queue": queue,
        "reason": args.reason or "",
    }
    out = _write_report(root, args.drop_id, "reject", report)
    print(f"rejected: {target}")
    print(f"report: {out}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    repo = _repo_root()
    root = _intake_root(repo, args.root)
    _ensure_layout(root)

    print(f"intake_root: {root}")
    for queue in QUEUE_NAMES:
        qd = _queue_dir(root, queue)
        ids = sorted([p.name for p in qd.iterdir() if p.is_dir()])
        print(f"{queue}: {len(ids)}")
        if args.verbose and ids:
            for did in ids[:100]:
                print(f"  - {did}")
            if len(ids) > 100:
                print(f"  ... +{len(ids) - 100} more")
    reports = sorted((root / "reports").glob("*.json"))
    print(f"reports: {len(reports)}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Code drop intake pipeline for high-volume patch ingestion.")
    ap.add_argument("--root", default="", help="Override intake root (default: <repo>/code_intake)")

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create intake queue directory layout + template.")

    p_new = sub.add_parser("new", help="Create a new incoming drop folder + manifest skeleton.")
    p_new.add_argument("--drop-id", required=True)
    p_new.add_argument("--prompt-id", default="")
    p_new.add_argument("--batch-id", default="")
    p_new.add_argument("--title", default="")
    p_new.add_argument("--artifact-type", default="unified_diff", choices=sorted(ARTIFACT_TYPES))
    p_new.add_argument("--artifact-name", default="")
    p_new.add_argument("--source", default="chatgpt_tab")
    p_new.add_argument("--notes", default="")
    p_new.add_argument("--allowed-path", action="append", default=[])
    p_new.add_argument("--forbidden-path", action="append", default=[])
    p_new.add_argument("--test-command", action="append", default=[])
    p_new.add_argument("--force", action="store_true")

    p_val = sub.add_parser("validate", help="Validate drop manifest + artifact + path policy.")
    p_val.add_argument("--drop-id", required=True)
    p_val.add_argument("--queue", choices=QUEUE_NAMES, default=None)
    p_val.add_argument("--skip-git-check", action="store_true")
    p_val.add_argument("--json", dest="as_json", action="store_true")

    p_stage = sub.add_parser("stage", help="Validate + move incoming drop to staged queue.")
    p_stage.add_argument("--drop-id", required=True)

    p_apply = sub.add_parser("apply", help="Apply a staged drop (default is dry-run metadata only).")
    p_apply.add_argument("--drop-id", required=True)
    p_apply.add_argument("--execute", action="store_true", help="Actually apply changes. Omit for dry-run mode.")
    p_apply.add_argument("--reject-on-fail", action="store_true")

    p_reject = sub.add_parser("reject", help="Move a drop to rejected queue.")
    p_reject.add_argument("--drop-id", required=True)
    p_reject.add_argument("--queue", choices=QUEUE_NAMES, default=None)
    p_reject.add_argument("--reason", default="")

    p_status = sub.add_parser("status", help="Show queue counts and optionally IDs.")
    p_status.add_argument("--verbose", action="store_true")

    return ap


def main(argv: Optional[list[str]] = None) -> int:
    ap = _build_parser()
    args = ap.parse_args(argv)

    if args.cmd == "init":
        return _cmd_init(args)
    if args.cmd == "new":
        return _cmd_new(args)
    if args.cmd == "validate":
        return _cmd_validate(args)
    if args.cmd == "stage":
        return _cmd_stage(args)
    if args.cmd == "apply":
        return _cmd_apply(args)
    if args.cmd == "reject":
        return _cmd_reject(args)
    if args.cmd == "status":
        return _cmd_status(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
