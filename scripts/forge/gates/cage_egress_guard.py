#!/usr/bin/env python3
"""Tripwire: flag clone / remote / submodule / out-of-box signals in a change.

Cage PROBLEM 1, defense-in-depth. This is the HONEST companion to the Windows
Sandbox: a same-OS-user shell can bypass any in-repo check, so this gate is NOT
the containment wall — ``build_sandbox_config.py`` (network off + mapped-folders
only) is. What this adds is *tamper-evidence*: when the sandbox is not active,
it surfaces the concrete escape/exfil vectors an agent's change can carry, so
they are caught and reviewed rather than landing silently.

It scans a unified diff (a submission patch, or the staged diff) for:

BLOCK (exit 1): structural escape vectors that are almost never legitimate
  * new/added git submodules (``.gitmodules`` ``url =`` lines) — pulls another
    repo in;
  * writes under ``.git/`` — tampering with git internals (hooks, config);
  * added files outside an ``--allow`` root, when an allowlist is given —
    "stay in your box".

WARN (exit 0, or exit 1 with --strict): added command lines that *invoke*
  cloning / remote mutation (``git clone``, ``git remote add``,
  ``git submodule add``). Mentions in docs/setup scripts are often legitimate,
  so these are advisory unless ``--strict``.

stdlib-only; unit-testable by feeding ``--patch-file``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Added command lines that reach out to another repo / remote. Matched only on
# inserted (+) diff lines.
_EGRESS_CMD_RE = re.compile(
    r"\b(git\s+clone|git\s+remote\s+add|git\s+submodule\s+add|git\s+fetch\s+\S*://|"
    r"git\s+push\s+\S*://)\b",
    re.IGNORECASE,
)
_SUBMODULE_URL_RE = re.compile(r"^\+\s*url\s*=\s*\S+", re.IGNORECASE)


def _norm(path: str) -> str:
    # Strip a leading "./" and surrounding slashes WITHOUT eating a leading dot
    # (str.lstrip("./") would turn ".git" into "git" and ".github" into "github").
    raw = str(path or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw.strip("/")


def _added_paths(diff_text: str) -> list[str]:
    out: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in out:
                out.append(path)
    return out


def _current_file(diff_text: str) -> dict[int, str]:
    """Map each line index to the file it belongs to (for submodule context)."""
    mapping: dict[int, str] = {}
    current = ""
    for idx, line in enumerate(diff_text.splitlines()):
        if line.startswith("+++ b/"):
            current = line[6:].strip()
        mapping[idx] = current
    return mapping


def scan_diff(diff_text: str, *, allow_roots: list[str] | None = None) -> dict[str, list[dict]]:
    """Return ``{"block": [...], "warn": [...]}`` findings for a unified diff."""
    diff_text = str(diff_text or "")
    block: list[dict] = []
    warn: list[dict] = []
    allow = [_norm(root) for root in (allow_roots or []) if _norm(root)]
    line_file = _current_file(diff_text)

    # Out-of-allowlist added files + .git writes.
    for path in _added_paths(diff_text):
        npath = _norm(path)
        if npath.startswith(".git/") or npath == ".git":
            block.append({"type": "git_internal_write", "path": path, "detail": "change writes under .git/"})
        if allow and not any(npath == root or npath.startswith(root + "/") for root in allow):
            block.append({"type": "out_of_allowlist", "path": path, "detail": f"added outside allowed roots {allow}"})

    for idx, line in enumerate(diff_text.splitlines()):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if _SUBMODULE_URL_RE.match(line) or line_file.get(idx, "").endswith(".gitmodules"):
            if "url" in line.lower():
                block.append(
                    {"type": "submodule_add", "path": line_file.get(idx, ".gitmodules"), "detail": line.strip()[:160]}
                )
        match = _EGRESS_CMD_RE.search(line)
        if match:
            warn.append({"type": "egress_command", "path": line_file.get(idx, ""), "detail": line.strip()[:160]})
    return {"block": block, "warn": warn}


def _staged_diff(repo: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--binary"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def evaluate(
    *,
    patch_file: str = "",
    repo: Path | None = None,
    allow_roots: list[str] | None = None,
    strict: bool = False,
) -> dict:
    repo = repo or _REPO_ROOT
    if patch_file:
        diff_text = Path(patch_file).read_text(encoding="utf-8", errors="replace")
    else:
        diff_text = _staged_diff(repo)
    findings = scan_diff(diff_text, allow_roots=allow_roots)
    failed = bool(findings["block"]) or (strict and bool(findings["warn"]))
    return {"ok": not failed, "block": findings["block"], "warn": findings["warn"], "strict": strict}


def _render(result: dict) -> str:
    lines = []
    if result["ok"] and not result["warn"]:
        return "cage-egress guard: PASS (no clone/remote/submodule/out-of-box signals)"
    if result["block"]:
        lines.append(f"cage-egress guard: BLOCKED ({len(result['block'])} escape vector(s))")
        for f in result["block"]:
            lines.append(f"  [BLOCK] {f['type']}: {f.get('path', '')} -- {f.get('detail', '')}")
    else:
        lines.append("cage-egress guard: PASS with warnings")
    for f in result["warn"]:
        lines.append(f"  [warn]  {f['type']}: {f.get('path', '')} -- {f.get('detail', '')}")
    if result["warn"] and not result["strict"]:
        lines.append("  (warnings are advisory; re-run with --strict to fail on them)")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flag clone/remote/submodule/out-of-box signals in a change.")
    parser.add_argument("--patch-file", default="", help="Scan this unified diff (default: the staged diff).")
    parser.add_argument("--repo", default=str(_REPO_ROOT))
    parser.add_argument(
        "--allow", action="append", default=[], dest="allow_roots", help="Allowed write root (repeatable)."
    )
    parser.add_argument("--strict", action="store_true", help="Fail on advisory warnings too.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate(
        patch_file=args.patch_file,
        repo=Path(args.repo),
        allow_roots=args.allow_roots,
        strict=args.strict,
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(_render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
