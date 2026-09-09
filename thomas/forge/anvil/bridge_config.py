"""Emergency stop kill-switch and TOML-loaded BridgeConfig for the evolve claude bridge."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def emergency_stop_path() -> Path:
    return Path(os.path.expanduser("~")) / ".thomas" / "evolve" / "claude_bridge.STOP"


def emergency_stop_active() -> bool:
    """A simple, always-checked kill switch: presence of the STOP file aborts dispatch."""
    try:
        return emergency_stop_path().exists()
    except OSError:
        return False


@dataclass
class BridgeConfig:
    enabled: bool = False  # master switch — OFF by default
    require_confirmation: bool = True  # require explicit human confirm before any keystroke
    window_match: str = "Claude Code"  # only type into a window whose title contains this
    branch_only: bool = True  # the typed prompt instructs build-on-branch, never merge
    max_prompt_chars: int = 8000  # refuse to type an unreasonably large blob

    @classmethod
    def load(cls, project_root: Path | None = None) -> BridgeConfig:
        import tomllib

        root = Path(project_root) if project_root is not None else Path.cwd()
        table: dict = {}
        try:
            p = root / "thomas.toml"
            if p.is_file():
                data = tomllib.loads(p.read_text(encoding="utf-8"))
                table = dict((data.get("evolve", {}) or {}).get("claude_bridge", {}) or {})
        except (OSError, tomllib.TOMLDecodeError):
            table = {}
        base = cls()
        cfg = cls(
            enabled=bool(table.get("enabled", base.enabled)),
            require_confirmation=bool(table.get("require_confirmation", base.require_confirmation)),
            window_match=str(table.get("window_match", base.window_match)),
            branch_only=bool(table.get("branch_only", base.branch_only)),
            max_prompt_chars=int(table.get("max_prompt_chars", base.max_prompt_chars)),
        )
        # Env override (handy for an operator to flip on for one run).
        if os.environ.get("THOMAS_CLAUDE_BRIDGE_ENABLED"):
            cfg.enabled = os.environ["THOMAS_CLAUDE_BRIDGE_ENABLED"].strip().lower() not in ("0", "false", "no", "")
        return cfg
