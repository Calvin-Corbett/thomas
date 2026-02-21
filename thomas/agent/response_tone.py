"""Response tone + testing-visibility helper utilities."""

from __future__ import annotations

import re

from thomas.agent.prompt_templates import format_input_continuity_hint


def strip_robotic_opener(text: str) -> tuple[str, bool]:
    src = str(text or "")
    if not src.strip():
        return src, False
    cleaned = re.sub(
        r"^\s*(understood|got it|certainly|absolutely|sure)\s*[,.:!-]*\s+",
        "",
        src,
        count=1,
        flags=re.I,
    )
    changed = cleaned != src
    return (cleaned if cleaned.strip() else src), changed


def prompt_has_frustration_signal(prompt_text: str) -> bool:
    src = str(prompt_text or "").lower()
    if not src:
        return False
    return bool(
        re.search(
            r"\b(frustrat(?:ed|ing)?|annoy(?:ed|ing)?|upset|not working|too robotic|sound robotic|talk better|person skills|this sucks)\b",
            src,
        )
    )


def response_has_ack_signal(text: str) -> bool:
    src = str(text or "").lower()
    if not src:
        return False
    return bool(
        re.search(
            r"\b(you'?re right|you are right|fair point|that makes sense|i hear you|good call|thanks for calling that out)\b",
            src,
        )
    )


def apply_social_tone_adjustments(text: str, *, prompt_text: str) -> tuple[str, bool]:
    src = str(text or "")
    if not src.strip():
        return src, False
    out = src
    changed = False

    out2, stripped = strip_robotic_opener(out)
    if stripped:
        out = out2
        changed = True

    # Avoid injecting stock acknowledgement text; keep the model's own voice.

    # Remove robotic filler fragments that can survive beyond the opener position.
    out2 = re.sub(r"(?i)(?:^|\s)(?:understood|got it|certainly|absolutely)\.(?:\s|$)", " ", out)
    if out2 != out:
        out = re.sub(r"\s{2,}", " ", out2).strip()
        changed = True

    return out, changed


_REASONING_BLOCK_TAG_RE = re.compile(
    r"(?is)<\s*(thinking|analysis|reasoning)\b[^>]*>.*?</\s*\1\s*>"
)
_REASONING_BLOCK_FENCE_RE = re.compile(
    r"(?is)```(?:analysis|reasoning|thinking|chain[- ]?of[- ]?thought)\s+.*?```"
)
_REASONING_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:(?:ok(?:ay)?|alright|right|well|sure)\s*[,:\-]\s*)?"
    r"(?:let me|lemme|i(?:'m| am| will|\'ll| am going to))\s+"
    r"(?:think(?: this through)?|reason(?: this out)?|walk through (?:my )?(?:thinking|reasoning)|"
    r"break(?: this)? down|analy[sz]e(?: this)?|figure (?:this )?out)\b[^.!?\n]*(?:[.!?]|$)\s*"
)

_REASONING_LINE_PATTERNS = (
    r"^\s*(?:thinking out loud|internal reasoning|chain of thought)\b.*$",
    r"^\s*(?:let me|lemme)\s+(?:think|reason|walk through|break(?: this)? down|analy[sz]e)\b.*$",
    r"^\s*i(?:'m| am)\s+(?:thinking|reasoning|analyzing)\b.*$",
    r"^\s*i(?:'ll| will| am going to)\s+(?:think|reason|analy[sz]e)\b.*$",
)
_META_REASONING_PHRASE_RE = re.compile(
    r"(?i)\b(?:here(?:'s| is)\s+)?(?:my\s+)?(?:thought process|chain of thought|internal reasoning)\b[:\-]?\s*"
)
_AS_AI_PREFIX_RE = re.compile(
    r"(?i)^\s*as an ai(?: language)? model[,:\-]?\s*"
)
_TOOL_CALL_ARTIFACT_BLOCK_RE = re.compile(
    r"(?is)(?:```(?:json)?\s*)?\{\s*(?:\\?\")name(?:\\?\")\s*:\s*(?:\\?\")[A-Za-z0-9_.:-]+(?:\\?\")\s*,\s*(?:\\?\")arguments(?:\\?\")\s*:\s*\{.*?\}\s*\}(?:\s*```)?"
)
_TOOL_CALL_PSEUDO_BLOCK_RE = re.compile(
    r"(?is)(?:^|\n)\s*(?:sh|bash|json|python)\s*\n\s*Copy\s*\n\s*(?:[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\s*\(.*?\)|[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*(?:\s+[^\n]+)?|[a-z_][a-z0-9_]*\s*\(.*?\))\s*(?=\n{2,}|\Z)"
)
_TOOL_CALL_PSEUDO_LINE_RE = re.compile(
    r"(?im)^\s*(?:[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\s*\(.*\)|[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*(?:\s+[a-z_][a-z0-9_]*\s*=\s*\"[^\"]*\")*|[a-z_][a-z0-9_]*\s*\(.*\))\s*$"
)
_REASONING_REQUEST_RE = re.compile(
    r"\b(think out loud|thought process|chain of thought|internal reasoning|reason step by step)\b",
    re.I,
)
_STEPWISE_OUTPUT_RE = re.compile(
    r"\b(step by step|steps|checklist|walkthrough|guide|tutorial|roadmap|plan)\b",
    re.I,
)
_REASONING_SCAFFOLD_RE = re.compile(
    r"(?is)\b(let'?s break down|step by step|thought process|reasoning)\b"
)
_NUMBERED_LIST_RE = re.compile(r"(?m)^\s*\d+\.\s+")
_ANSWER_SENTENCE_RE = re.compile(
    r"(?is)(therefore|so|thus|final answer|answer to .*? is|the answer is)\b.*?[.!?](?:\s|$)"
)


def _prompt_allows_stepwise_output(prompt_text: str) -> bool:
    src = str(prompt_text or "")
    if not src.strip():
        return False
    if _REASONING_REQUEST_RE.search(src):
        return False
    return bool(_STEPWISE_OUTPUT_RE.search(src))


def _extract_final_answer_sentence(text: str) -> str:
    src = str(text or "").strip()
    if not src:
        return ""
    matches = list(_ANSWER_SENTENCE_RE.finditer(src))
    if not matches:
        return ""
    tail = matches[-1].group(0).strip()
    return re.sub(r"\s+", " ", tail).strip()


def strip_internal_reasoning_narration(text: str, *, prompt_text: str = "") -> tuple[str, bool]:
    """Remove internal-monologue leakage while preserving user-facing content."""
    src = str(text or "")
    if not src.strip():
        return src, False

    out = src
    changed = False

    out2 = _REASONING_BLOCK_TAG_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = _REASONING_BLOCK_FENCE_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    while True:
        out2 = _REASONING_PREFIX_RE.sub("", out, count=1)
        if out2 == out:
            break
        out = out2
        changed = True

    cleaned_lines: list[str] = []
    for line in out.splitlines():
        if any(re.search(pat, line, re.I) for pat in _REASONING_LINE_PATTERNS):
            changed = True
            continue
        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines)

    out2 = _META_REASONING_PHRASE_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = _AS_AI_PREFIX_RE.sub("", out, count=1)
    if out2 != out:
        out = out2
        changed = True

    if (
        not _prompt_allows_stepwise_output(prompt_text)
        and _REASONING_SCAFFOLD_RE.search(out)
        and _NUMBERED_LIST_RE.search(out)
    ):
        answer_sentence = _extract_final_answer_sentence(out)
        if answer_sentence:
            out = answer_sentence
            changed = True

    if changed:
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\s+([.,!?])", r"\1", out)
        out = out.strip()

    if out:
        return out, changed
    if changed:
        return "I will keep it direct. Tell me the exact outcome you want.", True
    return src, False


def prompt_requests_structured_output(prompt_text: str) -> bool:
    src = str(prompt_text or "")
    if not src.strip():
        return False
    return bool(
        re.search(
            r"\b(json|yaml|xml|schema|structured|machine[- ]readable|code block|raw output)\b",
            src,
            re.I,
        )
    )


def strip_tool_call_artifacts(text: str, *, prompt_text: str = "") -> tuple[str, bool]:
    """Remove raw tool-call JSON snippets that leak into assistant prose."""
    src = str(text or "")
    if not src.strip():
        return src, False
    if prompt_requests_structured_output(prompt_text):
        return src, False

    out = src
    changed = False

    out2 = _TOOL_CALL_ARTIFACT_BLOCK_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = _TOOL_CALL_PSEUDO_BLOCK_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = re.sub(r"(?im)^\s*(json|copy)\s*$", "", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = _TOOL_CALL_PSEUDO_LINE_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = re.sub(r"(?im)^\s*(sh|bash|powershell)\s*$", "", out)
    if out2 != out:
        out = out2
        changed = True

    if changed:
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\s+([.,!?])", r"\1", out)
        out = out.strip()

    return (out if out else src), changed


def apply_directness_constraints(text: str, *, prompt_text: str = "") -> tuple[str, bool]:
    """Honor explicit brevity/shape asks like 'one sentence' or 'one thing'."""
    src = str(text or "")
    prompt = str(prompt_text or "")
    if not src.strip() or not prompt.strip():
        return src, False

    prompt_l = prompt.lower()
    asks_one_sentence = bool(re.search(r"\b(one|single)\s+sentence\b", prompt_l))
    asks_one_thing_short_window = bool(
        re.search(r"\bone thing\b", prompt_l)
        and re.search(r"\bnext\b.*\bminute", prompt_l)
    )
    asks_brief = bool(re.search(r"\b(brief|concise|short answer|keep it short)\b", prompt_l))
    asks_first_step = bool(
        re.search(
            r"\b(where should i look first|what should i do first|what should i look at first|first step|first thing)\b",
            prompt_l,
        )
    )

    out = src
    changed = False

    if asks_one_sentence:
        pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", out.strip()) if p.strip()]
        if pieces:
            first = pieces[0]
            if first != out.strip():
                out = first
                changed = True

    if asks_one_thing_short_window:
        pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", out.strip()) if p.strip()]
        if len(pieces) > 1 and pieces[-1].endswith("?"):
            out = " ".join(pieces[:-1]).strip()
            changed = True

    if asks_brief:
        words = re.findall(r"\S+", out)
        if len(words) > 40:
            out = " ".join(words[:40]).rstrip(",;:.")
            if not out.endswith((".", "!", "?")):
                out += "."
            changed = True

    if asks_first_step:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        prioritized = ""
        for ln in lines:
            if re.match(r"^[A-Za-z][A-Za-z /-]{2,30}:\s+.+", ln):
                prioritized = ln
                break
        if not prioritized:
            pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", out.strip()) if p.strip()]
            if pieces:
                skip_intro = re.compile(r"\b(check(?:ing)? the following|troubleshoot|start by checking)\b", re.I)
                for p in pieces:
                    if not skip_intro.search(p):
                        prioritized = p
                        break
                if not prioritized:
                    prioritized = pieces[0]
        if prioritized and prioritized != out.strip():
            out = prioritized
            changed = True

    return (out if out else src), changed


def prompt_requests_directness_constraints(prompt_text: str) -> bool:
    prompt_l = str(prompt_text or "").lower()
    if not prompt_l:
        return False
    if re.search(r"\b(one|single)\s+sentence\b", prompt_l):
        return True
    if re.search(r"\bone thing\b", prompt_l) and re.search(r"\bnext\b.*\bminute", prompt_l):
        return True
    if re.search(r"\b(brief|concise|short answer|keep it short)\b", prompt_l):
        return True
    if re.search(r"\b(where should i look first|what should i do first|what should i look at first|first step|first thing)\b", prompt_l):
        return True
    return False


def _prompt_asks_for_location(prompt_text: str) -> bool:
    src = str(prompt_text or "").lower()
    if not src:
        return False
    return bool(
        re.search(
            r"\b("
            r"where (?:is|are)|"
            r"which (?:folder|directory|path|repo|workspace)|"
            r"what (?:folder|directory|path) are you in|"
            r"what(?:'s| is) (?:the )?(?:path|directory|folder|cwd|working directory)|"
            r"current (?:path|directory|folder|cwd|working directory)|"
            r"show (?:me )?(?:path|directory|folder)|"
            r"print (?:path|cwd|working directory)"
            r")\b",
            src,
        )
    )


def strip_unprompted_workspace_references(text: str, *, prompt_text: str) -> tuple[str, bool]:
    """Remove unsolicited absolute-path/workspace mentions from casual replies."""
    src = str(text or "")
    if not src.strip():
        return src, False
    if _prompt_asks_for_location(prompt_text):
        return src, False

    out = src
    changed = False

    out2 = re.sub(
        r"(?i)\bwhat do you want to work on in\s+`[^`]+`\??",
        "What do you want to work on?",
        out,
    )
    if out2 != out:
        out = out2
        changed = True

    out2 = re.sub(
        r"(?i)\bready to proceed in\s+`[^`]+`",
        "ready to proceed",
        out,
    )
    if out2 != out:
        out = out2
        changed = True

    out2 = re.sub(r"(?i)\s+\b(?:in|from)\s+`[A-Za-z]:\\[^`]+`", "", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = re.sub(r"(?i)\s+\bin\s+this\s+workspace\b", "", out)
    if out2 != out:
        out = out2
        changed = True

    if changed:
        out = re.sub(r"\s{2,}", " ", out)
        out = re.sub(r"\s+([.,!?])", r"\1", out)
        out = out.strip()

    return (out if out else src), changed


def live_test_default_hint(prompt_text: str) -> str:
    src = str(prompt_text or "").strip().lower()
    if not src:
        return ""
    asks_testing = bool(re.search(r"\b(test|verify|validation|smoke|qa|check)\b", src))
    browserish = bool(re.search(r"\b(browser|ui|chrome|screen|visible|live|shadow)\b", src))
    if not (asks_testing and browserish):
        return ""
    if re.search(r"\b(shadow|headless|hidden|background)\b", src):
        return ""
    hint = (
        "- For browser/UI self-tests, default to live visible execution in Chrome.\n"
        "- Use shadow/headless tests only when explicitly requested."
    )
    return format_input_continuity_hint(hint).strip()
