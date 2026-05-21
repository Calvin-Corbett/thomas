from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_TEXT_SUFFIXES = {".md", ".py", ".txt", ".json", ".toml", ".yaml", ".yml", ".sh", ".ps1"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(text or "").lower())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _iter_text_files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved.is_dir():
            for child in resolved.rglob("*"):
                if not child.is_file() or child.suffix.lower() not in _TEXT_SUFFIXES:
                    continue
                key = str(child.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(child.resolve())
        elif resolved.is_file() and resolved.suffix.lower() in _TEXT_SUFFIXES:
            key = str(resolved).lower()
            if key not in seen:
                seen.add(key)
                out.append(resolved)
    return out


def build_no_copy_report(
    source_paths: list[Path], generated_paths: list[Path], *, ngram_size: int = 12
) -> dict[str, Any]:
    source_files = _iter_text_files(source_paths)
    generated_files = _iter_text_files(generated_paths)
    exact_matches: list[dict[str, str]] = []
    source_hashes: dict[str, list[str]] = {}
    source_ngrams: set[tuple[str, ...]] = set()

    for source in source_files:
        digest = _sha256_file(source)
        source_hashes.setdefault(digest, []).append(str(source))
        tokens = _word_tokens(_read_text(source))
        if len(tokens) < ngram_size:
            continue
        for index in range(0, len(tokens) - ngram_size + 1):
            source_ngrams.add(tuple(tokens[index : index + ngram_size]))

    contiguous_overlaps: list[dict[str, Any]] = []
    for generated in generated_files:
        digest = _sha256_file(generated)
        if digest in source_hashes:
            exact_matches.append(
                {
                    "generated": str(generated),
                    "source": source_hashes[digest][0],
                    "sha256": digest,
                }
            )
        tokens = _word_tokens(_read_text(generated))
        if len(tokens) < ngram_size:
            continue
        for index in range(0, len(tokens) - ngram_size + 1):
            window = tuple(tokens[index : index + ngram_size])
            if window not in source_ngrams:
                continue
            contiguous_overlaps.append(
                {
                    "generated": str(generated),
                    "phrase": " ".join(window),
                    "ngram_size": int(ngram_size),
                }
            )
            break

    return {
        "ok": not exact_matches and not contiguous_overlaps,
        "exact_matches": exact_matches,
        "contiguous_overlaps": contiguous_overlaps,
    }


def validate_recreated_skill_bundle(skill_dir: Path, source_paths: list[Path]) -> dict[str, Any]:
    skill_path = skill_dir.expanduser().resolve()
    metadata_path = skill_path / "THOMAS_SKILL.json"
    issues: list[dict[str, str]] = []
    metadata: dict[str, Any] = {}
    if not metadata_path.exists():
        issues.append(
            {
                "code": "missing_thomas_metadata",
                "message": "Distilled skills must include THOMAS_SKILL.json.",
            }
        )
    else:
        try:
            payload = json.loads(_read_text(metadata_path))
        except json.JSONDecodeError:
            payload = {}
            issues.append({"code": "invalid_thomas_metadata", "message": "THOMAS_SKILL.json is not valid JSON."})
        metadata = payload if isinstance(payload, dict) else {}
        if not bool(metadata.get("recreated_from_scratch")):
            issues.append(
                {
                    "code": "missing_recreated_flag",
                    "message": "THOMAS_SKILL.json must set recreated_from_scratch=true.",
                }
            )

    report = build_no_copy_report(source_paths, [skill_path])
    if report["exact_matches"]:
        issues.append({"code": "exact_copy_detected", "message": "Generated skill matches source file bytes."})
    if report["contiguous_overlaps"]:
        issues.append(
            {
                "code": "contiguous_overlap_detected",
                "message": "Generated skill reuses a long contiguous phrase from the source.",
            }
        )
    return {
        "ok": not issues,
        "issues": issues,
        "report": report,
        "metadata": metadata,
    }
