"""Deterministic review helpers for UI edit safety and intent alignment."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_COLOR_RE = re.compile(r"\brgba?\([^)]+\)")
_HSL_COLOR_RE = re.compile(r"\bhsla?\([^)]+\)")
_ANIMATION_RE = re.compile(r"\banimation(?:-name)?\s*:")
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")

_INTENT_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "under",
    "when", "while", "your", "their", "have", "has", "had", "will", "would", "should",
    "could", "just", "more", "less", "very", "really", "about", "make", "makes", "made",
    "need", "needs", "want", "wants", "user", "users", "page", "ui", "design", "update",
    "edit", "edits", "better", "good", "solid", "please", "must", "match", "intent",
}

_UI_REVIEW_EXTS = {".css", ".js", ".jsx", ".ts", ".tsx", ".html"}
_UI_REVIEW_PREFIXES = (
    "thomas/server/web/",
)


def collect_changed_paths(root: Path) -> List[str]:
    rows: List[str] = []
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


def intent_keywords(text: str) -> List[str]:
    words = [word.lower() for word in _WORD_RE.findall(str(text or ""))]
    out: List[str] = []
    seen: set[str] = set()
    for word in words:
        if len(word) < 4 or word in _INTENT_STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out[:24]


def review_ui_edits(
    *,
    root: Path,
    read_text: Callable[[Path], str],
    intent: str = "",
    changed_paths: Optional[Iterable[str]] = None,
    strict: bool = True,
    inferred_intent: str = "",
) -> Dict[str, Any]:
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

    intent_text = str(intent or "").strip() or str(inferred_intent or "").strip()
    keys = intent_keywords(intent_text)

    combined_text_chunks: List[str] = []
    issues: List[Dict[str, Any]] = []
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
        hardcoded_colors = len(_HEX_COLOR_RE.findall(content)) + len(_RGB_COLOR_RE.findall(content)) + len(_HSL_COLOR_RE.findall(content))
        hardcoded_colors_total += hardcoded_colors
        has_animation = bool(_ANIMATION_RE.search(content) or "@keyframes" in content)
        if has_animation and "prefers-reduced-motion" not in content.lower():
            animation_without_reduced_motion += 1
        interactive_hint = any(token in content for token in (":hover", "button", "input", "select", "textarea", "a{", "a "))
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

    corpus = " ".join(combined_text_chunks).lower()
    matched_keywords: List[str] = []
    missing_keywords: List[str] = []
    if keys:
        for key in keys:
            if key in corpus:
                matched_keywords.append(key)
            else:
                missing_keywords.append(key)
        alignment_score = round(len(matched_keywords) / float(len(keys)), 3)
        if alignment_score < 0.35:
            issues.append(
                {
                    "id": "review.intent_alignment_low",
                    "severity": "high" if strict else "medium",
                    "message": f"Intent alignment is low ({alignment_score:.2f}); edited UI may not match requested outcome.",
                    "missing_keywords": missing_keywords[:12],
                }
            )
    else:
        alignment_score = None

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
    if alignment_score is not None:
        score = min(score, int(round(40 + alignment_score * 60)))
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
        "intent": {
            "text": intent_text,
            "keywords": keys,
            "matched_keywords": matched_keywords,
            "missing_keywords": missing_keywords,
            "alignment_score": alignment_score,
        },
        "issues": issues,
    }
