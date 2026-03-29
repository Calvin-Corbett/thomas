from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = REPO_ROOT / "thomas" / "server" / "web" / "js" / "app.js"
APP_RUNTIME_PATH = REPO_ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_primary.mjs"
APP_PARTS_DIR = REPO_ROOT / "thomas" / "server" / "web" / "js" / "app_parts"
LAYOUT_CSS_PATH = REPO_ROOT / "thomas" / "server" / "web" / "css" / "layout.css"
LAYOUT_PARTS_DIR = REPO_ROOT / "thomas" / "server" / "web" / "css" / "layout_parts"


def _extract_part_names(loader_source: str) -> list[str]:
    block_match = re.search(r"const APP_PART_FILES = \[(.*?)\];", loader_source, flags=re.DOTALL)
    if not block_match:
        return []
    return re.findall(r'"([^"]+\.js)"', block_match.group(1))


def _decode_part_source(part_source: str) -> str:
    marker = "export default "
    start = part_source.find(marker)
    if start < 0:
        raise ValueError("unsupported app part format")

    payload = part_source[start + len(marker) :].strip()
    if payload.endswith(";"):
        payload = payload[:-1].strip()

    join_suffix = '.join("\\n")'
    if payload.endswith(join_suffix):
        array_text = payload[: -len(join_suffix)].strip()
        items = ast.literal_eval(array_text)
        return "\n".join(str(item) for item in items)

    if payload:
        return str(ast.literal_eval(payload))

    raise ValueError("unsupported app part format")


def read_app_js_source() -> str:
    source = APP_JS_PATH.read_text(encoding="utf-8")
    if "app_runtime_primary.mjs" in source and APP_RUNTIME_PATH.exists():
        return APP_RUNTIME_PATH.read_text(encoding="utf-8")
    if "APP_PART_FILES" not in source or not APP_PARTS_DIR.exists():
        return source

    names = _extract_part_names(source)
    if not names:
        return source

    chunks: list[str] = []
    for name in names:
        part_path = APP_PARTS_DIR / name
        if not part_path.exists():
            return source
        chunks.append(_decode_part_source(part_path.read_text(encoding="utf-8")))
    return "\n".join(chunks)


def read_layout_css_source() -> str:
    source = LAYOUT_CSS_PATH.read_text(encoding="utf-8")
    if "./layout_parts/" not in source or not LAYOUT_PARTS_DIR.exists():
        return source

    names = re.findall(r'@import url\("./layout_parts/([^"]+\.css)"\);', source)
    if not names:
        return source

    chunks: list[str] = []
    for name in names:
        part_path = LAYOUT_PARTS_DIR / name
        if not part_path.exists():
            return source
        part = part_path.read_text(encoding="utf-8")
        lines = part.splitlines()
        if lines and lines[0].startswith("/* layout.css lines "):
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines.pop()
        chunks.append("\n".join(lines))
    return "\n".join(chunks)
