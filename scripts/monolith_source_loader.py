from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _core_fallback_path(base: Path) -> Path:
    return base.with_name(f"{base.stem}_core{base.suffix}")


def load_monolith_source(
    base_path: Path | str,
    part_files: Iterable[str],
    *,
    namespace: dict[str, object] | None = None,
    encoding: str = "utf-8",
) -> None:
    """Load split source fragments into a single runtime module namespace."""

    ns = namespace if namespace is not None else {}
    base = Path(base_path)
    core_fallback = _core_fallback_path(base)
    chunks: list[str] = []
    for part in part_files:
        path = base.with_name(str(part))
        try:
            chunks.append(path.read_text(encoding=encoding))
        except FileNotFoundError:
            if core_fallback.exists():
                source = core_fallback.read_text(encoding=encoding)
                exec(compile(source, str(core_fallback), "exec"), ns, ns)
                return
            raise
    source = "\n".join(chunks)
    try:
        exec(compile(source, str(base), "exec"), ns, ns)
    except SyntaxError:
        if core_fallback.exists():
            fallback_source = core_fallback.read_text(encoding=encoding)
            exec(compile(fallback_source, str(core_fallback), "exec"), ns, ns)
            return
        raise
