from __future__ import annotations

import re
from typing import Any

from thomas.core.file_access import PROJECT, READ_ONLY, clamp_file_access_level, file_access_spec
from thomas.server.chat_delegation_live_repo import _with_live_repo_change_requirement

TASK_MANAGER_BACKEND = "task_manager"
PROVIDER_NATIVE_BACKEND = "provider_native"

_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "couple": 2,
    "few": 3,
}
_MULTI_AGENT_COUNT_RE = re.compile(
    r"(?:spawn|start|launch|run|create|use)\s+"
    r"(?:exactly\s+)?(?:a\s+)?(?P<count>\d+|one|two|three|four|five|couple|few)\s+"
    r"(?:real\s+|live\s+|tiny\s+|distinct\s+|lightweight\s+|small\s+|task\s+)*"
    r"(?:sub[- ]?agents?|agents?|helpers?|workers?)",
    re.I,
)
_NUMBERED_DELIVERABLE_RE = re.compile(r"(?ms)^\s*(?P<number>\d{1,2})[.)]\s+(?P<body>.+?)(?=^\s*\d{1,2}[.)]\s+|\Z)")
_BULLETED_DELIVERABLE_RE = re.compile(r"(?ms)^[ \t]*[-*•][ \t]+(?P<body>.+?)(?=^[ \t]*[-*•][ \t]+|\Z)")
_DELIVERABLE_LIST_CUE_RE = re.compile(
    r"\b(?:deliverables?|outputs?|separately|individually)\b|"
    r"\bseparate\s+(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b",
    re.I,
)
_SINGLE_DELIVERABLE_CUE_RE = re.compile(
    r"\b(?:(?:exactly\s+)?one|single)\b[^:\n]{0,100}\b(?:these|the\s+following)\s+"
    r"(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b|"
    r"\b(?:(?:exactly\s+)?one|single)\b(?:\s+[\w-]+){0,5}\s+"
    r"(?:output|deliverable|result|artifact|document|file|report|package|bundle)\b|"
    r"\ba\s+(?:(?:single|final|combined|complete|consolidated|overall|polished|downloadable)\s+){1,5}"
    r"(?:output|deliverable|result|artifact|document|file|report|package|bundle)\b|"
    r"\b(?:a|an)\s+(?:[\w-]+\s+){0,5}"
    r"(?:report|document|package|bundle|file|output|deliverable|artifact|result|chart|game|app|website|"
    r"presentation|spreadsheet)\b",
    re.I,
)
_EXPLICIT_MULTI_OBJECT_CUE_RE = re.compile(
    r"\b(?:a|an|one)\s+(?:[\w-]+\s+){0,5}[\w-]+\s+and\s+"
    r"(?:a|an|one)\s+(?:[\w-]+\s+){0,5}[\w-]+\s+as\s+"
    r"(?:separate|distinct|individual)\s+"
    r"(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b",
    re.I,
)
_EXPLICIT_EACH_SEPARATE_CUE_RE = re.compile(
    r"\beach\s+of\s+(?:these|the\s+following)\s+(?:as\s+)?(?:a\s+)?"
    r"(?:separate|distinct|individual)\s+"
    r"(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b",
    re.I,
)
_COMBINE_INTO_SINGLE_RE = re.compile(
    r"\b(?:combine|merge|put|place|assemble|package)\s+"
    r"(?:them|both|all(?:\s+of\s+them)?|the\s+(?:outputs?|deliverables?|items?))\b"
    r"[^.:;\n]{0,80}\b(?:into|in|as)\s+(?:exactly\s+)?(?:one|a\s+single)\b",
    re.I,
)
_COMBINED_CONTAINER_RE = re.compile(
    r"(?:\b(?:(?:exactly\s+)?one|a(?:n)?(?:\s+single)?)\s+(?:[\w-]+\s+){0,3}"
    r"(?:dashboard|workbook|spreadsheet|deck|presentation|zip|archive|report|document|package|bundle)\b"
    r"[^:\n]{0,100}\b(?:contain(?:ing|s)?|includ(?:ing|es?)|with|from|using|"
    r"made\s+up\s+of|composed\s+of)\b[^:\n]{0,80}"
    r"\b(?:these|the\s+following|two|three|four|five|\d+)\s+"
    r"(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b|"
    r"\b(?:these|the\s+following|two|three|four|five|\d+)\s+"
    r"(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b"
    r"[^:\n]{0,80}\b(?:in|inside|into|within)\s+"
    r"(?:(?:exactly\s+)?one|a(?:n)?(?:\s+single)?)\s+(?:[\w-]+\s+){0,3}"
    r"(?:dashboard|workbook|spreadsheet|deck|presentation|zip|archive|report|document|package|bundle)\b)",
    re.I,
)
_PROCEDURAL_LIST_CUE_RE = re.compile(
    r"\b(?:separate|ordered|sequential|procedural)\s+steps?\b|"
    r"\bsteps?\s+(?:separately|in\s+order|sequentially)\b",
    re.I,
)
_NUMBERED_PROCEDURE_SEQUENCE_RE = re.compile(
    r"(?ms)^\s*\d{1,2}[.)]\s+(?:first\b|start\s+by\b|begin\s+by\b).+?"
    r"^\s*\d{1,2}[.)]\s+(?:then\b|next\b|finally\b|after\s+that\b)",
    re.I,
)
_DEFERRED_APPROVAL_RE = re.compile(
    r"\bonly\s+after\s+(?:i|we|you|the\s+user)\s+(?:approve|confirm|authorize|review)\b|"
    r"\b(?:if|once|after|when)\s+(?:i|we|you|the\s+user)\s+"
    r"(?:approve|confirm|authorize|review)(?:\s+them|\s+it)?\b|"
    r"\bpending\s+(?:my|our|your|the\s+user['â€™]?s?)\s+"
    r"(?:approval|confirmation|authorization)\b|"
    r"\bsubject\s+to\s+(?:my|our|your|the\s+user['â€™]?s?\s+)?"
    r"(?:approval|confirmation|authorization)\b",
    re.I,
)
_EXECUTION_REQUEST_RE = re.compile(
    r"^\s*(?:(?:please\s+)?(?:create|build|make|write|produce|generate|prepare|deliver|render|draft|design|export|assemble|develop)\b"
    r"|(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:create|build|make|write|produce|generate|prepare|deliver|render|draft|design|export|assemble|develop)\b"
    r"|i\s+(?:need|want|would\s+like)\s+(?:(?:you\s+to\s+)?(?:create|build|make|write|produce|generate|prepare|deliver|render|draft|design|export|assemble|develop)\s+)?"
    r"(?:these|the\s+following|two|three|four|five|\d+)\b"
    r"|please\s+(?:give|provide)\s+me\s+(?:these|the\s+following|two|three|four|five|\d+)\b)",
    re.I,
)
_NON_EXECUTION_HEADER_RE = re.compile(
    r"\b(?:review\w*|discuss\w*|explain\w*|analy[sz]\w*|consider\w*|evaluat\w*|compar\w*)\b",
    re.I,
)
_DELIVERABLE_ACTION_RE = re.compile(
    r"\b(?:create|build|make|write|produce|generate|prepare|deliver|render|draft|design|export|assemble|develop)\b",
    re.I,
)
_NON_EXECUTION_REQUEST_RE = re.compile(
    r"\b(?:(?:do\s+not|don['’]?t|dont|never)\s+"
    r"(?:do|execute|run|perform|carry\s+out|act\s+on|send|email|delete|modify|change|create|build|write|make)"
    r"|without\s+(?:doing|executing|running|performing|acting)"
    r"|no\s+execution"
    r"|(?:list|describe|review|plan|discuss|analy[sz]e|explain)(?:ed)?(?:\s+\w+){0,2}\s+only"
    r"|not\s+(?:created|produced|built|written|made|executed|run|performed)"
    r"|only\s+after\s+(?:i|we|you|the\s+user)\s+(?:approve|confirm|authorize|review)"
    r"|(?:if|once|after|when)\s+(?:i|we|you|the\s+user)\s+(?:approve|confirm|authorize|review)"
    r"|pending\s+(?:my|our|your|the\s+user['â€™]?s?)\s+(?:approval|confirmation|authorization)"
    r"|subject\s+to\s+(?:my|our|your|the\s+user['â€™]?s?\s+)?(?:approval|confirmation|authorization))\b",
    re.I,
)
_NUMBERED_ITEM_LINE_RE = re.compile(r"^\s*\d{1,2}[.)]\s+")
_DELIVERABLE_ITEM_LINE_RE = re.compile(r"^[ \t]*(?:\d{1,2}[.)]|[-*•])[ \t]+")
_DECLARED_DELIVERABLE_COUNT_RE = re.compile(
    r"\b(?P<count>\d+|two|three|four|five|couple|few)\s+"
    r"(?:(?:separate|distinct|individual)\s+)?"
    r"(?:deliverables?|outputs?|files?|results?|artifacts?|documents?|items?)\b",
    re.I,
)
_ARTIFACT_ACTION = (
    r"(?:create|build|make|write|draft|produce|generate|prepare|deliver|render|export|save|develop|"
    r"scaffold|implement|design|code|edit|update|fix|repair|revise|recreate|regenerate|refactor)"
)
_ARTIFACT_OBJECT = (
    r"(?:artifact|deliverable|file|document|report|pdf|csv|spreadsheet|workbook|deck|slides?|presentation|"
    r"app|application|game|website|site|webpage|web[\s-]*app|dashboard|chart|graph|diagram|image|script|"
    r"cli|tool|plugin|extension|api|server|service|[A-Za-z0-9][A-Za-z0-9_.-]*\."
    r"(?:md|txt|json|csv|tsv|html?|pdf|docx|xlsx|pptx|py|js|ts|tsx|jsx|css|svg|png|jpe?g|webp))"
)
_ARTIFACT_GAP = r"(?:[\s,:;\-]+[A-Za-z0-9_'/+\-]+){0,6}[\s,:;\-]+"
_REQUEST_PREAMBLE = r"^\s*(?:(?:okay|ok|please|now|then|also|hey|first|only)\b[\s,.:;!\-]*)*"
_ARTIFACT_WRITE_REQUEST_RE = re.compile(
    _REQUEST_PREAMBLE + rf"(?:(?:(?:can|could|would|will)\s+you|(?:i|we)\s+(?:need|want|would\s+like)\s+you\s+to|"
    rf"help\s+(?:me|us)(?:\s+to)?)\s+)?(?:please\s+)?{_ARTIFACT_ACTION}\b{_ARTIFACT_GAP}{_ARTIFACT_OBJECT}\b",
    re.I,
)
_INDIRECT_ARTIFACT_REQUEST_RE = re.compile(
    _REQUEST_PREAMBLE + rf"(?:(?:i|we)\s+(?:need|want|would\s+like)|i['’]d\s+like|"
    rf"(?:can|could|would)\s+(?:i|we)\s+(?:get|have)|"
    rf"(?:(?:can|could|would)\s+you\s+)?(?:give|provide)\s+(?:me|us)){_ARTIFACT_GAP}{_ARTIFACT_OBJECT}\b",
    re.I,
)
_CHAINED_ARTIFACT_REQUEST_RE = re.compile(
    _REQUEST_PREAMBLE + rf"(?:analyze|review|inspect|read|use|take|check|research|summarize)\b[\s\S]{{0,140}}"
    rf"\b(?:and|then|and\s+then|after\s+that|to)[\s,:;\-]+(?:please\s+)?{_ARTIFACT_ACTION}\b"
    rf"{_ARTIFACT_GAP}{_ARTIFACT_OBJECT}\b",
    re.I,
)
_PASSIVE_ARTIFACT_REQUEST_RE = re.compile(
    _REQUEST_PREAMBLE + rf"(?:(?:can|could|would)\s+you\s+)?(?:have|get)\b{_ARTIFACT_GAP}{_ARTIFACT_OBJECT}\b"
    r"(?:\s+[A-Za-z0-9_'/+\-]+){0,3}\s+"
    r"(?:generated|created|built|written|drafted|produced|prepared|rendered|exported|developed|implemented)\b",
    re.I,
)
_SCOPED_ARTIFACT_EXCEPTION_RE = re.compile(
    r"^\s*(?:please\s+)?(?:do\s+not|don['’]?t|dont)\s+(?:create|write|save|produce|generate|make)\s+"
    rf"(?:(?:a|any|the)?\s*(?:files?|artifacts?|downloads?)|anything)\s+"
    rf"(?:except|other\s+than)\s+{_ARTIFACT_OBJECT}\b",
    re.I,
)
_INLINE_ARTIFACT_RESPONSE_RE = re.compile(
    _REQUEST_PREAMBLE + rf"(?:(?:(?:(?:can|could|would|will)\s+you)\s+)?(?:please\s+)?{_ARTIFACT_ACTION}\b|"
    rf"(?:(?:can|could|would)\s+you\s+)?(?:give|provide)\s+(?:me|us)\b)"
    + _ARTIFACT_GAP
    + rf"{_ARTIFACT_OBJECT}\b(?:\s+(?:(?:right\s+)?here|directly))?\s+(?:(?:in|inside)\s+"
    r"(?:(?:the|this|your)\s+)?"
    r"(?:chat|answer|response|reply)|as\s+(?:plain\s+)?text(?:\s+in\s+(?:(?:the|this|your)\s+)?"
    r"(?:chat|answer|response|reply))?)\b",
    re.I,
)
_NAMED_ARTIFACT_OUTPUT_RE = re.compile(
    _REQUEST_PREAMBLE + rf"(?:(?:(?:can|could|would|will)\s+you)\s+)?(?:please\s+)?{_ARTIFACT_ACTION}\b[^.!?]{{0,180}}"
    r"\b(?:as|in|into|to|named|called|saved\s+as|exported\s+as|written\s+to)\s+"
    r"[A-Za-z0-9][A-Za-z0-9_.-]*\."
    r"(?:md|txt|json|csv|tsv|html?|pdf|docx|xlsx|pptx|py|js|ts|tsx|jsx|css|svg|png|jpe?g|webp)\b",
    re.I,
)
_ISOLATED_ARTIFACT_ASSIGNMENT_RE = re.compile(
    rf"^Assigned deliverable\s+\d+\s+of\s+\d+:\s*[^\n]*\b{_ARTIFACT_OBJECT}\b",
    re.I,
)
_INLINE_ONLY_ARTIFACT_RE = re.compile(
    r"\b(?:do\s+not|don['’]?t|dont|without)\s+(?:create|write|save|produce|generate|make)(?:\s+(?:a|any|the))?\s+"
    r"(?:file|artifact|download)\b(?!\s+(?:other\s+than|except))|"
    r"\b(?:create|write|save|produce|generate|make)\s+no\s+(?:files?|artifacts?|downloads?)\b"
    r"(?!\s+(?:other\s+than|except))|"
    r"\bnot\s+(?:as|in|to)\s+(?:a\s+)?file\b",
    re.I,
)
_INDIRECT_ADVISORY_RE = re.compile(
    r"\b(?:analysis|explanation|advice|recommendations?|summary|review|comparison|information|guidance)\s+"
    r"(?:of|about|on|for)\b",
    re.I,
)
_EFFORT_UI_LABELS = {
    "cheap": "Quick",
    "balanced": "Standard",
    "optimal": "Standard",
    "max": "Thorough",
    "exhaustive": "Thorough",
}
# A sizeable fs.write_file call (for example a complete playable HTML game) can
# legitimately spend more than a minute generating its JSON arguments before the
# next event arrives.  Keep a bounded watchdog, but do not kill healthy builds at
# the old 60-second boundary.
_WORKER_FIRST_EVENT_TIMEOUT_S = 180.0
_WORKER_IDLE_EVENT_TIMEOUT_S = 120.0
_WORKER_STREAM_CLOSE_TIMEOUT_S = 5.0
_WORKER_WATCHDOG_GRACE_S = 15.0


def _infer_specialist(prompt: str) -> str:
    text = str(prompt or "").lower()
    if any(
        token in text
        for token in ("code", "bug", "endpoint", "api", "test", "refactor", "implement", "game", "app", "website")
    ):
        return "coding"
    if any(token in text for token in ("research", "find", "look up", "compare", "investigate")):
        return "research"
    if any(token in text for token in ("tool", "command", "run ", "install", "configure", "setup", "set up")):
        return "tools"
    return "reasoning"


def _requested_delegate_count(prompt: str) -> int:
    text = str(prompt or "").strip().lower()
    if not text:
        return 1
    match = _MULTI_AGENT_COUNT_RE.search(text)
    if not match:
        return 1
    raw = str(match.group("count") or "").strip().lower()
    if raw.isdigit():
        value = int(raw)
    else:
        value = _COUNT_WORDS.get(raw, 1)
    return max(1, min(5, int(value or 1)))


def _prompt_requires_artifact_write(prompt: str) -> bool:
    """Return true only for an explicit request to create a file-backed deliverable."""

    raw_text = str(prompt or "").strip()
    if _ISOLATED_ARTIFACT_ASSIGNMENT_RE.match(raw_text):
        return True
    text = re.sub(r"\s+", " ", raw_text).strip()
    if not text:
        return False
    if _SCOPED_ARTIFACT_EXCEPTION_RE.match(text):
        return True
    if _INLINE_ONLY_ARTIFACT_RE.search(text) or _INLINE_ARTIFACT_RESPONSE_RE.match(text):
        return False
    if _NAMED_ARTIFACT_OUTPUT_RE.match(text):
        return True
    explicit_match = (
        _CHAINED_ARTIFACT_REQUEST_RE.match(text)
        or _PASSIVE_ARTIFACT_REQUEST_RE.match(text)
        or _ARTIFACT_WRITE_REQUEST_RE.match(text)
    )
    if explicit_match is not None:
        advisory_match = _INDIRECT_ADVISORY_RE.search(text)
        return advisory_match is None or advisory_match.start() >= explicit_match.end()
    indirect_match = _INDIRECT_ARTIFACT_REQUEST_RE.match(text)
    if indirect_match is None:
        return False
    advisory_match = _INDIRECT_ADVISORY_RE.search(text)
    return advisory_match is None or advisory_match.start() >= indirect_match.end()


def _agent_worker_permission_block(prompt: str, *, targets_live_repo: bool, file_access: int) -> tuple[str, str] | None:
    """Return a structured permission blocker before a worker is handed off."""

    spec = file_access_spec(file_access)
    if targets_live_repo and file_access < PROJECT:
        return (
            "file_access_too_low_for_self_development",
            "This task targets Thomas's live repo, but file access is "
            f"'{spec.ui_label}'. Raise the file-access dial to Project or higher, "
            "then retry so Thomas can work on the live checkout instead of a sandbox.",
        )
    if not targets_live_repo and file_access == READ_ONLY and _prompt_requires_artifact_write(prompt):
        return (
            "file_access_too_low_for_artifact",
            "This task needs to create files, but File access is "
            f"'{spec.ui_label}'. Open Tools > File access > Workspace, then retry.",
        )
    return None


def _requested_delegate_items(prompt: str) -> list[str]:
    """Return explicit top-level numbered deliverables, never recipe/checklist steps.

    Thomas used to fan out only when the user literally requested multiple agents. A
    numbered list of distinct outputs therefore went to one worker and was often
    collapsed into one generic Canvas. Require a deliverable-list cue and at least two
    sequential numbered rows so ordinary numbered instructions remain one task.
    """

    text = str(prompt or "").strip()
    if not text:
        return []
    matches = list(_NUMBERED_DELIVERABLE_RE.finditer(text))
    numbered = bool(matches)
    if not matches:
        matches = list(_BULLETED_DELIVERABLE_RE.finditer(text))
    if not 2 <= len(matches) <= 5:
        return []
    # Apply list-wide denial language only to the header and trailing shared
    # instructions. Item bodies may legitimately contain constraints such as
    # "analyze Q1 only" or "draft this email; do not send it".
    list_wide_context = _shared_deliverable_context(text)
    if not _DELIVERABLE_LIST_CUE_RE.search(list_wide_context):
        return []
    request_header = text[: matches[0].start()]
    declared_count = _DECLARED_DELIVERABLE_COUNT_RE.search(request_header)
    if declared_count:
        raw_count = str(declared_count.group("count") or "").strip().lower()
        expected_count = int(raw_count) if raw_count.isdigit() else _COUNT_WORDS.get(raw_count, 0)
        if expected_count and expected_count != len(matches):
            return []
    # A numbered procedure is still one deliverable even when its header says
    # "separate steps" or "one output". Running those rows concurrently can
    # invert required ordering (install before test, mix before bake).
    explicit_multi = bool(
        _EXPLICIT_MULTI_OBJECT_CUE_RE.search(request_header) or _EXPLICIT_EACH_SEPARATE_CUE_RE.search(request_header)
    )
    if _COMBINE_INTO_SINGLE_RE.search(list_wide_context):
        return []
    if _COMBINED_CONTAINER_RE.search(request_header):
        return []
    if _SINGLE_DELIVERABLE_CUE_RE.search(list_wide_context) and not explicit_multi:
        return []
    if _PROCEDURAL_LIST_CUE_RE.search(request_header) or _NUMBERED_PROCEDURE_SEQUENCE_RE.search(text):
        return []
    if _DEFERRED_APPROVAL_RE.search(text):
        return []
    if _NON_EXECUTION_REQUEST_RE.search(list_wide_context):
        return []
    # Only an explicit action request may cross the L1 chat boundary into
    # automatic workers. Descriptions, questions, and lists for discussion can
    # contain dangerous item verbs ("Email...", "Delete...") and must remain chat.
    if not _EXECUTION_REQUEST_RE.search(request_header):
        return []
    if _NON_EXECUTION_HEADER_RE.search(request_header) and not _DELIVERABLE_ACTION_RE.search(request_header):
        return []
    if numbered:
        numbers = [int(match.group("number")) for match in matches]
        if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
            return []
    items: list[str] = []
    for match in matches:
        raw_lines = str(match.group("body") or "").splitlines()
        if not raw_lines:
            return []
        # A list-wide sentence after the final numbered row ("Keep each as its
        # own result") is not part of that deliverable. Preserve only explicitly
        # indented continuation lines as item detail.
        item_lines = [raw_lines[0].strip()]
        for raw_line in raw_lines[1:]:
            if raw_line.startswith((" ", "\t")):
                item_lines.append(raw_line.strip())
            else:
                break
        items.append(re.sub(r"\s+", " ", " ".join(item_lines)).strip())
    return items if all(items) else []


def _shared_deliverable_context(prompt: str) -> str:
    """Keep list-wide constraints without leaking sibling deliverables.

    Numbered item lines and their indented continuations belong only to their
    assigned worker. Everything outside those item bodies (headers, attachment
    rules, data-source constraints, formatting rules) applies to every worker.
    """

    shared_lines: list[str] = []
    inside_item = False
    for raw_line in str(prompt or "").splitlines():
        if _DELIVERABLE_ITEM_LINE_RE.match(raw_line):
            inside_item = True
            continue
        if inside_item and raw_line.startswith((" ", "\t")):
            continue
        inside_item = False
        clean = raw_line.strip()
        if clean:
            shared_lines.append(clean)
    return re.sub(r"\s+", " ", " ".join(shared_lines)).strip()


def _helper_prompt(
    prompt: str,
    *,
    helper_index: int,
    helper_count: int,
    bot_name: str,
    assigned_item: str = "",
) -> str:
    if helper_count <= 1:
        return prompt
    assignment = str(assigned_item or "").strip()
    if assignment:
        shared_context = _shared_deliverable_context(prompt)
        shared_instruction = (
            f"\nShared instructions applying to this deliverable: {shared_context}\n" if shared_context else "\n"
        )
        return (
            f"Assigned deliverable {helper_index} of {helper_count}: {assignment}\n\n"
            f"[Isolated deliverable assignment]\n"
            f"Your only assigned deliverable is: {assignment}\n"
            f"{shared_instruction}"
            "You are intentionally not given the other deliverables. Produce and verify "
            "only this item as its own result. Do not create guessed companion outputs, "
            "stand in for, or claim completion of any other deliverable."
        ).strip()
    return (
        f"{prompt.rstrip()}\n\n"
        f"[Helper assignment]\n"
        f"You are helper {helper_index} of {helper_count} ({bot_name}). "
        f"Take a distinct slice of the work from the other helpers, avoid duplicating them, "
        f"and report concise progress."
    ).strip()


def _self_recovery_attempts(autonomy_level: int) -> int:
    """Bounded replan budget: 3 retries at max autonomy (L4), 1 pass below."""
    return 3 if int(autonomy_level or 0) >= 4 else 1


def _safe_autonomy_level(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(1, min(4, parsed or 1))


def _agent_worker_runtime_profile(
    *,
    autonomy_level: int,
    file_access: int | None,
    effort: str,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    guardrails: str,
    requires_live_repo_change: bool,
) -> dict[str, Any]:
    effective_autonomy = _safe_autonomy_level(autonomy_level)
    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)
    spec = file_access_spec(effective_file_access)
    return {
        "backend_type": PROVIDER_NATIVE_BACKEND,
        "autonomy_level": effective_autonomy,
        "file_access": effective_file_access,
        "file_access_label": spec.ui_label,
        "effort": str(effort or "").strip() or "diligent",
        "model_id": str(model_id or "").strip(),
        "reasoning_effort": str(reasoning_effort or "").strip().lower(),
        "build_quality_label": _EFFORT_UI_LABELS.get(str(effort or "").strip().lower(), str(effort or "").strip()),
        "guardrails": str(guardrails or "").strip(),
        "requires_live_repo_change": bool(requires_live_repo_change),
        "max_attempts": _self_recovery_attempts(effective_autonomy),
    }


def _replan_prompt(original: str, last_error: str, attempt: int, total: int) -> str:
    """Augment the task prompt with the prior failure so the next attempt adapts."""
    error_text = str(last_error or "")
    prompt = (
        f"{original}\n\n"
        f"[Self-recovery — attempt {attempt} of {total}]\n"
        f"A previous attempt did not succeed. The failure was:\n{error_text}\n\n"
        "Diagnose why it failed and take a DIFFERENT approach this time — do not "
        "repeat the steps that just failed. If a tool or capability seems missing, "
        "find another way to reach the goal with the tools you have."
    )
    error_lower = error_text.lower()
    if "requested artifact verification failed" in error_lower:
        missing_text = [
            (name, literal)
            for name, _quote, literal in re.findall(
                r"requested artifact\s+([A-Za-z0-9][A-Za-z0-9_.-]{1,160})\s+"
                r"is missing required text\s+(['\"])(.*?)\2",
                error_text,
                re.IGNORECASE,
            )
        ]
        missing = list(
            dict.fromkeys(
                re.findall(
                    r"missing exact requested artifact\s+([A-Za-z0-9][A-Za-z0-9_.-]{1,160})",
                    error_text,
                    re.IGNORECASE,
                )
            )
        )
        if missing:
            prompt += (
                "\n\nNo acceptable requested file exists yet. Your next substantive tool "
                "calls MUST be fs.write_file, one for each missing exact filename: "
                + ", ".join(missing)
                + ". Do not inspect or explain first. Write complete contents with no "
                "placeholders, then call fs.read_file on every filename and correct any "
                "mismatch before finishing."
            )
        else:
            prompt += (
                "\n\nThe prior run produced an artifact, but deterministic proof rejected its "
                "name or contents. Do not abandon the requested workflow and do not only "
                "explain the correction. Re-run every source/read tool needed for real "
                "values, then use fs.write_file to OVERWRITE the exact filename requested "
                "by the user with those values and no placeholders. Finally call "
                "fs.read_file on that exact filename and correct any remaining mismatch "
                "before finishing."
            )
        if missing_text:
            repair_lines = "\n".join(
                f"- {name} MUST contain this exact literal: {literal}" for name, literal in missing_text
            )
            affected = ", ".join(dict.fromkeys(name for name, _literal in missing_text))
            prompt += (
                "\n\nDeterministic verification identified these exact repairs:\n"
                f"{repair_lines}\n"
                f"Repair ONLY these rejected files: {affected}. Do not rewrite artifacts that already passed. "
                "For every rejected file, call fs.write_file with complete corrected contents containing "
                "every listed literal, then call fs.read_file and confirm each literal is present before "
                "finishing."
            )
    if "no write tool was used" in error_lower:
        prompt += (
            "\n\nThe previous attempt only inspected the repo. Stop broad inspection now: "
            "make the smallest scoped live-repo edit with fs.write_file, run the focused "
            "verification, or report the exact blocker that prevents the write. Your next "
            "substantive tool call must be fs.write_file or fs.write_protected_file. Do not "
            "call code.search, fs.read_file, fs.list_dir, git.status, or shell.exec again "
            "unless you first make a tracked source/test/doc edit or explicitly report why "
            "no edit is possible. For broad cleanup tasks, prefer a small regression test or "
            "catalog policy edit over continued architecture discovery."
        )
    elif "write tools used did not change counted files" in error_lower:
        prompt += (
            "\n\nA previous attempt called a write tool, but the write did not change any "
            "counted live-repo source/test/doc content. The next edit must change file "
            "content, not rewrite identical bytes, and it must target a non-ignored path "
            "outside runtime/, output/, library/, cache directories, and generated logs. "
            "Use fs.write_file on the smallest relevant tracked source/test/doc file with "
            "different content, then run focused verification. If you cannot identify a "
            "safe content change, report that blocker explicitly."
        )
    if "no live repo files" in error_lower:
        prompt = _with_live_repo_change_requirement(prompt)
    return prompt
