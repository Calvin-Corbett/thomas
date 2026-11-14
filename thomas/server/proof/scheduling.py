"""Balance proof shards without changing the selected files or the pool's capacity."""

from __future__ import annotations

import ast
import hashlib
import math
import statistics
import threading
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path

_lock = threading.Lock()
_costs: dict[tuple[str, bytes], tuple[float, int]] = {}
_MAX_COSTS = 4096


def _source(tree: Path, rel: str) -> bytes:
    try:
        return (tree / rel.split("::", 1)[0]).read_bytes()
    except OSError:
        return b""


def _key(rel: str, source: bytes) -> tuple[str, bytes]:
    return rel, hashlib.sha256(source).digest()


def _definitions(source: bytes) -> int:
    try:
        nodes = ast.walk(ast.parse(source))
        count = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test") for n in nodes)
    except (SyntaxError, ValueError, RecursionError):
        count = 1
    return max(1, count)


def estimate(tree: Path, rel: str) -> float:
    """Use measured seconds, scaling cold definition counts by the median learned rate."""
    source = _source(tree, rel)
    with _lock:
        measured = _costs.get(_key(rel, source))
        rates = [seconds / definitions for seconds, definitions in _costs.values()]
    if measured is not None:
        return measured[0]
    # Before any measurements, one second per definition is only a relative ranking hint.
    return _definitions(source) * (statistics.median(rates) if rates else 1.0)


def batches(tree: Path, files: Sequence[str], *, size: int, workers: int, spread: bool = True) -> list[tuple[str, ...]]:
    """Balance bounded shards, then submit the heaviest completed groups first.

    With *spread* the files go out over at least *workers* shards, so idle CPUs share them. Without it, only as many
    shards as *size* needs: on a PC already at its load limit, every extra shard is one more pytest start (~4 CPU-s,
    measured 2026-11-06) competing for the same busy CPUs, not more work done at once.
    """
    if workers <= 1 or size <= 1:
        return [tuple(files[i : i + size]) for i in range(0, len(files), size)]
    costs = {rel: estimate(tree, rel) for rel in files}
    ranked = sorted(enumerate(files), key=lambda item: (-costs[item[1]], item[0]))
    needed = math.ceil(len(files) / size)
    count = min(len(files), max(needed, workers) if spread else needed)
    groups: list[list[str]] = [[] for _ in range(count)]
    totals = [0.0] * count
    for _index, rel in ranked:
        candidates = [i for i, group in enumerate(groups) if len(group) < size]
        index = min(candidates, key=lambda i: (totals[i], len(groups[i]), i))
        groups[index].append(rel)
        totals[index] += costs[rel]
    ordered = sorted(range(len(groups)), key=lambda i: (-totals[i], i))
    return [tuple(groups[i]) for i in ordered if groups[i]]


def snapshot(tree: Path, files: Sequence[str]) -> dict[str, bytes]:
    """Capture the source fingerprints before a shard starts."""
    return {rel: _key(rel, _source(tree, rel))[1] for rel in files}


def learn(tree: Path, files: Sequence[str], report: Path, *, sources: Mapping[str, bytes] | None = None) -> None:
    """Remember per-file JUnit case time only as a scheduling hint, never as proof."""
    try:
        root = ET.parse(report).getroot()
        totals: dict[str, float] = {}
        allowed = set(files)
        invalid: set[str] = set()
        for case in root.iter("testcase"):
            module = case.get("classname", "").replace(".", "/")
            matches = [name for name in files if module == name[:-3] or module.startswith(name[:-3] + "/")]
            rel = max(matches, key=len, default="") or case.get("file", "").replace("\\", "/")
            if rel not in allowed:
                continue
            try:
                seconds = float(case.get("time", ""))
            except ValueError:
                invalid.add(rel)
                continue
            if math.isfinite(seconds) and seconds >= 0:
                total = totals.get(rel, 0.0) + seconds
                if math.isfinite(total):
                    totals[rel] = total
                else:
                    invalid.add(rel)
            elif rel in allowed:
                invalid.add(rel)
        with _lock:
            for rel, seconds in totals.items():
                key = _key(rel, _source(tree, rel))
                if rel not in invalid and (sources is None or sources.get(rel) == key[1]):
                    _costs[key] = (seconds, _definitions(_source(tree, rel)))
            while len(_costs) > _MAX_COSTS:
                _costs.pop(next(iter(_costs)))
    except (OSError, ValueError, ET.ParseError):
        return
