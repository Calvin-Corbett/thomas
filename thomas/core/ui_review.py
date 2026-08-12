"""Deterministic structural review helpers for UI edit safety."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_COLOR_RE = re.compile(r"\brgba?\([^)]+\)")
_HSL_COLOR_RE = re.compile(r"\bhsla?\([^)]+\)")
_ANIMATION_RE = re.compile(r"\banimation(?:-name)?\s*:")
_UI_REVIEW_EXTS = {".css", ".js", ".jsx", ".ts", ".tsx", ".html"}
_UI_REVIEW_PREFIXES = (
    "thomas/server/web/",
    "apps/site/src/",
)


def collect_changed_paths(root: Path) -> list[str]:
    rows: list[str] = []
    commands = [
        ["git", "-C", str(root), "diff", "--name-only"],
        ["git", "-C", str(root), "diff", "--name-only", "--cached"],
    ]
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8.0)
        except Exception:
            continue
        if proc.returncode != 0:
            continue
        for line in str(proc.stdout or "").splitlines():
            value = line.strip().replace("\\", "/")
            if value:
                rows.append(value)
    return sorted({row for row in rows})


def is_ui_review_path(rel_path: str) -> bool:
    value = str(rel_path or "").replace("\\", "/").strip().lower()
    if not value:
        return False
    if not any(value.startswith(prefix) for prefix in _UI_REVIEW_PREFIXES):
        return False
    suffix = Path(value).suffix.lower()
    return suffix in _UI_REVIEW_EXTS


def review_ui_edits(
    *,
    root: Path,
    read_text: Callable[[Path], str],
    intent: str = "",
    changed_paths: Iterable[str] | None = None,
    strict: bool = True,
    inferred_intent: str = "",
) -> dict[str, Any]:
    # Backward-compatible parameters only. Natural-language intent is evidence for
    # the frontier model, never a deterministic pass/fail input here.
    _ = intent
    _ = inferred_intent
    raw_paths = list(changed_paths or collect_changed_paths(root))
    changed = sorted({str(path or "").replace("\\", "/").strip() for path in raw_paths if str(path or "").strip()})
    ui_paths = [path for path in changed if is_ui_review_path(path)]
    if not ui_paths:
        return {
            "ok": True,
            "verdict": "skip",
            "reason": "no_ui_changes_detected",
            "changed_count": len(changed),
            "ui_changed_count": 0,
            "paths": [],
        }

    combined_text_chunks: list[str] = []
    issues: list[dict[str, Any]] = []
    css_changed_count = 0
    animation_without_reduced_motion = 0
    interactive_without_focus = 0
    hardcoded_colors_total = 0

    for rel_path in ui_paths:
        abs_path = root / rel_path
        content = read_text(abs_path)
        combined_text_chunks.append(content)
        suffix = abs_path.suffix.lower()
        if suffix != ".css":
            continue
        css_changed_count += 1
        hardcoded_colors = (
            len(_HEX_COLOR_RE.findall(content))
            + len(_RGB_COLOR_RE.findall(content))
            + len(_HSL_COLOR_RE.findall(content))
        )
        hardcoded_colors_total += hardcoded_colors
        has_animation = bool(_ANIMATION_RE.search(content) or "@keyframes" in content)
        if has_animation and "prefers-reduced-motion" not in content.lower():
            animation_without_reduced_motion += 1
        interactive_hint = any(
            token in content for token in (":hover", "button", "input", "select", "textarea", "a{", "a ")
        )
        if interactive_hint and ":focus-visible" not in content:
            interactive_without_focus += 1

    if animation_without_reduced_motion > 0:
        issues.append(
            {
                "id": "review.motion_reduced_missing",
                "severity": "high" if strict else "medium",
                "message": f"{animation_without_reduced_motion} changed CSS file(s) animate without prefers-reduced-motion fallback.",
            }
        )
    if interactive_without_focus > 0:
        issues.append(
            {
                "id": "review.focus_visible_missing",
                "severity": "medium",
                "message": f"{interactive_without_focus} changed CSS file(s) appear interactive without :focus-visible states.",
            }
        )
    if hardcoded_colors_total > max(12, css_changed_count * 8):
        issues.append(
            {
                "id": "review.hardcoded_colors_excess",
                "severity": "medium",
                "message": f"Changed CSS uses many hardcoded colors ({hardcoded_colors_total}); prefer token variables for consistency.",
            }
        )

    high_issues = [row for row in issues if str(row.get("severity") or "").lower() == "high"]
    if strict and high_issues:
        verdict = "fail"
    elif issues:
        verdict = "warn"
    else:
        verdict = "pass"

    score = 100
    score -= 20 * len(high_issues)
    score -= 8 * (len(issues) - len(high_issues))
    score = max(0, min(100, int(score)))

    return {
        "ok": True,
        "verdict": verdict,
        "score": score,
        "strict": bool(strict),
        "changed_count": len(changed),
        "ui_changed_count": len(ui_paths),
        "paths": ui_paths,
        "checks": {
            "css_changed_count": css_changed_count,
            "hardcoded_colors_total": hardcoded_colors_total,
            "animation_without_reduced_motion": animation_without_reduced_motion,
            "interactive_without_focus": interactive_without_focus,
        },
        "issues": issues,
    }
