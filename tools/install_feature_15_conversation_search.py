# tools/install_feature_15_conversation_search.py
"""
Feature 15 installer: Conversation Search (v4)

What it patches:
- Adds search router include to the FastAPI app
- Mounts /static if missing
- Adds a startup warmup that syncs search index from persistence
- Injects search overlay JS/CSS into a likely base template

Conservative behavior:
- Creates *.bak backups
- Only inserts when not already present
- Searches under thomas/server for FastAPI entrypoints and templates

Run from repo root:
  python tools/install_feature_15_conversation_search.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path.cwd()

ROUTER_IMPORT = "from thomas.server.routes.search import router as search_router"
ROUTER_INCLUDE = "app.include_router(search_router)"

STATIC_IMPORT = "from fastapi.staticfiles import StaticFiles"
STATIC_MOUNT = "app.mount('/static', StaticFiles(directory='thomas/server/web/static'), name='static')"

WARMUP_IMPORT = "from thomas.core.search_history import get_search as _get_search"
WARMUP_BLOCK = """
@app.on_event("startup")
def _search_warmup():
    try:
        _get_search().sync_from_persistence()
    except Exception:
        pass
""".strip()

CSS_TAG = '<link rel="stylesheet" href="/static/search_overlay.css">'
JS_TAG = '<script defer src="/static/search_overlay.js"></script>'


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        bak.write_bytes(path.read_bytes())


def patch_app_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False

    if ROUTER_IMPORT not in text:
        m = re.search(r"^from fastapi[^\n]*\n", text, re.M)
        if m:
            insert_at = m.end()
            text = text[:insert_at] + ROUTER_IMPORT + "\n" + text[insert_at:]
        else:
            text = ROUTER_IMPORT + "\n" + text
        changed = True

    if STATIC_IMPORT not in text:
        m = re.search(r"^from fastapi[^\n]*\n", text, re.M)
        if m:
            insert_at = m.end()
            text = text[:insert_at] + STATIC_IMPORT + "\n" + text[insert_at:]
        else:
            text = STATIC_IMPORT + "\n" + text
        changed = True

    if WARMUP_IMPORT not in text:
        m = re.search(r"^from thomas[^\n]*\n", text, re.M)
        if m:
            insert_at = m.end()
            text = text[:insert_at] + WARMUP_IMPORT + "\n" + text[insert_at:]
        else:
            text = WARMUP_IMPORT + "\n" + text
        changed = True

    if ROUTER_INCLUDE not in text or STATIC_MOUNT not in text:
        m = re.search(r"^\s*app\s*=\s*FastAPI\([^\)]*\)\s*$", text, re.M)
        if m:
            insert_at = m.end()
            inject = ""
            if ROUTER_INCLUDE not in text:
                inject += "\n" + ROUTER_INCLUDE
            if STATIC_MOUNT not in text:
                inject += "\n" + STATIC_MOUNT
            if inject:
                text = text[:insert_at] + inject + "\n" + text[insert_at:]
                changed = True

    if "_search_warmup" not in text and "sync_from_persistence" not in text:
        text = text.rstrip() + "\n\n" + WARMUP_BLOCK + "\n"
        changed = True

    if changed:
        backup(path)
        path.write_text(text, encoding="utf-8")

    return changed


def find_app_candidates() -> list[Path]:
    server_dir = REPO / "thomas" / "server"
    if not server_dir.exists():
        return []

    py_files = list(server_dir.rglob("*.py"))

    preferred = []
    for p in py_files:
        if p.name.lower() in ("app.py", "main.py", "server.py"):
            preferred.append(p)

    fastapi_files = []
    for p in py_files:
        try:
            t = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "FastAPI(" in t and re.search(r"^\s*app\s*=\s*FastAPI\(", t, re.M):
            fastapi_files.append(p)

    out = []
    seen = set()
    for p in preferred + fastapi_files:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def patch_template(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False

    if CSS_TAG not in text:
        if "</head>" in text:
            text = text.replace("</head>", f"  {CSS_TAG}\n</head>")
        else:
            text = CSS_TAG + "\n" + text
        changed = True

    if JS_TAG not in text:
        if "</body>" in text:
            text = text.replace("</body>", f"  {JS_TAG}\n</body>")
        else:
            text = text + "\n" + JS_TAG + "\n"
        changed = True

    if changed:
        backup(path)
        path.write_text(text, encoding="utf-8")

    return changed


def find_template_candidates() -> list[Path]:
    web_dir = REPO / "thomas" / "server" / "web"
    if not web_dir.exists():
        return []
    patterns = ["base.html", "layout.html", "index.html", "chat.html"]
    out: list[Path] = []
    for pat in patterns:
        out.extend(list(web_dir.rglob(pat)))
    if not out:
        out = list(web_dir.rglob("*.html"))
    uniq = []
    seen = set()
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main() -> None:
    print("== Feature 15 installer: Conversation Search (v4) ==")
    print(f"Repo: {REPO}")

    app_candidates = find_app_candidates()
    if not app_candidates:
        print("[WARN] No FastAPI app entrypoints found under thomas/server.")
        print("Manual additions needed:")
        print(f"  - {ROUTER_IMPORT}")
        print(f"  - {ROUTER_INCLUDE}")
        print(f"  - {STATIC_IMPORT}")
        print(f"  - {STATIC_MOUNT}")
        print("  - optional: call get_search().sync_from_persistence() at startup")
    else:
        patched = False
        for c in app_candidates[:10]:
            if patch_app_file(c):
                print(f"[OK] Patched app file: {c}")
                patched = True
                break
        if not patched:
            print("[INFO] App already had required lines (or couldn't patch safely).")

    tmpl_candidates = find_template_candidates()
    if not tmpl_candidates:
        print("[WARN] No templates found under thomas/server/web.")
        print("Ensure your HTML includes:")
        print(f"  - {CSS_TAG}")
        print(f"  - {JS_TAG}")
    else:
        patched = False
        for t in tmpl_candidates[:15]:
            if patch_template(t):
                print(f"[OK] Patched template: {t}")
                patched = True
                break
        if not patched:
            print("[INFO] Template already had required CSS/JS includes (or couldn't patch safely).")

    print("Done. Backups saved as *.bak for modified files.")


if __name__ == "__main__":
    main()
