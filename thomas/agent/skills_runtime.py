"""Runtime skill discovery and selection for model-agnostic agent turns.

This module keeps skill resolution in the orchestrator layer so any model
provider used by Thomas (Codex, Anthropic, OpenAI-compatible) receives the
same selected skill guidance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.skills import discover_native_skill_roots, discover_native_skills, excerpt_body, read_skill_bundle

from .skills_policy import (
    classify_skill_risk,
    evaluate_skill_trust,
    has_skill_approval_phrase,
    is_globally_approved,
    load_runtime_skill_trust_policy,
    prompt_negates_risky_approval,
)

_LOW_INTENT_ROUTES = {"casual_chat", "assistant_meta", "personal_context", "general"}
_REQUIRED_CHECK_LINE_RE = re.compile(
    r"\b(before finishing|required(?: local)? probes?|literal probe|expected output|must run|run probes?)\b",
    re.IGNORECASE,
)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_EXPECTED_OUTPUT_RE = re.compile(r"\bexpect(?:ed|ing)?(?:\s+(?:output|result|remaining|ids?))?\b", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "about",
    "accept",
    "across",
    "add",
    "after",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "behavior",
    "before",
    "both",
    "by",
    "change",
    "changes",
    "component",
    "components",
    "constraint",
    "constraints",
    "current",
    "data",
    "default",
    "defaults",
    "dependencies",
    "during",
    "each",
    "either",
    "end",
    "existing",
    "expected",
    "file",
    "files",
    "for",
    "from",
    "got",
    "handle",
    "including",
    "how",
    "i",
    "if",
    "in",
    "inside",
    "instead",
    "is",
    "it",
    "keep",
    "must",
    "new",
    "not",
    "of",
    "only",
    "on",
    "or",
    "part",
    "parser",
    "preserve",
    "requested",
    "require",
    "required",
    "run",
    "same",
    "should",
    "specific",
    "support",
    "supports",
    "that",
    "the",
    "this",
    "thomas",
    "to",
    "type",
    "use",
    "value",
    "when",
    "with",
    "work",
    "you",
    "your",
}


def _is_enabled_env(name: str, default: bool = True) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return bool(default)
    return raw not in {"0", "false", "no", "off"}


def _codex_home_skills_key() -> str:
    raw = str(os.environ.get("CODEX_HOME") or "").strip()
    if not raw:
        return ""
    try:
        return str((Path(raw).expanduser() / "skills").resolve()).lower()
    except Exception:
        return str(Path(raw).expanduser() / "skills").lower()


def _int_env(name: str, default: int, *, allow_non_positive: bool = False) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return int(default)

    lowered = raw.lower()
    if lowered in {"all", "unlimited", "none", "inf", "infinite"}:
        return 0 if allow_non_positive else int(default)

    try:
        value = int(raw)
    except Exception:
        return int(default)
    if value <= 0 and not allow_non_positive:
        return int(default)
    return int(value)


def _normalize_skill_name(value: str) -> str:
    return str(value or "").strip().lower()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _ordered_unique(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = str(item or "").strip()
        if not key:
            continue
        norm = key.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(key)
    return out


def _keyword_tokens(text: str) -> list[str]:
    src = str(text or "").lower()
    raw = re.findall(r"[a-z0-9][a-z0-9._-]{1,60}", src)
    out: list[str] = []
    for token in raw:
        # Keep dense identifiers (for example "cloudflare-deploy"), but skip
        # low-signal short words.
        if len(token) < 3 and token not in {"ui", "ux"}:
            continue
        if token in _STOPWORDS:
            continue
        out.append(token)
        if "-" in token:
            out.extend([part for part in token.split("-") if len(part) >= 3 and part not in _STOPWORDS])
        if "_" in token:
            out.extend([part for part in token.split("_") if len(part) >= 3 and part not in _STOPWORDS])
    return _ordered_unique(out)


def _read_skill_description(skill_md: Path) -> str:
    try:
        lines = skill_md.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        if text.startswith("#"):
            continue
        return text[:240]
    return ""


def _read_skill_excerpt(skill_md: Path, *, max_chars: int) -> str:
    try:
        raw = skill_md.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

    lines: list[str] = []
    chars = 0
    in_code_block = False
    for row in raw.splitlines():
        stripped = str(row or "").rstrip()
        marker = stripped.strip()
        if marker.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not marker:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        compact = marker[:220] + ("..." if len(marker) > 220 else "")
        next_len = chars + len(compact) + 1
        if next_len > max_chars:
            break
        lines.append(compact)
        chars = next_len

    excerpt = "\n".join(lines).strip()
    if excerpt:
        return excerpt
    return raw[:max_chars].strip()


def _memory_root_path(config: Any) -> Path:
    memory = getattr(config, "memory", None)
    root_path = getattr(memory, "root_path", None)
    if isinstance(root_path, Path):
        return root_path
    if root_path:
        return Path(str(root_path)).expanduser()
    root_text = getattr(memory, "root", None)
    if root_text:
        return Path(str(root_text)).expanduser()
    return (Path.cwd() / "runtime").resolve()


def _skills_state_path(config: Any) -> Path:
    return _memory_root_path(config) / ".thomas" / "cli" / "skills.json"


def load_pinned_skill_names(config: Any) -> list[str]:
    path = _skills_state_path(config)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("pinned")
    if not isinstance(rows, list):
        return []
    pinned: list[str] = []
    for item in rows:
        norm = _normalize_skill_name(str(item or ""))
        if norm:
            pinned.append(norm)
    return _ordered_unique(pinned)


def discover_skill_roots(
    config: Any,
    *,
    cwd: Path | None = None,
    include_roots: Sequence[str | Path] | None = None,
) -> list[Path]:
    _ = config
    roots = [path for path, _origin in discover_native_skill_roots(cwd=cwd)]
    for extra in include_roots or []:
        path_text = str(extra or "").strip()
        if path_text:
            roots.append(Path(path_text).expanduser())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            unique.append(resolved)
    return unique


@dataclass
class RuntimeSkill:
    name: str
    path: str
    skill_file: str
    source_root: str
    description: str
    excerpt: str
    skill_sha256: str = ""
    risk_level: str = "low"
    risk_tags: list[str] = field(default_factory=list)
    keyword_tokens: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return str(self.path).strip().lower()


@dataclass
class RuntimeSkillSelection:
    enabled: bool
    selected: list[RuntimeSkill] = field(default_factory=list)
    selected_reasons: dict[str, str] = field(default_factory=dict)
    explicit_mentions: list[str] = field(default_factory=list)
    pinned_matches: list[str] = field(default_factory=list)
    approved_risky: list[str] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    discovered_count: int = 0
    trusted_count: int = 0
    untrusted_count: int = 0
    trust_policy: dict[str, Any] = field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        required_checks: list[dict[str, Any]] = []
        for skill in self.selected:
            required_checks.extend(_required_checks_for_skill(skill))
        return {
            "enabled": bool(self.enabled),
            "discovered_count": int(self.discovered_count),
            "selected_count": len(self.selected),
            "explicit_mentions": list(self.explicit_mentions),
            "pinned_matches": list(self.pinned_matches),
            "approved_risky": list(self.approved_risky),
            "blocked": [dict(row) for row in self.blocked],
            "roots": list(self.roots),
            "trusted_count": int(self.trusted_count),
            "untrusted_count": int(self.untrusted_count),
            "trust_policy": dict(self.trust_policy),
            "required_checks": required_checks[:12],
            "selected": [
                {
                    "name": str(skill.name),
                    "path": str(skill.path),
                    "skill_file": str(skill.skill_file),
                    "skill_sha256": str(skill.skill_sha256),
                    "risk_level": str(skill.risk_level),
                    "risk_tags": list(skill.risk_tags),
                    "reason": str(self.selected_reasons.get(skill.key, "")),
                }
                for skill in self.selected
            ],
        }


def _required_checks_for_skill(skill: RuntimeSkill) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in str(skill.excerpt or "").splitlines():
        text = str(row or "").strip()
        if not text or not _REQUIRED_CHECK_LINE_RE.search(text):
            continue
        snippets = []
        expected_outputs = []
        expected_match = _EXPECTED_OUTPUT_RE.search(text)
        expected_at = expected_match.start() if expected_match else -1
        for match in _INLINE_CODE_RE.finditer(text):
            value = str(match.group(1) or "").strip()
            if len(value) < 2:
                continue
            if expected_at >= 0 and match.start() > expected_at and value[:1] in {"[", "{", "(", '"', "'"}:
                expected_outputs.append(value)
            else:
                snippets.append(value)
        checks.append(
            {
                "skill": str(skill.name),
                "text": text[:360],
                "snippets": _ordered_unique(snippets)[:8],
                "expected_outputs": _ordered_unique(expected_outputs)[:4],
            }
        )
    return checks[:6]


def discover_runtime_skills(
    config: Any,
    *,
    cwd: Path | None = None,
    include_roots: Sequence[str | Path] | None = None,
    max_excerpt_chars: int = 1_100,
) -> tuple[list[RuntimeSkill], list[str]]:
    _ = config
    rows: list[RuntimeSkill] = []
    seen: set[str] = set()
    bundles, roots = discover_native_skills(cwd=cwd)
    if _is_enabled_env("THOMAS_RUNTIME_IGNORE_CODEX_HOME_SKILLS", default=False):
        codex_home_skills = _codex_home_skills_key()
        if codex_home_skills:
            bundles = [
                bundle
                for bundle in bundles
                if str(getattr(bundle, "source_root", "") or "").lower() != codex_home_skills
            ]
            roots = [root for root in roots if str(root or "").lower() != codex_home_skills]

    def _append_bundle(bundle: Any, root_label: str) -> None:
        parent_path = str(bundle.path)
        key = parent_path.lower()
        if key in seen:
            return
        seen.add(key)
        excerpt = excerpt_body(str(bundle.body or ""), max_chars=max(350, int(max_excerpt_chars)))
        skill_sha = ""
        try:
            skill_sha = _sha256_file(Path(bundle.skill_file))
        except Exception:
            skill_sha = ""
        risk_level, risk_tags = classify_skill_risk(bundle.name, bundle.description, excerpt)
        skill_tokens = _keyword_tokens("\n".join([bundle.name, bundle.description, excerpt[:450]]))
        rows.append(
            RuntimeSkill(
                name=str(bundle.name),
                path=parent_path,
                skill_file=str(bundle.skill_file),
                source_root=str(root_label),
                description=str(bundle.description),
                excerpt=excerpt,
                skill_sha256=skill_sha,
                risk_level=risk_level,
                risk_tags=risk_tags,
                keyword_tokens=skill_tokens,
            )
        )

    for bundle in bundles:
        _append_bundle(bundle, bundle.source_root)

    extra_roots: list[str] = []
    root_keys = {str(root).lower() for root in roots}
    configured_roots: list[str | Path] = []
    configured_roots.extend(include_roots or [])
    env_roots = str(os.environ.get("THOMAS_RUNTIME_SKILL_ROOTS") or "").strip()
    if env_roots:
        configured_roots.extend(part for part in env_roots.split(os.pathsep) if part.strip())

    for extra in configured_roots:
        path_text = str(extra or "").strip()
        if not path_text:
            continue
        extra_root = Path(path_text).expanduser()
        try:
            resolved_root = extra_root.resolve()
        except Exception:
            resolved_root = extra_root
        root_key = str(resolved_root).lower()
        if root_key in root_keys or not resolved_root.exists() or not resolved_root.is_dir():
            continue
        root_keys.add(root_key)
        extra_roots.append(str(resolved_root))
        try:
            skill_files = list(resolved_root.rglob("SKILL.md"))
        except Exception:
            skill_files = []
        for skill_md in skill_files:
            bundle = read_skill_bundle(skill_md.parent, source_root=resolved_root, origin="extra")
            if bundle is not None:
                _append_bundle(bundle, str(resolved_root))

    rows.sort(key=lambda item: item.name.lower())
    return rows, roots + extra_roots


def _skill_name_aliases(name: str) -> list[str]:
    normalized = _normalize_skill_name(name)
    if not normalized:
        return []
    aliases = {
        normalized,
        normalized.replace("_", "-"),
        normalized.replace("-", "_"),
        normalized.replace(" ", "-"),
        normalized.replace(" ", "_"),
    }
    return sorted({alias for alias in aliases if alias})


def _extract_explicit_mentions(prompt_text: str) -> list[str]:
    text = str(prompt_text or "")
    names: list[str] = []
    for pattern in (
        r"\$([A-Za-z0-9][A-Za-z0-9._-]{1,80})",
        r"`([A-Za-z0-9][A-Za-z0-9._-]{1,80})`",
        r"\bskill\s+([A-Za-z0-9][A-Za-z0-9._-]{1,80})\b",
    ):
        for match in re.findall(pattern, text):
            names.append(_normalize_skill_name(str(match)))
    return _ordered_unique(names)


def _skill_name_mentioned(prompt_text: str, name_alias: str) -> bool:
    src = str(prompt_text or "").lower()
    target = str(name_alias or "").lower().strip()
    if not src or not target:
        return False
    escaped = re.escape(target)
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", src))


def _skill_relevance_score(query_tokens: set[str], skill: RuntimeSkill) -> int:
    """Prefer skill identity matches over incidental overlap in long instructions."""
    if not query_tokens:
        return 0

    all_tokens = set(skill.keyword_tokens)
    overlap = query_tokens.intersection(all_tokens)
    if not overlap:
        return 0

    name_tokens = set(_keyword_tokens(skill.name.replace("-", " ")))
    description_tokens = set(_keyword_tokens(skill.description))

    name_overlap = overlap.intersection(name_tokens)
    description_overlap = overlap.intersection(description_tokens) - name_overlap
    body_overlap = overlap - name_overlap - description_overlap

    return (len(name_overlap) * 3) + (len(description_overlap) * 2) + len(body_overlap)


def resolve_runtime_skills(
    config: Any,
    *,
    prompt_text: str,
    relevance_text: str = "",
    route_path: str = "",
    cwd: Path | None = None,
    include_roots: Sequence[str | Path] | None = None,
    max_selected: int | None = None,
) -> RuntimeSkillSelection:
    enabled = _is_enabled_env("THOMAS_RUNTIME_SKILLS_ENABLED", default=True)
    selection = RuntimeSkillSelection(enabled=enabled)
    if not enabled:
        return selection

    max_excerpt_chars = _int_env(
        "THOMAS_RUNTIME_SKILL_EXCERPT_CHARS",
        1_100,
        allow_non_positive=False,
    )
    discovered, roots = discover_runtime_skills(
        config,
        cwd=cwd,
        include_roots=include_roots,
        max_excerpt_chars=max(350, int(max_excerpt_chars)),
    )
    selection.roots = roots
    selection.discovered_count = len(discovered)
    if not discovered:
        return selection

    max_count = (
        int(max_selected)
        if max_selected is not None
        else _int_env(
            "THOMAS_RUNTIME_MAX_SKILLS",
            4,
            allow_non_positive=True,
        )
    )
    if _is_enabled_env("THOMAS_RUNTIME_LOAD_ALL_SKILLS", default=False):
        max_count = 0
    max_count = None if int(max_count or 0) <= 0 else int(max_count)
    max_total_chars = _int_env(
        "THOMAS_RUNTIME_MAX_SKILL_CHARS",
        0 if max_count is None else 3600,
        allow_non_positive=True,
    )
    max_total_chars = None if int(max_total_chars or 0) <= 0 else int(max_total_chars)
    require_explicit_risky = _is_enabled_env(
        "THOMAS_RUNTIME_SKILLS_REQUIRE_EXPLICIT_RISK_APPROVAL",
        default=True,
    )
    min_relevance_score = _int_env(
        "THOMAS_RUNTIME_SKILL_MIN_RELEVANCE_SCORE",
        5,
        allow_non_positive=True,
    )
    auto_relevance_enabled = _is_enabled_env(
        "THOMAS_RUNTIME_SKILLS_AUTO_RELEVANCE",
        default=False,
    )
    global_risk_approved = is_globally_approved(prompt_text)
    trust_policy = load_runtime_skill_trust_policy(config, cwd=cwd)
    selection.trust_policy = trust_policy.summary()

    by_alias: dict[str, list[RuntimeSkill]] = {}
    for skill in discovered:
        for alias in _skill_name_aliases(skill.name):
            by_alias.setdefault(alias, []).append(skill)

    explicit_mentions = _extract_explicit_mentions(prompt_text)
    for skill in discovered:
        for alias in _skill_name_aliases(skill.name):
            if _skill_name_mentioned(prompt_text, alias):
                explicit_mentions.append(alias)
                break
    explicit_mentions = _ordered_unique(explicit_mentions)
    selection.explicit_mentions = explicit_mentions

    pinned = load_pinned_skill_names(config)
    selected: list[RuntimeSkill] = []
    selected_keys: set[str] = set()
    reasons: dict[str, str] = {}
    blocked_rows: list[dict[str, Any]] = []
    blocked_keys: set[str] = set()
    approved_risky: list[str] = []

    trust_eval: dict[str, tuple[bool, str]] = {}
    trusted_count = 0
    untrusted_count = 0
    for skill in discovered:
        trusted, trust_reason = evaluate_skill_trust(
            skill_name=skill.name,
            skill_file=skill.skill_file,
            skill_sha256=skill.skill_sha256,
            policy=trust_policy,
        )
        trust_eval[skill.key] = (bool(trusted), str(trust_reason))
        if trusted:
            trusted_count += 1
        else:
            untrusted_count += 1
    selection.trusted_count = int(trusted_count)
    selection.untrusted_count = int(untrusted_count)

    def _block(skill: RuntimeSkill, code: str, reason: str, selected_reason: str) -> None:
        block_key = f"{skill.key}|{code}"
        if block_key in blocked_keys:
            return
        blocked_keys.add(block_key)
        blocked_rows.append(
            {
                "code": str(code),
                "name": str(skill.name),
                "path": str(skill.path),
                "risk_level": str(skill.risk_level),
                "risk_tags": list(skill.risk_tags),
                "selection_reason": str(selected_reason),
                "reason": str(reason),
            }
        )

    def _add(skill: RuntimeSkill, reason: str) -> None:
        if max_count is not None and len(selected) >= max_count:
            return
        key = skill.key
        if key in selected_keys:
            return
        trusted, trust_reason = trust_eval.get(key, (True, "trust_unknown"))
        if trust_policy.mode == "enforce" and not bool(trusted):
            _block(
                skill,
                code="untrusted_skill",
                reason=str(trust_reason),
                selected_reason=reason,
            )
            return
        if str(skill.risk_level) == "high" and require_explicit_risky:
            # R5 (praxis-unbypassable-2026-05-29): an explicit mention approves a
            # high-risk skill ONLY when the prompt does not negate risky-skill
            # approval. Previously `reason == "explicit"` alone approved it, so
            # "Use $cloudflare-deploy ... but I do not approve risky skills"
            # auto-approved the deploy skill despite the refusal. A genuine
            # explicit invocation ("please use $deploy-prod now") still works.
            explicit_ok = bool(reason == "explicit" and not prompt_negates_risky_approval(prompt_text))
            approved = bool(explicit_ok or global_risk_approved or has_skill_approval_phrase(prompt_text, skill.name))
            if not approved:
                _block(
                    skill,
                    code="risky_skill_requires_explicit_approval",
                    reason="high-risk skill requires explicit, non-negated approval; mention plus a refusal is not approval",
                    selected_reason=reason,
                )
                return
            approved_risky.append(str(skill.name))
        selected_keys.add(key)
        selected.append(skill)
        reasons[key] = reason

    for mention in explicit_mentions:
        for skill in by_alias.get(_normalize_skill_name(mention), []):
            _add(skill, "explicit")

    for pinned_name in pinned:
        matched = False
        for skill in by_alias.get(_normalize_skill_name(pinned_name), []):
            _add(skill, "pinned")
            matched = True
        if matched:
            selection.pinned_matches.append(pinned_name)

    low_intent = str(route_path or "").strip() in _LOW_INTENT_ROUTES
    query_tokens = set(_keyword_tokens(f"{prompt_text}\n{relevance_text}\n{route_path.replace('_', ' ')}"))

    if auto_relevance_enabled and query_tokens and (not low_intent or bool(selected)):
        scored: list[tuple[int, int, RuntimeSkill]] = []
        for skill in discovered:
            if skill.key in selected_keys:
                continue
            overlap_tokens = query_tokens.intersection(set(skill.keyword_tokens))
            overlap = len(overlap_tokens)
            score = _skill_relevance_score(query_tokens, skill)
            if overlap <= 0 or score <= 0:
                continue
            if min_relevance_score > 0 and score < min_relevance_score:
                continue
            scored.append((score, overlap, skill))
        scored.sort(key=lambda item: (-int(item[0]), -int(item[1]), item[2].name.lower(), item[2].path.lower()))
        selected_before_relevance = len(selected)
        top_score = int(scored[0][0]) if scored else 0
        top_relevance_blocked = False
        top_relevance_selected = False
        for score, _overlap, skill in scored:
            if (
                selected_before_relevance == 0
                and top_relevance_blocked
                and not top_relevance_selected
                and int(score) < top_score
            ):
                break
            before_selected = len(selected)
            before_blocked = len(blocked_rows)
            _add(skill, f"relevance:{score}")
            if int(score) == top_score:
                if len(selected) > before_selected:
                    top_relevance_selected = True
                if len(blocked_rows) > before_blocked:
                    top_relevance_blocked = True

    # Prompt-size guardrail: keep compact by limiting cumulative skill payload.
    if selected and max_total_chars is not None:
        limited: list[RuntimeSkill] = []
        total_chars = 0
        for skill in selected:
            est = len(skill.name) + len(skill.description) + len(skill.excerpt) + 72
            if limited and (total_chars + est) > max_total_chars:
                break
            limited.append(skill)
            total_chars += est
        selected = limited
        selected_keys = {skill.key for skill in selected}
        reasons = {key: val for key, val in reasons.items() if key in selected_keys}
        approved_risky = [name for name in approved_risky if name in {s.name for s in selected}]

    selection.selected = selected
    selection.selected_reasons = reasons
    selection.approved_risky = _ordered_unique(approved_risky)
    selection.blocked = blocked_rows
    return selection


def format_runtime_skills_context(selection: RuntimeSkillSelection) -> str:
    if not selection.enabled or not selection.selected:
        return ""

    trust_mode = str((selection.trust_policy or {}).get("mode") or "enforce")
    require_hash = bool((selection.trust_policy or {}).get("require_hash"))
    lines: list[str] = [
        "--- Runtime Skills ---",
        "Apply the selected skill instructions for this turn.",
        "For coding/debugging turns, convert any skill-required probes, checks, or "
        "before-finishing instructions into concrete local validation before finalizing; "
        "if a required check cannot run, state why.",
        "If a skill names a literal probe, exact command, expected output, or required "
        "local probe, run that exact check; nearby or simplified checks are not a substitute.",
        "Selection priority: explicit mention > pinned > relevance.",
        f"Trust policy: mode={trust_mode}, require_hash={str(require_hash).lower()}, "
        f"trusted={int(selection.trusted_count)}/{int(selection.discovered_count)} discovered skills.",
    ]
    for idx, skill in enumerate(selection.selected, start=1):
        reason = str(selection.selected_reasons.get(skill.key, "") or "")
        lines.append(f"{idx}. {skill.name} [{reason}]")
        lines.append(f"   Skill file: {skill.skill_file}")
        if skill.skill_sha256:
            lines.append(f"   SHA256: {skill.skill_sha256}")
        if str(skill.risk_level) == "high":
            tags = ", ".join(skill.risk_tags[:8]) if skill.risk_tags else "high-risk"
            lines.append(f"   Risk: high ({tags})")
        if skill.description:
            lines.append(f"   Summary: {skill.description}")
        if skill.excerpt:
            lines.append("   Instructions:")
            for row in skill.excerpt.splitlines():
                chunk = str(row or "").rstrip()
                if not chunk:
                    continue
                lines.append(f"   {chunk}")
    lines.append(
        "If skill instructions conflict, follow the user's direct request first, "
        "then explicit skill mentions, then pinned/relevance selections."
    )
    if selection.approved_risky:
        lines.append(
            "Approved risky skills for this turn: " + ", ".join(str(name) for name in selection.approved_risky)
        )
    lines.append("--- End Runtime Skills ---")
    return "\n".join(lines)
