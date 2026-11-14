"""Inspect the actual Build scripts loaded by Chat without assuming function ownership."""

import re
from pathlib import Path


def read_code_sources(web_js: Path) -> str:
    html = (web_js.parent / "chat.html").read_text(encoding="utf-8")
    names = re.findall(r'<script src="/static/js/(unified_code_[^?"/]+\.js)(?:\?[^"<>]*)?"></script>', html)
    assert names, "Chat does not load any Build scripts"
    return "\n".join((web_js / name).read_text(encoding="utf-8") for name in names)


def code_function_body(web_js: Path, name: str) -> str:
    source = read_code_sources(web_js)
    header = re.search(r"^([ \t]*)(?:async )?function " + re.escape(name) + r"\b", source, re.M)
    assert header, f"Build function {name} was not found in loaded scripts"
    # Match the function's own indentation, not a nested arrow/function body.
    return re.split(r"\n" + re.escape(header[1]) + r"\}(?:[;\n]|$)", source[header.end() :], maxsplit=1)[0]
