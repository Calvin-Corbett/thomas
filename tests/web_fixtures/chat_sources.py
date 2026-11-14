"""Read the real script sources loaded by the Chat entry page for contracts."""

import re
from pathlib import Path


def read_chat_sources(page: Path) -> str:
    html = page.read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="/static/js/(chat_[^?"/]+\.js)(?:\?[^"<>]*)?"></script>', html)
    return "\n".join(
        [
            html,
            *[(page.parent / "js" / name).read_text(encoding="utf-8") for name in scripts],
        ]
    )
