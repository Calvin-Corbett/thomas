#!/usr/bin/env python3
"""
Feature pack applier: observability.run_replay_debugger

Idempotently:
- Copies new files into the repo.
- Registers aiohttp routes for replay debugger.
- Adds the replay observability middleware to the aiohttp app (best-effort).
- Appends feature entry into docs/FEATURE_CATALOG.md (non-destructive).
Creates backups for modified files under: <repo>/.feature_backups/observability.run_replay_debugger/
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

FEATURE_ID = "observability.run_replay_debugger"

def copy_tree(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)

def backup_file(repo: Path, file_path: Path) -> Path:
    backup_root = repo / ".feature_backups" / FEATURE_ID
    backup_root.mkdir(parents=True, exist_ok=True)
    rel = file_path.relative_to(repo)
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, backup_path)
    return backup_path

def patch_text_file(repo: Path, target: Path, patch_fn) -> bool:
    if not target.exists():
        return False
    old = target.read_text(encoding="utf-8")
    new, changed = patch_fn(old)
    if not changed:
        return True
    backup_file(repo, target)
    target.write_text(new, encoding="utf-8")
    return True

def ensure_feature_catalog(repo: Path) -> None:
    cat = repo / "docs" / "FEATURE_CATALOG.md"
    append = repo / "docs" / "FEATURE_CATALOG.md.append"
    if not cat.exists() or not append.exists():
        return
    snippet = append.read_text(encoding="utf-8")
    def do_patch(old: str):
        if FEATURE_ID in old:
            return old, False
        return old.rstrip() + "\n\n" + snippet.strip() + "\n", True
    patch_text_file(repo, cat, do_patch)

def _patch_route_setup_text(old: str) -> tuple[str, bool]:
    if "replay_debugger" in old and "replay_debugger.setup" in old:
        return old, False

    # add import near other thomas.server.routes imports
    import_stmt = "from thomas.server.routes import replay_debugger\n"
    if import_stmt not in old:
        # insert after aiohttp import if present
        m = re.search(r"^(from\s+aiohttp\s+import\s+web.*\n)", old, flags=re.M)
        if m:
            ins = m.end(1)
            old = old[:ins] + import_stmt + old[ins:]
        else:
            old = import_stmt + old

    # insert call inside setup/setup_routes function
    for pat in [
        r"def\s+setup_routes\s*\(\s*app\s*:\s*web\.Application\s*\)\s*->\s*None\s*:\s*\n",
        r"def\s+setup_routes\s*\(\s*app\s*\)\s*:\s*\n",
        r"def\s+setup\s*\(\s*app\s*:\s*web\.Application\s*\)\s*->\s*None\s*:\s*\n",
        r"def\s+setup\s*\(\s*app\s*\)\s*:\s*\n",
    ]:
        m2 = re.search(pat, old)
        if m2:
            insert_pos = m2.end(0)
            call = "    replay_debugger.setup(app)\n"
            if call in old:
                return old, False
            old = old[:insert_pos] + call + old[insert_pos:]
            return old, True

    # fallback: append at end if app variable exists
    if "app" in old:
        old = old.rstrip() + "\n\n# added by feature pack: observability.run_replay_debugger\nreplay_debugger.setup(app)\n"
        return old, True

    return old, False

def ensure_route_registration(repo: Path) -> None:
    # Look for likely route setup modules
    candidates = []
    for p in (repo / "thomas").rglob("*.py"):
        if "server" not in p.parts:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "web.Application" in txt and ("router.add_" in txt or "setup_routes" in txt or "setup(app" in txt):
            candidates.append(p)

    for p in candidates:
        ok = patch_text_file(repo, p, _patch_route_setup_text)
        if ok:
            new = p.read_text(encoding="utf-8")
            if "replay_debugger.setup(app)" in new:
                return

    raise SystemExit(
        "Could not automatically register replay_debugger routes.\n"
        "Manual fix: during server startup where routes are registered, add:\n"
        "  from thomas.server.routes import replay_debugger\n"
        "  replay_debugger.setup(app)\n"
    )

def _patch_middleware_text(old: str) -> tuple[str, bool]:
    if "replay_observability_middleware" in old:
        return old, False

    import_stmt = "from thomas.server.middleware.replay_observability import replay_observability_middleware\n"
    if import_stmt not in old:
        m = re.search(r"^(from\s+aiohttp\s+import\s+web.*\n)", old, flags=re.M)
        if m:
            ins = m.end(1)
            old = old[:ins] + import_stmt + old[ins:]
        else:
            old = import_stmt + old

    # Patch web.Application(...) construction to include middleware if it has middlewares=[...]
    # If no middlewares, insert middlewares=[replay_observability_middleware]
    def repl(m):
        inside = m.group(1)
        if "middlewares=" in inside:
            # add to existing list
            inside2 = re.sub(r"middlewares\s*=\s*\[", "middlewares=[replay_observability_middleware,", inside, count=1)
            return f"web.Application({inside2})"
        else:
            return f"web.Application(middlewares=[replay_observability_middleware]{',' if inside.strip() else ''}{inside})"

    new = re.sub(r"web\.Application\s*\(\s*(.*?)\s*\)", repl, old, count=1, flags=re.S)
    if new != old:
        return new, True

    # Fallback: add app.middlewares.append(...)
    m2 = re.search(r"app\s*=\s*web\.Application\([^\)]*\)\s*\n", old)
    if m2:
        ins = m2.end(0)
        line = "app.middlewares.append(replay_observability_middleware)\n"
        new = old[:ins] + line + old[ins:]
        return new, True

    return old, False

def ensure_middleware(repo: Path) -> None:
    # Find entrypoints that construct web.Application
    candidates = []
    for p in (repo / "thomas").rglob("*.py"):
        if "server" not in p.parts:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "web.Application" in txt:
            candidates.append(p)

    for p in candidates:
        ok = patch_text_file(repo, p, _patch_middleware_text)
        if ok:
            new = p.read_text(encoding="utf-8")
            if "replay_observability_middleware" in new:
                return

    raise SystemExit(
        "Could not automatically add replay_observability_middleware.\n"
        "Manual fix: when constructing aiohttp app, include:\n"
        "  from thomas.server.middleware.replay_observability import replay_observability_middleware\n"
        "  app = web.Application(middlewares=[replay_observability_middleware, ...])\n"
        "or:\n"
        "  app.middlewares.append(replay_observability_middleware)\n"
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to repo root (e.g., F:\\DevHub\\Thomas)")
    ap.add_argument("--pack", default="pack", help="Path to extracted pack/ directory (default: ./pack)")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    pack_dir = Path(args.pack).expanduser().resolve()

    if not repo.exists():
        raise SystemExit(f"Repo path does not exist: {repo}")
    if not (repo / "thomas").exists():
        raise SystemExit(f"Repo does not look like a Thomas repo (missing 'thomas/' folder): {repo}")
    if not pack_dir.exists():
        raise SystemExit(f"Pack directory not found: {pack_dir}")

    # copy files
    copy_tree(pack_dir, repo)

    # route wiring + middleware
    ensure_route_registration(repo)
    ensure_middleware(repo)

    # docs
    ensure_feature_catalog(repo)

    print("✅ Applied feature pack:", FEATURE_ID)

if __name__ == "__main__":
    main()
