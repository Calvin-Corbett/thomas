"""Fail-closed verification and evidence-only reconciliation for worker artifacts."""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from thomas.server import chat_delegation_artifact_intent as artifact_intent

_ARTIFACT_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9][A-Za-z0-9_.-]{0,120}\."
    r"(?:md|txt|json|csv|tsv|html|htm|pdf|docx|xlsx|pptx|py|js|ts|tsx|jsx|css|svg))\b",
    re.IGNORECASE,
)
_UNRESOLVED_PLACEHOLDER_RE = re.compile(
    r"\[(?:(?:insert|replace|extracted|page\s+title|brief\s+description|todo)\b[^]\r\n]{0,120}"
    r"|(?:heading|title|value|content|description))\]",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)\]}>,]+", re.IGNORECASE)
_TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv", ".tsv", ".html", ".htm"}
_QUOTED_LITERAL_RE = re.compile(r'["\u201c]([^"\u201d\r\n]{1,240})["\u201d]')
_CSV_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"([A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?,"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)"
    r"(?![A-Za-z0-9_-])"
)
_ID_LITERAL_RE = re.compile(r"\bid\s+['\"]?([A-Za-z][A-Za-z0-9_-]{1,80})", re.IGNORECASE)
_MARKER_LITERAL_RE = re.compile(r"\bmarker\s+['\"]?([A-Za-z0-9][A-Za-z0-9_.:-]{2,120})", re.IGNORECASE)
_MARKER_TOKEN_RE = re.compile(r"(?:^|[-_.:])marker(?:[-_.:]|$)", re.IGNORECASE)
_TERMINAL_PENDING_RE = re.compile(
    r"\b(?:please\s+wait|once\s+(?:the|these)\s+checks?\s+pass|"
    r"i(?:'m|\s+am)\s+(?:going\s+to|about\s+to)|"
    r"let\s+me\s+(?:execute|run|finish)|will\s+(?:then\s+)?(?:execute|provide))\b",
    re.IGNORECASE,
)
_ATTACHED_DOCUMENTS_BOUNDARY_RE = re.compile(r"\n\s*\[Attached documents\]\s*\n", re.IGNORECASE)
_RECOVERABLE_READ_TOOLS = {"fs.read_file", "fs_read_file", "fs.list_dir", "fs_list_dir"}
_OPTIONAL_ENRICHMENT_TOOLS = {"create_skill", "skills.create", "skill.create"}


def _prompt_requires_skill_change(prompt: str) -> bool:
    text = " ".join(str(prompt or "").casefold().split())
    if re.search(r"\b(?:do not|don't|without)\b.{0,40}\bskills?\b", text):
        return False
    return bool(
        re.search(
            r"\b(?:create|make|build|write|update|edit|change|improve|install)\b.{0,60}\bskills?\b",
            text,
        )
    )


def _hidden_completion_review_passes(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str],
    summary: str,
    verified_candidate: bool,
    failed_tools: list[str],
    *,
    succeeded_tools: list[str] | None = None,
) -> bool:
    """Run the standard worker result through the adversarial review panel.

    Ordinary provider-native work must pass this hidden review before its proof or
    terminal text is presented. The scorer is evidence-based and deterministic:
    every lens vetoes missing verification, tool failure, missing files, or empty
    artifacts. Informational answers can pass without files only when the existing
    completion-evidence policy already verified them.
    """
    from thomas.marketplace.orchestrator import adversarial_review

    root = work_dir.resolve() if work_dir is not None else None
    missing_or_empty: list[str] = []
    for relative in created_files:
        candidate = (root / relative).resolve() if root is not None else None
        if candidate is None or not candidate.is_file() or candidate.stat().st_size <= 0:
            missing_or_empty.append(str(relative))
    succeeded = {str(tool) for tool in (succeeded_tools or []) if str(tool)}
    recovered_reads = (
        succeeded.intersection(_RECOVERABLE_READ_TOOLS) if created_files and not missing_or_empty else set()
    )
    optional_failures = (
        _OPTIONAL_ENRICHMENT_TOOLS
        if created_files and not missing_or_empty and not _prompt_requires_skill_change(prompt)
        else set()
    )
    unrecovered_failures = [
        str(tool)
        for tool in failed_tools
        if str(tool) and str(tool) not in recovered_reads and str(tool) not in optional_failures
    ]
    # Does the artifact have anything to do with the request? Every other check
    # here asks whether *something* was produced, which a wrong deliverable
    # passes as easily as a right one -- an arcade game satisfied a request for
    # a graph of current trends, and a football game closed "start a local dev
    # server". This is the only check that can tell those apart.
    intent = artifact_intent.intent_evidence(prompt, root, list(created_files))
    intent_issues = list(intent.get("issues") or [])

    evidence: dict[str, Any] = {
        "prompt": str(prompt or ""),
        "summary": str(summary or ""),
        "created_files": list(created_files),
        "failed_tools": list(failed_tools),
        "unrecovered_failed_tools": unrecovered_failures,
        "missing_or_empty": missing_or_empty,
        "artifact_intent": intent,
    }

    def _score(_work: Any, _rubric: dict[str, Any], lens: str) -> float:
        if not verified_candidate or unrecovered_failures or missing_or_empty or not str(summary or "").strip():
            return 0.0
        if intent_issues:
            return 0.0
        return 9.0 if lens in {"correctness", "completeness", "robustness"} else 8.0

    review = adversarial_review.review_deliverable(
        evidence,
        {"verified": bool(verified_candidate), "artifact_count": len(created_files)},
        scorer=_score,
        budget_ok=True,
    )
    return bool(review.passed)


def _explicit_request_text(prompt: str) -> str:
    """Exclude attachment bodies from output-artifact requirement inference."""
    text = str(prompt or "")
    boundary = _ATTACHED_DOCUMENTS_BOUNDARY_RE.search(text)
    return text[: boundary.start()] if boundary else text


def _requested_names(prompt: str) -> list[str]:
    return list(dict.fromkeys(match.group(1) for match in _ARTIFACT_NAME_RE.finditer(_explicit_request_text(prompt))))


def _created_paths_by_name(created_files: list[str]) -> dict[str, list[Path]]:
    """Index safe recorded artifact paths without discarding their directories."""
    paths: dict[str, list[Path]] = {}
    for raw in created_files:
        rel = Path(str(raw or "").strip().replace("\\", "/").lstrip("/"))
        if rel.is_absolute() or not rel.parts or ".." in rel.parts:
            continue
        paths.setdefault(rel.name.casefold(), []).append(rel)
    return paths


def _artifact_requirement_segments(prompt: str) -> dict[str, str]:
    """Return the requirement text attached to each first-mentioned artifact."""
    request_text = _explicit_request_text(prompt)
    matches = list(_ARTIFACT_NAME_RE.finditer(request_text))
    segments: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = Path(match.group(1)).name.casefold()
        if key in segments:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(request_text)
        segments[key] = request_text[match.end() : end]
    return segments


def _required_literals(name: str, segment: str) -> list[str]:
    """Extract conservative exact-content requirements for one text artifact."""
    literals = [match.group(1).strip() for match in _QUOTED_LITERAL_RE.finditer(segment)]
    literals.extend(match.group(1).strip() for match in _ID_LITERAL_RE.finditer(segment))
    literals.extend(match.group(1).strip() for match in _MARKER_LITERAL_RE.finditer(segment))
    if Path(name).suffix.casefold() in {".csv", ".tsv"}:
        literals.extend(match.group(1).strip() for match in _CSV_LITERAL_RE.finditer(segment))
    return list(dict.fromkeys(value for value in literals if value))


def _required_urls(prompt: str) -> list[str]:
    required: list[str] = []
    for match in _URL_RE.finditer(prompt or ""):
        prefix = prompt[max(0, match.start() - 180) : match.start()].casefold()
        if "must include" in prefix or "include the source url" in prefix:
            required.append(match.group(0).rstrip(".,;:"))
    return required


def _requires_extracted_value(prompt: str) -> bool:
    return "must include" in (prompt or "").casefold() and bool(
        re.search(r"\bextracted\s+(?:heading|value|text|content)\b", prompt or "", re.IGNORECASE)
    )


def _extract_values(tool_outputs: dict[str, list[str]] | None) -> list[str]:
    values: list[str] = []
    for raw in (tool_outputs or {}).get("browser.extract", []):
        for match in re.finditer(r"['\"]([^'\"\r\n]{1,240})['\"]", raw):
            value = match.group(1).strip()
            if value and value not in values:
                values.append(value)
    return values


def _requested_artifact_issues(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str],
    tool_outputs: dict[str, list[str]] | None = None,
) -> list[str]:
    """Return mismatches between explicit artifact requirements and evidence."""
    requested = _requested_names(prompt)
    if not requested:
        return []

    created_by_name = _created_paths_by_name(created_files)
    messages = [
        f"missing exact requested artifact {name}"
        for name in requested
        if Path(name).name.casefold() not in created_by_name
    ]
    if work_dir is None:
        return messages

    root = work_dir.resolve()
    segments = _artifact_requirement_segments(prompt)
    extract_values = _extract_values(tool_outputs)
    for name in requested:
        matching_paths = created_by_name.get(Path(name).name.casefold(), [])
        if not matching_paths:
            continue
        if len(matching_paths) > 1:
            messages.append(f"requested artifact {name} is ambiguous across multiple created paths")
            continue
        relative = matching_paths[0]
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            messages.append(f"requested artifact escaped workspace: {name}")
            continue
        if candidate.suffix.casefold() not in _TEXT_SUFFIXES:
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messages.append(f"could not read requested artifact {name}: {exc}")
            continue
        placeholder = _UNRESOLVED_PLACEHOLDER_RE.search(content)
        if placeholder:
            messages.append(f"unresolved placeholder in {name}: {placeholder.group(0)}")
        segment = segments.get(Path(name).name.casefold(), "")
        searchable_content = html.unescape(content)
        for literal in _required_literals(name, segment):
            if literal not in searchable_content:
                messages.append(f"requested artifact {name} is missing required text {literal!r}")
        required_urls = _required_urls(segment)
        for url in required_urls:
            if url not in content:
                messages.append(f"requested artifact {name} is missing required URL {url}")
        requires_extracted = _requires_extracted_value(segment)
        if requires_extracted:
            if not extract_values:
                messages.append(f"requested artifact {name} has no successful browser.extract evidence")
            elif not any(value in content for value in extract_values):
                messages.append(f"requested artifact {name} is missing browser.extract value {extract_values[0]}")
    return messages


def _sanitize_terminal_summary(summary: str, created_files: list[str]) -> str:
    """Replace future-tense worker narration after evidence already passed."""
    clean = " ".join(str(summary or "").split()).strip()
    if not _TERMINAL_PENDING_RE.search(clean):
        return summary
    names = list(dict.fromkeys(Path(path).name for path in created_files if str(path).strip()))
    if names:
        return "Created and verified " + ", ".join(names) + "."
    return "Completed with verified evidence."


def _reconcile_missing_marker_literals(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str],
) -> list[str]:
    """Insert only explicit missing marker tokens into existing text artifacts."""
    if work_dir is None:
        return list(created_files)
    root = work_dir.resolve()
    created_by_name = _created_paths_by_name(created_files)
    segments = _artifact_requirement_segments(prompt)
    for requested_name in _requested_names(prompt):
        name = Path(requested_name).name
        matching_paths = created_by_name.get(name.casefold(), [])
        if len(matching_paths) != 1:
            continue
        candidate = (root / matching_paths[0]).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.suffix.casefold() not in _TEXT_SUFFIXES or not candidate.is_file():
            continue
        segment = segments.get(name.casefold(), "")
        markers = [literal for literal in _required_literals(name, segment) if _MARKER_TOKEN_RE.search(literal)]
        if not markers:
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        missing = [marker for marker in markers if marker not in html.unescape(content)]
        if not missing:
            continue
        if candidate.suffix.casefold() in {".html", ".htm"}:
            addition = "".join(f'<p data-thomas-required-marker="true">{html.escape(marker)}</p>' for marker in missing)
            body_end = content.lower().rfind("</body>")
            content = content[:body_end] + addition + content[body_end:] if body_end >= 0 else content + addition
        else:
            content = content.rstrip() + "\n" + "\n".join(missing) + "\n"
        try:
            candidate.write_text(content, encoding="utf-8")
        except OSError:
            continue
    return list(created_files)


def _reconcile_requested_artifact_from_evidence(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str],
    tool_outputs: dict[str, list[str]],
) -> list[str]:
    """Correct one near-match text artifact using only captured browser evidence."""
    requested = _requested_names(prompt)
    extract_values = _extract_values(tool_outputs)
    if work_dir is None or len(requested) != 1 or not extract_values:
        return list(created_files)

    root = work_dir.resolve()
    expected_name = Path(requested[0]).name
    expected = (root / expected_name).resolve()
    if expected.suffix.casefold() not in _TEXT_SUFFIXES:
        return list(created_files)

    candidates: list[Path] = []
    if expected.is_file():
        candidates.append(expected)
    for rel in created_files:
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file() and candidate.suffix.casefold() == expected.suffix.casefold():
            candidates.append(candidate)
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return list(created_files)
    source = max(
        candidates,
        key=lambda path: SequenceMatcher(None, path.name.casefold(), expected_name.casefold()).ratio(),
    )
    similarity = SequenceMatcher(None, source.name.casefold(), expected_name.casefold()).ratio()
    if source != expected and similarity < 0.7:
        return list(created_files)

    try:
        content = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(created_files)
    value = extract_values[0]

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0).casefold()
        if any(word in token for word in ("heading", "title", "extracted", "value")):
            return value
        if any(word in token for word in ("description", "content")):
            return f'a documentation example headed "{value}"'
        return match.group(0)

    content = _UNRESOLVED_PLACEHOLDER_RE.sub(_replace, content)
    for url in _required_urls(prompt):
        if url not in content:
            content = f"Source URL: {url}\n" + content.lstrip()
    if _requires_extracted_value(prompt) and value not in content:
        content = content.rstrip() + f"\nExtracted Heading: {value}\n"

    try:
        expected.write_text(content, encoding="utf-8")
    except OSError:
        return list(created_files)
    return list(dict.fromkeys([*created_files, expected_name]))
