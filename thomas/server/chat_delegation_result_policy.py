"""Rules that distinguish a verified worker answer from progress or promises."""

from __future__ import annotations

import re

from thomas.server.chat_delegation_deliverable import (
    _FAILURE_LANGUAGE_RE,
    _claims_file_creation,
    _has_action_or_outcome_claim,
    _requests_action_execution,
    _tool_corresponds,
    _worker_summary_line,
)

_ACKNOWLEDGEMENT_ONLY_RE = re.compile(
    r"^(?:got it|okay|ok|done|confirmed|understood|sure|all set|sounds good|will do|on it)(?:[.!\s]+)?$",
    re.IGNORECASE,
)
_PROMISE_ONLY_RE = re.compile(
    r"^(?:(?:got it|okay|ok|done|confirmed|understood|sure|all set|sounds good|will do|on it)"
    r"[\s,;:\u2013\u2014-]*)?(?:(?:i|we)(?:['\u2019]?ll|\s+will)\b|"
    r"(?:i|we)(?:['\u2019]?m|\s+am|\s+are)\s+going\s+to\b|"
    r"(?:i|we)(?:['\u2019](?:m|re)|\s+am|\s+are)\s+(?:working|starting|get(?:ting)?\s+started)\b|"
    r"let\s+me\b)[^.!?]*(?:[.!?])?$",
    re.IGNORECASE,
)
_DEFERRED_ANSWER_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:have|has)\s+[^.;!?]{0,80}\s+ready\s*[;,:-]?\s*)?"
    r"(?:will|['\u2019]?ll)\s+(?:provide|send|share|deliver|return|give|answer|complete|finish)\b|"
    r"\b(?:answer|analysis|explanation|summary|result|response|report)\b[^.!?]{0,80}"
    r"\b(?:forthcoming|coming\s+(?:soon|shortly|later)|available\s+(?:soon|shortly|later)|"
    r"coming\s+(?:in\s+)?(?:the\s+)?(?:next|following)\s+(?:message|reply|response|turn)|"
    r"will\s+be\b[^.!?]{0,40}\b(?:soon|shortly|later|next))\b|"
    r"\b(?:details?|explanation|analysis|answer|summary|result|response|report|rest|remainder)\b"
    r"\s+(?:(?:is|are)\s+)?(?:still\s+)?(?:to\s+follow|coming\s+(?:soon|shortly|later))\b|"
    r"\b(?:rest|remainder)\s+(?:will|should)\s+(?:follow|come|arrive)\b",
    re.IGNORECASE,
)
_NONFINAL_PROGRESS_RE = re.compile(
    r"^\s*(?:[.\u2026\u2013\u2014-]+|\[(?:pending|processing)\]|\((?:pending|processing)\)|"
    r"status\s*:\s*(?:pending|complete|completed|finished|success|ready)|"
    r"no\s+answer\s+provided|nothing\s+to\s+report\s+yet|waiting|loading|starting|finishing\s+up|"
    r"(?:task\s+)?complete|ready|finished|success|complete\s+soon|answer\s+pending|"
    r"awaiting\s+(?:the\s+)?final\s+response|queued|(?:work\s+)?in\s+progress|not\s+yet\s+complete|"
    r"tbd|coming\s+up\s+next|i(?:['\u2019]?ll|\s+will)\s+be\s+right\s+back|still\s+processing|"
    r"response\s+pending\s+review|still\s+working|processing\s+(?:the\s+)?request|hold\s+on|"
    r"one\s+moment|to\s+be\s+continued|drafting\s+(?:the\s+)?answer\s+now|"
    r"(?:the\s+)?response\s+is\s+not\s+ready\s+yet|no\s+final\s+answer\s+yet|"
    r"pending\s+completion|calculating)\s*[.!?\u2026]*\s*$|\bmore\s+to\s+come\b|"
    r"\bcontinu(?:ed|es?|ing)\s+(?:in|on)\s+(?:my\s+|the\s+)?next\s+(?:message|reply|response|turn)\b|"
    r"\b(?:please\s+wait|stand\s+by)(?=\W|[^\x00-\x7f]|$)|"
    r"\b(?:answer|result|details?|response|analysis|explanation|summary)\b[^.!?]{0,40}"
    r"\b(?:will\s+(?:follow|come|arrive)|(?:follows?|coming|arrives?)\s+"
    r"(?:soon|shortly|later|next|in\s+(?:a|one)\s+moment))\b|"
    r"\b(?:almost\s+(?:done|finished|complete)|working\s+on\s+it)\b|"
    r"\b(?:answer|result|details?|response)\s+(?:soon|shortly|in\s+(?:a|one)\s+moment)\b",
    re.IGNORECASE,
)
_ARTIFACT_DELIVERABLE_REQUEST_RE = re.compile(
    r"(?:\[isolated deliverable assignment\]|\b(?:create|build|make|write|produce|generate|prepare|"
    r"deliver|render|draft|design|export|assemble|develop)\b[\s\S]{0,180}\b(?:artifact|deliverable|"
    r"output|file|game|app|website|chart|report|pdf|markdown|document|spreadsheet|presentation|image|"
    r"diagram|code|script)\b)",
    re.IGNORECASE,
)
_TEXT_ANSWER_KIND_RE = re.compile(
    r"\b(?:plan|outline|checklist|rubric|explanation|analysis|summary|recommendations?|"
    r"instructions?|strategy|steps?|ideas?|answer)\b",
    re.IGNORECASE,
)
_ARTIFACT_FILENAME_RE = re.compile(
    r"\b[A-Za-z0-9_-]+\.(?:pdf|docx|xlsx|pptx|html?|svg|png|jpe?g|gif|webp|csv|tsv|"
    r"md|markdown|txt|text|rtf|odt|json|py|js|ts|zip)\b",
    re.IGNORECASE,
)
_MATERIALIZATION_VERB_BEFORE_RE = re.compile(
    r"\b(?:create|build|make|write|produce|generate|prepare|deliver|render|draft|design|export|"
    r"assemble|develop|save)\b[^.!?\n]{0,160}$",
    re.IGNORECASE,
)
_SOURCE_FILENAME_PREFIX_RE = re.compile(r"\b(?:of|from|about)\s+(?:(?:this|the|an?|my)\s+)?$", re.IGNORECASE)
_EXPLICIT_ARTIFACT_FORMAT_REQUEST_RE = re.compile(
    r"(?:\b(?:export|save|convert|download|render)\b[^.!?\n]{0,120}\b"
    r"(?:pdf|docx|xlsx|pptx|html|svg|png|jpe?g|gif|webp|csv|markdown|md|zip)\b|"
    r"\b(?:as|into|in)\s+(?:an?\s+)?(?:pdf|docx|xlsx|pptx|html|svg|png|jpe?g|gif|webp|csv|markdown|md|zip)\b|"
    r"\bdownloadable\b)",
    re.IGNORECASE,
)
_EXPLICIT_MATERIALIZATION_REQUEST_RE = re.compile(
    r"\b(?:create|build|make|write|produce|generate|prepare|deliver|render|draft|design|export|"
    r"assemble|develop)\b[^.!?\n]{0,160}\b(?:as|into|in)\s+(?:an?\s+)?(?:downloadable\s+)?"
    r"(?:artifact|deliverable|file|document|spreadsheet|report|presentation|pdf|docx|xlsx|pptx|"
    r"html|svg|png|jpe?g|gif|webp|csv|tsv|markdown|md|txt|text|rtf|odt|json|zip)\b",
    re.IGNORECASE,
)
_CHAT_ONLY_NO_ARTIFACT_RE = re.compile(
    r"(?:\b(?:in|as)\s+(?:the\s+)?chat\b[\s\S]{0,160}\bdo\s+not\s+(?:create|make|write|save|export|"
    r"build|produce|generate)\b[\s\S]{0,80}\b(?:file|artifact|app|game|website)\b|"
    r"\bdo\s+not\s+(?:create|make|write|save|export|build|produce|generate)\b[\s\S]{0,80}"
    r"\b(?:file|artifact|app|game|website)\b[\s\S]{0,160}\b(?:in|as)\s+(?:the\s+)?chat\b)",
    re.IGNORECASE,
)
_HOW_TO_PREFIX_RE = re.compile(r"\bhow\s+to\s*$", re.IGNORECASE)
_NEGATED_REQUEST_PREFIX_RE = re.compile(r"\b(?:do\s+not|don't|never)\s+$", re.IGNORECASE)


def _requests_artifact_deliverable(prompt: str) -> bool:
    """Distinguish file/app requests from text answers that discuss artifacts."""
    text = str(prompt or "")
    if _CHAT_ONLY_NO_ARTIFACT_RE.search(text):
        return False
    if (
        "[isolated deliverable assignment]" in text.lower()
        or _EXPLICIT_ARTIFACT_FORMAT_REQUEST_RE.search(text)
        or _EXPLICIT_MATERIALIZATION_REQUEST_RE.search(text)
    ):
        return True
    filename = _ARTIFACT_FILENAME_RE.search(text)
    if filename:
        filename_prefix = text[max(0, filename.start() - 180) : filename.start()]
        if _MATERIALIZATION_VERB_BEFORE_RE.search(filename_prefix) and not _SOURCE_FILENAME_PREFIX_RE.search(
            filename_prefix
        ):
            return True
    artifact = None
    for match in _ARTIFACT_DELIVERABLE_REQUEST_RE.finditer(text):
        prefix = text[max(0, match.start() - 40) : match.start()]
        if _HOW_TO_PREFIX_RE.search(prefix) or _NEGATED_REQUEST_PREFIX_RE.search(prefix):
            continue
        artifact = match
        break
    if artifact is None:
        return False
    answer_kind = _TEXT_ANSWER_KIND_RE.search(text, artifact.start())
    artifact_kind = re.search(
        r"\b(?:artifact|deliverable|output|file|game|app|website|chart|report|markdown|document|"
        r"spreadsheet|presentation|image|diagram|code|script|pdf|docx|xlsx|pptx|html|svg|png|"
        r"jpe?g|gif|webp|csv|zip)\b",
        artifact.group(0),
        re.IGNORECASE,
    )
    if answer_kind and artifact_kind and answer_kind.start() < artifact.start() + artifact_kind.start():
        answer_end = answer_kind.end()
        artifact_start = artifact.start() + artifact_kind.start()
        # ``create a plan for testing file access`` asks for a text plan, while
        # ``create a checklist file`` and ``make a rubric spreadsheet`` explicitly
        # materialize that text as an artifact.
        return not bool(text[answer_end:artifact_start].strip())
    return True


def worker_text_is_confirmed_answer(
    result_text_parts: list[str],
    *,
    prompt: str = "",
    succeeded_tools: list[str] | None = None,
    failed_tools: list[str] | None = None,
) -> bool:
    worker_line = _worker_summary_line(result_text_parts)
    if not worker_line or _FAILURE_LANGUAGE_RE.search(worker_line):
        return False
    if _claims_file_creation(worker_line):
        return False
    full_text = " ".join(str(part) for part in (result_text_parts or []) if part is not None).strip()
    needs_action_proof = bool(_requests_action_execution(prompt) or _has_action_or_outcome_claim(full_text))
    if needs_action_proof:
        return bool(
            succeeded_tools and not failed_tools and _tool_corresponds(succeeded_tools, f"{prompt}\n{full_text}")
        )
    normalized = worker_line.strip()
    return not (
        _ACKNOWLEDGEMENT_ONLY_RE.fullmatch(normalized)
        or _PROMISE_ONLY_RE.fullmatch(normalized)
        or _DEFERRED_ANSWER_RE.search(normalized)
        or _NONFINAL_PROGRESS_RE.search(normalized)
        or _requests_artifact_deliverable(prompt)
    )


def should_finalize_exact_artifact_tool_result(
    prompt: str,
    *,
    last_tool: str,
    succeeded_tools: list[str],
    failed_tools: list[str],
) -> bool:
    read_tools = {"fs.read_file", "fs_read_file"}
    write_tools = {"fs.write_file", "fs_write_file"}
    succeeded = set(succeeded_tools)
    return bool(
        "exactly one downloadable artifact named" in str(prompt or "").lower()
        and last_tool in read_tools | write_tools
        and bool(write_tools & succeeded)
        and not failed_tools
    )
