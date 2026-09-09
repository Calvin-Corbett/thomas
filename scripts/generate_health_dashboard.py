#!/usr/bin/env python3
"""Generate an HTML health dashboard for the Thomas repo.

Scans the codebase and produces a standalone HTML file showing:
- Module health status (from _architecture.py)
- File size violations and warnings
- Safety hook coverage
- Broad exception handler count
- Recent changes

Usage:
    python scripts/generate_health_dashboard.py
    # Opens: output/repo_health.html
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

PYTHON_SOFT_LIMIT = 800
PYTHON_HARD_LIMIT = 1200
JS_SOFT_LIMIT = 800
JS_HARD_LIMIT = 2000

SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    ".next",
}


def _scan_python_files() -> list[dict]:
    """Scan all Python files under thomas/ for size and exception issues."""
    results = []
    thomas_dir = ROOT / "thomas"
    if not thomas_dir.exists():
        return results

    for py_file in thomas_dir.rglob("*.py"):
        if any(part in SKIP_DIRS for part in py_file.parts):
            continue

        rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        lines = len(content.splitlines())
        broad_except_count = 0

        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if (
                        node.type is None
                        or isinstance(node.type, ast.Name)
                        and node.type.id in ("Exception", "BaseException")
                    ):
                        broad_except_count += 1
        except SyntaxError:
            pass

        status = "ok"
        if lines > PYTHON_HARD_LIMIT:
            status = "critical"
        elif lines > PYTHON_SOFT_LIMIT:
            status = "warning"

        results.append(
            {
                "path": rel,
                "lines": lines,
                "status": status,
                "broad_exceptions": broad_except_count,
            }
        )

    return sorted(results, key=lambda x: -x["lines"])


def _count_hooks() -> int:
    """Count pre-commit hooks."""
    config_path = ROOT / ".pre-commit-config.yaml"
    if not config_path.exists():
        return 0
    import re

    content = config_path.read_text(encoding="utf-8")
    return len(re.findall(r"^\s+-\s+id:\s+", content, re.MULTILINE))


def _module_health() -> list[dict]:
    """Extract module health from _architecture.py."""
    arch_path = ROOT / "thomas" / "_architecture.py"
    if not arch_path.exists():
        return []

    content = arch_path.read_text(encoding="utf-8")

    # Simple extraction of MODULES dict
    modules = []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MODULES":
                        if isinstance(node.value, ast.Dict):
                            for key, val in zip(node.value.keys, node.value.values):
                                if isinstance(key, ast.Constant) and isinstance(val, ast.Dict):
                                    mod = {"name": key.value}
                                    for k2, v2 in zip(val.keys, val.values):
                                        if isinstance(k2, ast.Constant) and isinstance(v2, ast.Constant):
                                            mod[k2.value] = v2.value
                                    modules.append(mod)
    except SyntaxError:
        pass

    return modules


def generate_dashboard() -> str:
    """Generate the complete HTML dashboard."""
    files = _scan_python_files()
    hook_count = _count_hooks()
    modules = _module_health()

    total_files = len(files)
    total_lines = sum(f["lines"] for f in files)
    critical_files = [f for f in files if f["status"] == "critical"]
    warning_files = [f for f in files if f["status"] == "warning"]
    [f for f in files if f["status"] == "ok"]
    total_broad_exceptions = sum(f["broad_exceptions"] for f in files)

    [m for m in modules if m.get("health") == "green"]
    [m for m in modules if m.get("health") == "yellow"]
    [m for m in modules if m.get("health") == "red"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Thomas Repo Health Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
  .header {{ text-align: center; margin-bottom: 32px; }}
  .header h1 {{ font-size: 28px; font-weight: 700; color: #f8fafc; }}
  .header .subtitle {{ color: #94a3b8; margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .card .label {{ color: #94a3b8; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card .value {{ font-size: 32px; font-weight: 700; margin-top: 4px; }}
  .card .value.green {{ color: #4ade80; }}
  .card .value.yellow {{ color: #facc15; }}
  .card .value.red {{ color: #f87171; }}
  .card .value.blue {{ color: #60a5fa; }}
  .section {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #334155; }}
  .section h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #f8fafc; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; padding: 8px 12px; color: #94a3b8; font-size: 12px; text-transform: uppercase; border-bottom: 1px solid #334155; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; font-size: 14px; }}
  tr:hover {{ background: #334155; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 12px; font-weight: 600; }}
  .badge.ok {{ background: #166534; color: #4ade80; }}
  .badge.warning {{ background: #713f12; color: #facc15; }}
  .badge.critical {{ background: #7f1d1d; color: #f87171; }}
  .badge.green {{ background: #166534; color: #4ade80; }}
  .badge.yellow {{ background: #713f12; color: #facc15; }}
  .badge.red {{ background: #7f1d1d; color: #f87171; }}
  .module-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
  .module-card {{ background: #0f172a; border-radius: 8px; padding: 14px; border: 1px solid #334155; }}
  .module-card .name {{ font-weight: 600; font-size: 15px; }}
  .module-card .desc {{ color: #94a3b8; font-size: 13px; margin-top: 4px; }}
  .module-card .debt {{ color: #fb923c; font-size: 12px; margin-top: 6px; }}
  .progress-bar {{ height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 8px; }}
  .progress-fill {{ height: 100%; border-radius: 4px; }}
  .footer {{ text-align: center; color: #64748b; font-size: 13px; margin-top: 32px; }}
</style>
</head>
<body>
<div class="header">
  <h1>Thomas Repo Health</h1>
  <div class="subtitle">Generated {now}</div>
</div>

<div class="grid">
  <div class="card">
    <div class="label">Python Files</div>
    <div class="value blue">{total_files}</div>
  </div>
  <div class="card">
    <div class="label">Total Lines</div>
    <div class="value blue">{total_lines:,}</div>
  </div>
  <div class="card">
    <div class="label">Pre-commit Hooks</div>
    <div class="value green">{hook_count}</div>
  </div>
  <div class="card">
    <div class="label">Over Size Limit</div>
    <div class="value {"red" if critical_files else "green"}">{len(critical_files)}</div>
  </div>
  <div class="card">
    <div class="label">Approaching Limit</div>
    <div class="value {"yellow" if warning_files else "green"}">{len(warning_files)}</div>
  </div>
  <div class="card">
    <div class="label">Broad Exceptions</div>
    <div class="value {"red" if total_broad_exceptions > 100 else "yellow" if total_broad_exceptions > 0 else "green"}">{total_broad_exceptions}</div>
  </div>
</div>

<div class="section">
  <h2>Module Health</h2>
  <div class="module-grid">
"""

    for mod in modules:
        health = mod.get("health", "unknown")
        badge_class = {"green": "green", "yellow": "yellow", "red": "red"}.get(health, "warning")
        desc = mod.get("description", "")
        debt = mod.get("debt", "")
        debt_html = f'<div class="debt">{debt[:120]}{"..." if len(debt) > 120 else ""}</div>' if debt else ""

        html += f"""    <div class="module-card">
      <div class="name">{mod["name"]} <span class="badge {badge_class}">{health}</span></div>
      <div class="desc">{desc}</div>
      {debt_html}
    </div>
"""

    html += """  </div>
</div>
"""

    # Files over limit
    if critical_files or warning_files:
        html += """<div class="section">
  <h2>Files Needing Attention</h2>
  <table>
    <thead><tr><th>File</th><th>Lines</th><th>Limit</th><th>Status</th></tr></thead>
    <tbody>
"""
        for f in (critical_files + warning_files)[:30]:
            badge = f["status"]
            limit = PYTHON_HARD_LIMIT if f["status"] == "critical" else PYTHON_SOFT_LIMIT
            html += f'      <tr><td>{f["path"]}</td><td>{f["lines"]}</td><td>{limit}</td><td><span class="badge {badge}">{badge}</span></td></tr>\n'
        html += """    </tbody>
  </table>
</div>
"""

    # Broad exception hotspots
    exception_files = sorted(
        [f for f in files if f["broad_exceptions"] > 0],
        key=lambda x: -x["broad_exceptions"],
    )
    if exception_files:
        html += """<div class="section">
  <h2>Broad Exception Hotspots</h2>
  <table>
    <thead><tr><th>File</th><th>Broad Catches</th><th>Lines</th></tr></thead>
    <tbody>
"""
        for f in exception_files[:20]:
            html += f"      <tr><td>{f['path']}</td><td>{f['broad_exceptions']}</td><td>{f['lines']}</td></tr>\n"
        html += """    </tbody>
  </table>
</div>
"""

    html += f"""
<div class="footer">
  Thomas Repo Health Dashboard | {total_files} files | {hook_count} hooks | Generated {now}
</div>
</body>
</html>"""

    return html


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate repo health dashboard.")
    parser.add_argument(
        "--output",
        default="output/repo_health.html",
        help="Output path for HTML dashboard (default: output/repo_health.html).",
    )
    args = parser.parse_args()

    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    html = generate_dashboard()
    output_path.write_text(html, encoding="utf-8")
    print(f"Dashboard generated: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
