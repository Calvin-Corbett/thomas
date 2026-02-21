"""Lines of Code Tracker for Thomas.

Provides real-time LOC metrics for the codebase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json


@dataclass
class LOCStats:
    """Lines of code statistics."""
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    file_count: int
    by_extension: Dict[str, int]
    by_directory: Dict[str, int]
    timestamp: str
    
    def to_dict(self) -> Dict:
        return {
            "total_lines": self.total_lines,
            "code_lines": self.code_lines,
            "comment_lines": self.comment_lines,
            "blank_lines": self.blank_lines,
            "file_count": self.file_count,
            "by_extension": self.by_extension,
            "by_directory": self.by_directory,
            "timestamp": self.timestamp,
        }


# Extensions to count
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt",
    ".sh", ".bat", ".cmd", ".ps1",
    ".sql", ".prisma",
}

# Directories to skip
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "node_modules", ".idea", ".vscode", "dist", "build",
    "*.egg-info", ".mypy_cache", ".ruff_cache",
    "runtime", "library", "tasks", "output",
}


def should_count_file(path: Path, root: Path) -> bool:
    """Check if a file should be counted."""
    # Check extension
    if path.suffix.lower() not in CODE_EXTENSIONS:
        return False
    
    # Check if in skipped directory
    rel_path = path.relative_to(root)
    for part in rel_path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return False
        if part.startswith(".") and part not in {".github", ".thomas"}:
            return False
    
    return True


def count_file_lines(path: Path) -> tuple[int, int, int]:
    """Count lines in a file. Returns (total, code, comments, blank)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return 0, 0, 0
    
    total = len(lines)
    code = 0
    comments = 0
    blank = 0
    
    in_multiline_comment = False
    ext = path.suffix.lower()
    
    for line in lines:
        stripped = line.strip()
        
        # Blank line
        if not stripped:
            blank += 1
            continue
        
        # Python multiline comments
        if ext == ".py":
            if '"""' in stripped or "'''" in stripped:
                in_multiline_comment = not in_multiline_comment
                comments += 1
                continue
            if in_multiline_comment:
                comments += 1
                continue
            if stripped.startswith("#"):
                comments += 1
                continue
        
        # JS/TS comments
        if ext in {".js", ".ts", ".tsx", ".jsx"}:
            if stripped.startswith("//"):
                comments += 1
                continue
            if stripped.startswith("/*") or stripped.endswith("*/"):
                comments += 1
                continue
        
        # CSS comments
        if ext in {".css", ".scss"}:
            if stripped.startswith("/*") or stripped.endswith("*/"):
                comments += 1
                continue
        
        # Shell comments
        if ext in {".sh", ".bash", ".zsh"}:
            if stripped.startswith("#"):
                comments += 1
                continue
        
        code += 1
    
    return total, code, comments, blank


def count_loc(root: Optional[Path] = None) -> LOCStats:
    """Count lines of code in the project."""
    if root is None:
        # Find project root (where pyproject.toml is)
        current = Path.cwd()
        while current.parent != current:
            if (current / "pyproject.toml").exists():
                root = current
                break
            current = current.parent
        if root is None:
            root = Path.cwd()
    
    total_lines = 0
    code_lines = 0
    comment_lines = 0
    blank_lines = 0
    file_count = 0
    by_extension: Dict[str, int] = {}
    by_directory: Dict[str, int] = {}
    
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not should_count_file(path, root):
            continue
        
        total, code, comments, blank = count_file_lines(path)
        if total == 0:
            continue
        
        total_lines += total
        code_lines += code
        comment_lines += comments
        blank_lines += blank
        file_count += 1
        
        # By extension
        ext = path.suffix.lower() or ".no_ext"
        by_extension[ext] = by_extension.get(ext, 0) + code
        
        # By top-level directory
        rel_path = path.relative_to(root)
        top_dir = rel_path.parts[0] if len(rel_path.parts) > 1 else "root"
        by_directory[top_dir] = by_directory.get(top_dir, 0) + code
    
    return LOCStats(
        total_lines=total_lines,
        code_lines=code_lines,
        comment_lines=comment_lines,
        blank_lines=blank_lines,
        file_count=file_count,
        by_extension=dict(sorted(by_extension.items(), key=lambda x: -x[1])),
        by_directory=dict(sorted(by_directory.items(), key=lambda x: -x[1])),
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


# Singleton for caching
_cached_stats: Optional[LOCStats] = None
_cache_time: Optional[float] = None
CACHE_TTL_SECONDS = 60  # Refresh every minute


def get_loc_stats(force_refresh: bool = False) -> LOCStats:
    """Get LOC stats with caching."""
    global _cached_stats, _cache_time
    
    import time
    now = time.time()
    
    if force_refresh or _cached_stats is None or _cache_time is None or (now - _cache_time) > CACHE_TTL_SECONDS:
        _cached_stats = count_loc()
        _cache_time = now
    
    return _cached_stats


# FastAPI integration
def create_loc_api():
    """Create FastAPI router for LOC API."""
    from fastapi import APIRouter
    
    router = APIRouter(prefix="/api/loc", tags=["loc"])
    
    @router.get("")
    async def get_loc():
        """Get current lines of code stats."""
        stats = get_loc_stats()
        return stats.to_dict()
    
    @router.post("/refresh")
    async def refresh_loc():
        """Force refresh LOC stats."""
        stats = get_loc_stats(force_refresh=True)
        return stats.to_dict()
    
    return router


# CLI entry point
def main():
    """CLI entry point for LOC counter."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Count lines of code")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--watch", action="store_true", help="Watch mode (refresh every 5s)")
    args = parser.parse_args()
    
    if args.watch:
        import time
        try:
            while True:
                stats = get_loc_stats(force_refresh=True)
                print(f"\rLOC: {stats.code_lines:,} code lines in {stats.file_count} files", end="", flush=True)
                time.sleep(5)
        except KeyboardInterrupt:
            print()
    else:
        stats = get_loc_stats(force_refresh=True)
        
        if args.json:
            print(json.dumps(stats.to_dict(), indent=2))
        else:
            print(f"Lines of Code Report")
            print(f"=" * 40)
            print(f"Total lines:    {stats.total_lines:,}")
            print(f"Code lines:     {stats.code_lines:,}")
            print(f"Comment lines:  {stats.comment_lines:,}")
            print(f"Blank lines:    {stats.blank_lines:,}")
            print(f"Files:          {stats.file_count:,}")
            print()
            print("By Extension:")
            for ext, count in list(stats.by_extension.items())[:10]:
                print(f"  {ext:12} {count:,}")
            print()
            print("By Directory:")
            for dir_name, count in list(stats.by_directory.items())[:10]:
                print(f"  {dir_name:20} {count:,}")


if __name__ == "__main__":
    main()
