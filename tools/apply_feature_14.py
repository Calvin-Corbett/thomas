#!/usr/bin/env python3
"""Feature 14 v3 installer/patcher.

Wires:
- FastAPI router include for spend routes
- Injects widget CSS/JS into HTML templates in thomas/server/web

Usage:
  python tools/apply_feature_14.py
  python tools/apply_feature_14.py /path/to/repo
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER_PY = "# --- feature14: spend dashboard ---"
MARKER_HTML = "<!-- feature14: spend widget -->"


def die(msg: str) -> None:
    print(f"[feature14] ERROR: {msg}")
    sys.exit(1)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def find_repo_root(arg: str | None) -> Path:
    root = Path(arg).expanduser().resolve() if arg else Path.cwd().resolve()
    if not (root / "thomas").exists():
        die(f"Could not find 'thomas/' under {root}. Run from repo root or pass the repo path.")
    return root


def find_fastapi_app_file(root: Path) -> Path | None:
    candidates = [
        root / "thomas" / "server" / "app.py",
        root / "thomas" / "server" / "main.py",
        root / "thomas" / "server" / "server.py",
    ]
    for p in candidates:
        if p.exists():
            txt = read(p)
            if "FastAPI(" in txt and re.search(r"^\s*app\s*=", txt, flags=re.M):
                return p

    for p in (root / "thomas" / "server").rglob("*.py"):
        try:
            txt = read(p)
        except Exception:
            continue
        if re.search(r"^\s*app\s*=\s*FastAPI\s*\(", txt, flags=re.M):
            return p
    return None


def patch_fastapi_app(app_file: Path) -> bool:
    txt = read(app_file)
    if MARKER_PY in txt:
        print(f"[feature14] FastAPI app already patched: {app_file}")
        return False

    import_line = "from thomas.server.routes.spend import router as spend_router"
    include_line = "app.include_router(spend_router)"

    lines = txt.splitlines()
    last_import = -1
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            last_import = i
    insert_idx = last_import + 1 if last_import >= 0 else 0

    if import_line not in txt:
        lines.insert(insert_idx, import_line + "  " + MARKER_PY)
    else:
        lines.insert(insert_idx, MARKER_PY)

    txt2 = "\n".join(lines)

    # Insert include_router after FastAPI() assignment if present
    m = re.search(r"^\s*app\s*=\s*FastAPI\s*\(.*?\)\s*$", txt2, flags=re.M)
    if m and include_line not in txt2:
        idx = m.end()
        txt2 = txt2[:idx] + "\n" + include_line + "\n" + txt2[idx:]
    elif include_line not in txt2:
        txt2 = txt2 + "\n\n" + include_line + "\n"

    write(app_file, txt2)
    print(f"[feature14] Patched FastAPI app include_router: {app_file}")
    return True


def patch_html_files(root: Path) -> int:
    web = root / "thomas" / "server" / "web"
    if not web.exists():
        print("[feature14] No thomas/server/web directory found; skipping HTML patch.")
        return 0

    injected = 0
    for p in web.rglob("*.html"):
        try:
            txt = read(p)
        except Exception:
            continue
        if MARKER_HTML in txt:
            continue
        if re.search(r"</head\s*>", txt, flags=re.I) is None:
            continue

        snippet = (
            "\n  " + MARKER_HTML + "\n"
            '  <link rel="stylesheet" href="/api/spend/widget.css">\n'
            '  <script defer src="/api/spend/widget.js"></script>\n'
        )
        new_txt = re.sub(r"</head\s*>", snippet + "</head>", txt, flags=re.I, count=1)
        if new_txt != txt:
            write(p, new_txt)
            injected += 1

    print(f"[feature14] HTML injection: {injected} file(s) updated.")
    return injected


def main() -> None:
    root = find_repo_root(sys.argv[1] if len(sys.argv) > 1 else None)

    required = [
        root / "thomas" / "core" / "cost_tracker.py",
        root / "thomas" / "server" / "routes" / "spend.py",
        root / "thomas" / "server" / "web" / "spend_widget.js",
        root / "thomas" / "server" / "web" / "spend_widget.css",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        die("Missing files. Did you unzip into repo root?\n" + "\n".join(f"  - {m}" for m in missing))

    app_file = find_fastapi_app_file(root)
    if app_file is None:
        print("[feature14] Could not locate FastAPI app file automatically.")
        print("[feature14] Manually add:")
        print("  from thomas.server.routes.spend import router as spend_router")
        print("  app.include_router(spend_router)")
    else:
        patch_fastapi_app(app_file)

    patch_html_files(root)

    print("[feature14] Done.")
    print("[feature14] Verify: GET /api/spend/today and check the web UI badge.")
    print("[feature14] Tip: use CostTracker.record_from_any(model, provider, response) to wire faster.")


if __name__ == "__main__":
    main()
