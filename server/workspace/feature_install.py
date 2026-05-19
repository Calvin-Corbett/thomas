"""Installer for feature: workspace.rbac_multi_tenant (single-zip drop-in)

Commands:
  python -m server.workspace.feature_install apply
  python -m server.workspace.feature_install verify
  python -m server.workspace.feature_install rollback

apply:
  - patches FastAPI entrypoint to call server.workspace.bootstrap.install(app)
  - ensures /api routes include dependency Depends(enforce_workspace)
  - patches Web UI header to render WorkspaceSwitcher
  - patches Web UI entrypoint to import workspaceFetch (global fetch shim)
  - appends docs entries to docs/FEATURE_CATALOG.md and docs/PROJECT_SCOPE.md

verify:
  - runs route + DB checks via server.workspace.verify_install

rollback:
  - restores patched files from backups (feature files remain, but git rollback is recommended)

Backups live under:
  .thomas_feature_backups/workspace.rbac_multi_tenant/
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

FEATURE_ID = "workspace.rbac_multi_tenant"
BACKUP_DIR = Path(".thomas_feature_backups") / FEATURE_ID
RECEIPT_PATH = BACKUP_DIR / "receipt.json"

PUBLIC_MARKER = "workspace.rbac_multi_tenant"


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")


def _backup_file(p: Path, receipt: dict) -> None:
    rel = str(p.as_posix())
    dest = BACKUP_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    receipt.setdefault("backups", []).append(rel)


def _save_receipt(receipt: dict) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _write(RECEIPT_PATH, json.dumps(receipt, indent=2))


def _load_receipt() -> dict | None:
    if not RECEIPT_PATH.exists():
        return None
    return json.loads(_read(RECEIPT_PATH))


def _find_fastapi_entrypoint(repo: Path) -> Path | None:
    server_dir = repo / "server"
    if not server_dir.exists():
        return None
    candidates = []
    for p in server_dir.rglob("*.py"):
        try:
            txt = _read(p)
        except Exception:
            continue
        if "FastAPI(" in txt and ("include_router" in txt or "APIRouter(" in txt):
            candidates.append(p)
    preferred = [server_dir / "main.py", server_dir / "app.py", server_dir / "__main__.py"]
    for p in preferred:
        if p in candidates:
            return p
    return candidates[0] if candidates else None


def _patch_fastapi_entrypoint(p: Path, receipt: dict) -> None:
    txt = _read(p)
    if PUBLIC_MARKER in txt:
        return

    import_block = (
        "\n# --- feature: workspace.rbac_multi_tenant ---\n"
        "from fastapi import Depends\n"
        "from server.workspace.bootstrap import install as _install_workspace_rbac_multi_tenant\n"
        "from server.workspace.deps import enforce_workspace\n"
        "# --- end feature: workspace.rbac_multi_tenant ---\n"
    )

    # Insert imports after last fastapi import or at top.
    if "from fastapi" in txt:
        m = list(re.finditer(r"^from fastapi.*$", txt, flags=re.M))
        if m:
            insert_at = m[-1].end()
            txt = txt[:insert_at] + import_block + txt[insert_at:]
        else:
            txt = import_block + txt
    else:
        txt = import_block + txt

    # Ensure install(app) is called after app creation.
    m = re.search(r"^(\s*app\s*=\s*FastAPI\(.*\)\s*)$", txt, flags=re.M)
    if m:
        insert_at = m.end()
        txt = txt[:insert_at] + "\n_install_workspace_rbac_multi_tenant(app)\n" + txt[insert_at:]
    else:
        m2 = re.search(r"^\s*def\s+create_app\s*\(.*\):\s*$", txt, flags=re.M)
        if m2:
            after = re.search(r"^(\s*app\s*=\s*FastAPI\(.*\)\s*)$", txt[m2.end() :], flags=re.M)
            if after:
                insert_at = m2.end() + after.end()
                txt = txt[:insert_at] + "\n    _install_workspace_rbac_multi_tenant(app)\n" + txt[insert_at:]
            else:
                raise RuntimeError(f"Could not find app = FastAPI(...) inside create_app() in {p}")
        else:
            raise RuntimeError(f"Could not find FastAPI app construction in {p}")

    # Patch include_router(... prefix="/api" ...) calls.
    def _patch_include(match: re.Match) -> str:
        call = match.group(0)
        if "enforce_workspace" in call:
            return call
        if "dependencies=" in call:
            # Append to existing dependency list
            call2 = re.sub(
                r"dependencies\s*=\s*\[(.*?)\]",
                r"dependencies=[\1, Depends(enforce_workspace)]",
                call,
                flags=re.S,
            )
            return call2
        # Add dependencies kwarg
        return call[:-1] + ", dependencies=[Depends(enforce_workspace)])"

    txt = re.sub(
        r"""app\.include_router\([^\)]*prefix\s*=\s*["']\/api["'][^\)]*\)""",
        _patch_include,
        txt,
        flags=re.M,
    )

    # Patch APIRouter(prefix="/api") definitions if present:
    # e.g. api = APIRouter(prefix="/api") -> api = APIRouter(prefix="/api", dependencies=[Depends(enforce_workspace)])
    def _patch_api_router(match: re.Match) -> str:
        call = match.group(0)
        if "dependencies=" in call:
            return call
        return call[:-1] + ", dependencies=[Depends(enforce_workspace)])"

    txt = re.sub(
        r"""APIRouter\([^\)]*prefix\s*=\s*["']\/api["'][^\)]*\)""",
        _patch_api_router,
        txt,
        flags=re.M,
    )

    # Add marker
    if PUBLIC_MARKER not in txt:
        txt += f"\n# {PUBLIC_MARKER}: installed\n"

    _backup_file(p, receipt)
    _write(p, txt)
    receipt.setdefault("patched", []).append(str(p.as_posix()))


def _find_web_header(repo: Path) -> Path | None:
    web_dir = repo / "web-ui" / "src"
    if not web_dir.exists():
        return None
    candidates = []
    for p in web_dir.rglob("*.tsx"):
        try:
            txt = _read(p)
        except Exception:
            continue
        if "<header" in txt and ("Header" in txt or "AppHeader" in txt):
            candidates.append(p)
    preferred = [web_dir / "components" / "AppHeader.tsx", web_dir / "components" / "Header.tsx"]
    for p in preferred:
        if p in candidates:
            return p
    return candidates[0] if candidates else None


def _patch_web_header(p: Path, receipt: dict) -> None:
    txt = _read(p)
    if "WorkspaceSwitcher" in txt:
        return

    # Try to insert import
    if "web-ui/src/components" in str(p.as_posix()):
        import_line = 'import { WorkspaceSwitcher } from "./WorkspaceSwitcher";\n'
    else:
        import_line = 'import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";\n'

    if "WorkspaceSwitcher" not in txt:
        # insert after first import block, else at top
        if re.search(r"^import .*\n", txt, flags=re.M):
            txt = re.sub(r"^(import .*\n)+", lambda m: m.group(0) + import_line, txt, count=1, flags=re.M)
        else:
            txt = import_line + txt

    # Insert component usage
    inserted = False
    for pat in [r"(\<UserMenu[^\n]*\/>\s*)", r"(\<AccountMenu[^\n]*\/>\s*)", r"(\<ProfileMenu[^\n]*\/>\s*)"]:
        m = re.search(pat, txt)
        if m:
            txt = txt[: m.start()] + "<WorkspaceSwitcher />\n" + txt[m.start() :]
            inserted = True
            break
    if not inserted:
        m = re.search(r"\</header\>", txt)
        if m:
            txt = txt[: m.start()] + "  <WorkspaceSwitcher />\n" + txt[m.start() :]
            inserted = True

    if not inserted:
        raise RuntimeError(f"Could not patch header to include WorkspaceSwitcher in {p}")

    _backup_file(p, receipt)
    _write(p, txt)
    receipt.setdefault("patched", []).append(str(p.as_posix()))


def _find_web_entrypoint(repo: Path) -> Path | None:
    web_dir = repo / "web-ui" / "src"
    if not web_dir.exists():
        return None
    preferred = [
        web_dir / "main.tsx",
        web_dir / "index.tsx",
        web_dir / "main.ts",
        web_dir / "index.ts",
    ]
    for p in preferred:
        if p.exists():
            return p
    # heuristic
    for p in web_dir.rglob("*.ts*"):
        try:
            txt = _read(p)
        except Exception:
            continue
        if "createRoot" in txt or "ReactDOM" in txt:
            return p
    return None


def _patch_web_entrypoint(p: Path, receipt: dict) -> None:
    txt = _read(p)
    if "workspaceFetch" in txt:
        return
    # Add side-effect import near top
    import_line = 'import "./workspace/workspaceFetch";\n'
    if re.search(r"^import .*\n", txt, flags=re.M):
        txt = re.sub(r"^(import .*\n)+", lambda m: m.group(0) + import_line, txt, count=1, flags=re.M)
    else:
        txt = import_line + txt

    _backup_file(p, receipt)
    _write(p, txt)
    receipt.setdefault("patched", []).append(str(p.as_posix()))


def _append_docs(repo: Path, receipt: dict) -> None:
    feature_catalog = repo / "docs" / "FEATURE_CATALOG.md"
    project_scope = repo / "docs" / "PROJECT_SCOPE.md"

    if feature_catalog.exists():
        txt = _read(feature_catalog)
        if FEATURE_ID not in txt:
            _backup_file(feature_catalog, receipt)
            txt += (
                "\n\n---\n\n"
                f"## {FEATURE_ID}\n\n"
                "**Goal:** True multi-workspace/team support with RBAC and strict data isolation.\n\n"
                "**Adds:**\n"
                "- Workspace entities (workspace_id, name, owner, created_at)\n"
                "- Roles: owner, admin, member, viewer\n"
                "- Workspace-bound sessions, chats, memory, autonomy jobs, API tokens\n"
                "- Access enforcement on /api routes\n"
                "- Web UI header workspace switcher + current workspace badge\n"
                "- Admin endpoints: invite, role change, revoke\n"
                "- Cross-workspace reads/writes denied by default (ORM scoping + route enforcement)\n\n"
                "**Migration note:** existing installs get a default workspace "
                "`00000000-0000-0000-0000-000000000001` named **Personal**; existing rows are backfilled.\n"
            )
            _write(feature_catalog, txt)
            receipt.setdefault("patched", []).append(str(feature_catalog.as_posix()))

    if project_scope.exists():
        txt = _read(project_scope)
        marker = f"<!-- {FEATURE_ID} -->"
        if marker not in txt:
            _backup_file(project_scope, receipt)
            txt += (
                "\n\n---\n\n"
                "### Mission impact: Multi-workspace isolation\n\n"
                "Thomas now supports true multi-tenant workspaces with role-based access control and strict data isolation. "
                "All workspace-bound resources (sessions, chats, memory, autonomy jobs, API tokens) are scoped to a workspace by default. "
                "This enables teams to safely share a Thomas instance without cross-team leakage.\n"
                f"\n{marker}\n"
            )
            _write(project_scope, txt)
            receipt.setdefault("patched", []).append(str(project_scope.as_posix()))


def apply() -> None:
    repo = Path.cwd()
    receipt = {"feature_id": FEATURE_ID, "applied_at": _now(), "patched": [], "backups": []}

    entry = _find_fastapi_entrypoint(repo)
    if not entry:
        raise RuntimeError("Could not locate FastAPI entrypoint under server/.")
    _patch_fastapi_entrypoint(entry, receipt)

    header = _find_web_header(repo)
    if header:
        _patch_web_header(header, receipt)

    entry_tsx = _find_web_entrypoint(repo)
    if entry_tsx:
        _patch_web_entrypoint(entry_tsx, receipt)

    _append_docs(repo, receipt)

    _save_receipt(receipt)
    print(f"Applied {FEATURE_ID}. Backups in {BACKUP_DIR.as_posix()}")


def rollback() -> None:
    receipt = _load_receipt()
    if not receipt:
        raise RuntimeError(f"No receipt found at {RECEIPT_PATH.as_posix()}")

    restored = 0
    for rel in receipt.get("backups", []):
        src = BACKUP_DIR / rel
        dst = Path(rel)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored += 1

    print(f"Restored {restored} files from backups. Feature files added by the pack remain on disk.")
    print("If you're using git, the cleanest rollback is `git reset --hard` to the pre-apply commit.")


def verify() -> None:
    from server.workspace.verify_install import main as verify_main  # local import for faster apply

    verify_main()


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m server.workspace.feature_install [apply|verify|rollback]")
        raise SystemExit(2)
    cmd = sys.argv[1].strip().lower()
    if cmd == "apply":
        apply()
    elif cmd == "verify":
        verify()
    elif cmd == "rollback":
        rollback()
    else:
        print("Unknown command:", cmd)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
