from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_vf.tools.base import Tool, ToolRegistry


def _safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if not str(p).startswith(str(root.resolve())):
        raise ValueError("path escapes fs_root")
    return p

def register(reg: ToolRegistry, fs_root: str) -> None:
    root = Path(fs_root)
    root.mkdir(parents=True, exist_ok=True)

    def read(args: dict[str, Any]) -> dict[str, Any]:
        path = _safe_path(root, args["path"])
        if not path.exists():
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "text": path.read_text(encoding="utf-8", errors="replace")}

    def write(args: dict[str, Any]) -> dict[str, Any]:
        path = _safe_path(root, args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.get("text",""), encoding="utf-8")
        return {"ok": True}

    reg.register(Tool(
        name="fs.read",
        description="Read a UTF-8 text file within the agent sandbox.",
        schema={"type":"object","properties":{"path":{"type":"string"}}, "required":["path"]},
        handler=read
    ))
    reg.register(Tool(
        name="fs.write",
        description="Write a UTF-8 text file within the agent sandbox.",
        schema={"type":"object","properties":{"path":{"type":"string"},"text":{"type":"string"}}, "required":["path","text"]},
        handler=write
    ))
