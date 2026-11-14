#!/usr/bin/env python3
"""Require version + changelog updates when product surface changes."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import tomllib
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
ROOT_DIRNAME = ROOT.name

REQUIRED_FILES: set[str] = {
    "pyproject.toml",
    "thomas/__init__.py",
    "CHANGELOG.md",
}

PRODUCT_PREFIXES: Sequence[str] = (
    "thomas/",
    "server/",
    "web/",
    "web-ui/",
    "extensions/",
)

PRODUCT_EXACT: set[str] = {
    "thomas.toml",
    "run-ui.cmd",
    "run-repl.cmd",
}

IGNORE_PREFIXES: Sequence[str] = (
    ".github/",
    "docs/",
    "plans/",
    "tasks/",
    "tests/",
    "library/",
    "Inbox/",
    "code_intake/",
    "pack/",
    "patches/",
    "runtime/",
    "output/",
    ".inbox_extract_",
)

IGNORE_EXACT: set[str] = {
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "thomas/__init__.py",
    "thomas/_architecture.py",
    "thomas/observability/module_audit.py",
}


def _normalize(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    # Only strip a leading `<repo-dirname>/` segment when it's a doubled
    # prefix from an absolute path (e.g. `/home/runner/work/thomas/thomas/...`
    # → `thomas/thomas/file.py` after path-relative resolution). Bare
    # relative paths like `thomas/__init__.py` MUST be preserved verbatim —
    # otherwise REQUIRED_FILES lookups break on public `thomas/` checkouts
    # where the repo dir name and the package name collide.
    prefix = ROOT_DIRNAME + "/"
    if p.startswith(prefix + prefix):
        p = p[len(prefix) :]
    return p


def _git_changed_files(
    base: str | None,
    head: str | None,
    *,
    include_untracked: bool = True,
) -> tuple[list[str], str, str]:
    resolved_head = (head or "HEAD").strip() or "HEAD"
    if base and str(base).strip("0"):
        resolved_base = str(base)
        range_expr = f"{resolved_base}...{resolved_head}"
    else:
        resolved_base = f"{resolved_head}~1"
        range_expr = f"{resolved_base}...{resolved_head}"

    proc = subprocess.run(
        ["git", "diff", "--name-only", range_expr],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fallback = subprocess.run(
            ["git", "diff", "--name-only", resolved_head],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if fallback.returncode != 0:
            raise RuntimeError(
                "Unable to compute git diff. "
                f"primary error: {proc.stderr.strip()} | fallback error: {fallback.stderr.strip()}"
            )
        out = fallback.stdout
    else:
        out = proc.stdout

    changed: set[str] = {_normalize(line) for line in out.splitlines() if _normalize(line)}

    for cmd in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
    ):
        local = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if local.returncode == 0:
            for line in local.stdout.splitlines():
                p = _normalize(line)
                if p:
                    changed.add(p)

    if include_untracked:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if untracked.returncode == 0:
            for line in untracked.stdout.splitlines():
                p = _normalize(line)
                if p:
                    changed.add(p)

    return sorted(changed), resolved_base, resolved_head


def _is_product_surface(path: str) -> bool:
    p = _normalize(path)
    if not p:
        return False
    if p in IGNORE_EXACT:
        return False
    for prefix in IGNORE_PREFIXES:
        if p.startswith(prefix):
            return False
    if p in PRODUCT_EXACT:
        return True
    return any(p.startswith(prefix) for prefix in PRODUCT_PREFIXES)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _version_from_pyproject_text(text: str) -> str:
    data = tomllib.loads(text)
    return str((data.get("project") or {}).get("version") or "").strip()


def _version_from_init_text(text: str) -> str:
    m = re.search(r"__version__\s*=\s*\"([^\"]+)\"", text)
    return str(m.group(1)).strip() if m else ""


def _git_stdout(*args: str) -> str | None:
    """Run one read-only git command in the repo; its stdout, or None when it fails."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _git_show_text(rev: str, rel_path: str) -> str | None:
    return _git_stdout("show", f"{rev}:{rel_path}")


def _ref_sha(ref: str) -> str | None:
    """Resolve `ref` (an exact, fully-qualified path) via `git show-ref
    --verify` -- NO DWIM fallback, so a same-named tag or nested lookalike
    branch can never stand in for the intended ref (the landed
    claim_evidence.py `_ref_resolves` pattern, 9ac14311/f7a523f0).
    """
    try:
        proc = subprocess.run(
            ["git", "show-ref", "--verify", ref],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    sha = (proc.stdout or "").strip().splitlines()[0].split(maxsplit=1)[0].strip()
    return sha or None


def _merge_base_with_canonical(head: str = "HEAD") -> str | None:
    """Merge-base with the canonical branch, or None when unresolvable."""
    # Exact, fully-qualified candidate paths -- a bare name here lets git's
    # DWIM resolution (gitrevisions(7)) match a same-named tag before the
    # intended branch, and a bare "origin/dev" even matches a local branch
    # literally named origin/dev before the remote-tracking ref. `head`
    # stays "HEAD": that is an exact $GIT_DIR/HEAD lookup (rule 1), not
    # DWIM-reachable.
    for ref in (
        "refs/remotes/dev-origin/dev",
        "refs/remotes/origin/dev",
        "refs/heads/dev",
        "refs/remotes/origin/main",
        "refs/heads/main",
    ):
        ref_sha = _ref_sha(ref)
        if ref_sha is None:
            continue
        proc = subprocess.run(
            ["git", "merge-base", head, ref_sha],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        base = str(proc.stdout or "").strip()
        if proc.returncode == 0 and base:
            # On the canonical branch itself the merge-base IS head — no
            # branch-wide window exists, so the fallback must not engage.
            if base != _rev_parse(head):
                return base
            return None
    return None


def _rev_parse(rev: str) -> str:
    proc = subprocess.run(["git", "rev-parse", rev], cwd=ROOT, capture_output=True, text=True)
    return str(proc.stdout or "").strip()


def _branch_release_proof(current_py: str, current_init: str) -> str | None:
    """Return a PASS note when the BRANCH already carries the release update.

    The per-commit helper lane (--changed-file) used to demand pyproject.toml,
    thomas/__init__.py, and CHANGELOG.md be dirty in EVERY product-surface
    commit. Once a version bump landed, those files were clean, so every later
    product commit through the sanctioned helper was structurally blocked (the
    stranded-work catch-22, recurring on the workboard since 2026-06-26).
    A branch that has ALREADY bumped the version and updated the changelog
    relative to its merge-base with the canonical branch satisfies the gate's
    actual contract; direct commits on the canonical branch still require the
    release files in the change set. (Calvin approval, 2026-07-18.)
    """

    base = _merge_base_with_canonical()
    if not base:
        return None
    base_py = _git_show_text(base, "pyproject.toml")
    base_init = _git_show_text(base, "thomas/__init__.py")
    if base_py is None or base_init is None:
        return None
    try:
        prior_py = _version_from_pyproject_text(base_py)
    except (ValueError, KeyError, TypeError):
        return None
    prior_init = _version_from_init_text(base_init)
    if not (prior_py and prior_init and current_py and current_init):
        return None
    if current_py == prior_py or current_init == prior_init:
        return None
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD", "--", "CHANGELOG.md", "changelog.d"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    changelog_changed = bool(str(diff.stdout or "").strip())
    if not changelog_changed:
        dirty = subprocess.run(
            ["git", "diff", "--name-only", "--", "CHANGELOG.md", "changelog.d"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        changelog_changed = bool(str(dirty.stdout or "").strip())
    if not changelog_changed:
        return None
    return f"release metadata already updated branch-wide ({prior_py} -> {current_py} since {base[:12]})"


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_RELEASE_TAG_RE = re.compile(r"^refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse `major.minor.patch` into integers; anything else is None (fail closed)."""
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _last_released_version() -> tuple[int, int, int] | None:
    """The version of the last RELEASE, or None when none can be found.

    Highest well-formed `v<major>.<minor>.<patch>` tag, read with an exact
    `refs/tags/` listing (no DWIM). Falling back to the version in
    thomas/__init__.py at refs/remotes/origin/main (the public repo's main).
    Read-only: this never writes to git.
    """
    tagged: list[tuple[int, int, int]] = []
    for line in (_git_stdout("for-each-ref", "--format=%(refname)", "refs/tags/") or "").splitlines():
        m = _RELEASE_TAG_RE.match(line.strip())
        if m:
            tagged.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if tagged:
        return max(tagged)
    main_sha = _ref_sha("refs/remotes/origin/main")
    if main_sha is None:
        return None
    main_init = _git_show_text(main_sha, "thomas/__init__.py")
    if main_init is None:
        return None
    return _parse_version(_version_from_init_text(main_init))


def _pending_release_proof(changed_set: set[str], current_py: str, current_init: str) -> str | None:
    """Return a PASS note when a release is pending and this change carries its notes.

    The contract: a product change needs a changelog entry, and the project
    version must be ahead of the last RELEASE (not ahead of the last push).
    On the canonical branch the branch-wide proof cannot engage (the
    merge-base is head), and pyproject.toml is a protected file the commit
    tool cannot land, so once a bump is pending every later product commit
    needs only its changelog entry. Once the release is cut and nobody has
    bumped, the version is no longer ahead and the bump is demanded again.
    Fails closed: malformed or disagreeing versions, no changelog entry in
    THIS change set, or no known release all return None.
    """
    if current_py != current_init:
        return None
    version = _parse_version(current_py)
    if version is None:
        return None
    if "CHANGELOG.md" not in changed_set:
        return None
    released = _last_released_version()
    if released is None or version <= released:
        return None
    return (
        f"release pending ({current_py} is ahead of the last release "
        f"{'.'.join(str(n) for n in released)}); this change carries its changelog entry"
    )


def _check_release_hygiene_script() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "scripts/forge/gates/release_hygiene.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require version/changelog updates for product-surface changes.")
    parser.add_argument("--base", default=None, help="Diff base ref/sha (optional)")
    parser.add_argument("--head", default=None, help="Diff head ref/sha (default: HEAD)")
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed path (repeatable); skips git diff resolution if present.",
    )
    parser.add_argument(
        "--include-untracked",
        dest="include_untracked",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include untracked files in change detection (default: enabled).",
    )
    parser.add_argument(
        "--enforce-release-hygiene",
        dest="enforce_release_hygiene",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also run the broader release hygiene script after the scoped release-update checks pass.",
    )
    args = parser.parse_args(argv)

    if args.changed_file:
        changed = sorted({_normalize(x) for x in args.changed_file if _normalize(x)})
        resolved_base = "<manual>"
        resolved_head = "<manual>"
    else:
        try:
            changed, resolved_base, resolved_head = _git_changed_files(
                args.base,
                args.head,
                include_untracked=bool(args.include_untracked),
            )
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as exc:
            print(f"Release update gate: FAIL (diff resolution error: {exc})")
            return 1

    if not changed:
        print("Release update gate: PASS (no changed files detected)")
        return 0

    relevant = [p for p in changed if _is_product_surface(p)]
    if not relevant:
        print("Release update gate: PASS (no product-surface changes)")
        return 0

    changed_set = set(changed)
    if any(p.startswith("changelog.d/") and p.endswith(".md") and not p.endswith("README.md") for p in changed_set):
        changed_set.add("CHANGELOG.md")  # a per-agent fragment is the changelog update
    missing = sorted(REQUIRED_FILES - changed_set)
    violations: list[str] = []

    py_text = _read(ROOT / "pyproject.toml")
    init_text = _read(ROOT / "thomas" / "__init__.py")
    current_py = _version_from_pyproject_text(py_text)
    current_init = _version_from_init_text(init_text)

    release_pending = False
    if missing:
        branch_proof = _branch_release_proof(current_py, current_init) if resolved_base == "<manual>" else None
        pending_proof = None if branch_proof else _pending_release_proof(changed_set, current_py, current_init)
        if branch_proof:
            print(f"Release update gate: note — {branch_proof}")
        elif pending_proof:
            release_pending = True
            print(f"Release update gate: note — {pending_proof}")
        else:
            violations.append(
                "product-surface changes require release updates; missing changed files: " + ", ".join(missing)
            )

    base_py = _git_show_text(resolved_base, "pyproject.toml") if resolved_base != "<manual>" else None
    base_init = _git_show_text(resolved_base, "thomas/__init__.py") if resolved_base != "<manual>" else None

    # A pending release already satisfies the version contract: the version is
    # ahead of the last release, so "unchanged since this commit's base" is not a violation.
    if not release_pending and base_py is not None and base_init is not None:
        try:
            prior_py = _version_from_pyproject_text(base_py)
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError):
            prior_py = ""
        prior_init = _version_from_init_text(base_init)
        if prior_py and prior_init and current_py == prior_py and current_init == prior_init:
            violations.append("product-surface changed but project version did not change relative to base")

    hygiene_output = ""
    if bool(args.enforce_release_hygiene):
        ok_hygiene, hygiene_output = _check_release_hygiene_script()
        if not ok_hygiene:
            violations.append("release_hygiene.py failed")

    if violations:
        print("Release update gate: FAIL")
        print(f"- diff range: {resolved_base}...{resolved_head}")
        print("- product-surface changes detected:")
        for path in relevant:
            print(f"  - {path}")
        for msg in violations:
            print(f"- {msg}")
        if hygiene_output:
            print("- release hygiene output:")
            for line in hygiene_output.splitlines():
                print(f"  {line}")
        return 1

    print("Release update gate: PASS")
    print(f"- diff range: {resolved_base}...{resolved_head}")
    print(f"- product-surface file count: {len(relevant)}")
    print(f"- version files + changelog changed: {', '.join(sorted(REQUIRED_FILES))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
