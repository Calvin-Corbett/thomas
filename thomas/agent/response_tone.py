"""Response tone + testing-visibility helper utilities."""

from __future__ import annotations

import re

from thomas.agent.prompt_templates import format_input_continuity_hint


def strip_robotic_opener(text: str) -> tuple[str, bool]:
    src = str(text or "")
    if not src.strip():
        return src, False
    # Only strip clearly robotic openers — NOT natural conversational ones.
    # "Sure, I can help" is fine. "Certainly! I would be delighted" is not.
    cleaned = re.sub(
        r"^\s*(certainly|absolutely)\s*[!.:,-]*\s+",
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
    if _is_code_sensitive_output(prompt_text, src):
        # Preserve whitespace/indentation for code-centric replies.
        return src, False
    out = src
    changed = False

    out2, stripped = strip_robotic_opener(out)
    if stripped:
        out = out2
        changed = True

    # Avoid injecting stock acknowledgement text; keep the model's own voice.

    # Remove only clearly robotic filler fragments mid-text.
    # Keep "got it" and "understood" as they're natural conversational markers.
    if prompt_has_frustration_signal(prompt_text):
        out2 = re.sub(r"(?i)(?:^|\s)(?:understood)\.?,?(?:\s|$)", " ", out)
        if out2 != out:
            out = re.sub(r"\s{2,}", " ", out2).strip()
            changed = True

    out2 = re.sub(r"(?i)(?:^|\s)(?:certainly|absolutely)\.(?:\s|$)", " ", out)
    if out2 != out:
        out = re.sub(r"[ \t]{2,}", " ", out2).strip()
        changed = True

    return out, changed


_REASONING_BLOCK_TAG_RE = re.compile(r"(?is)<\s*(thinking|analysis|reasoning)\b[^>]*>.*?</\s*\1\s*>")
_REASONING_BLOCK_FENCE_RE = re.compile(r"(?is)```(?:analysis|reasoning|thinking|chain[- ]?of[- ]?thought)\s+.*?```")
# Catch entire candidate-selection reasoning blocks that leak from the LLM.
# Pattern: everything from "Selected candidate" up to and including
# a quoted "Final selected reply" (or the end of text).
_CANDIDATE_SELECTION_BLOCK_RE = re.compile(
    r"(?is)selected?\s*candidate\s*[:=#\d].*?"
    r"(?:final\s+selected\s+(?:reply|response|answer|output)\s*[:=]\s*"
    r"""(?:"[^"]*"|'[^']*'|[^\n]+)"""
    r"|\Z)"
)
# Same pattern but for garbled no-space variants from Codex tokenizer.
# e.g. "Selectedcandidate:3Rationale(tone+safety):...Finalselectedreply:\"...\""
_CANDIDATE_SELECTION_NOSPACE_RE = re.compile(
    r"(?i)Select(?:ed)?candidate\s*[:=#\d].*?"
    r"(?:Final\s*selected\s*(?:reply|response|answer|output)\s*[:=]\s*"
    r"""(?:\u201c[^\u201d]*\u201d|"[^"]*"|'[^']*'|[^\n]+)"""
    r"|\Z)"
)
# Extract the actual user-facing reply from a garbled reasoning block.
# Looks for quoted text after "Finalselectedreply:" (with or without spaces).
_EXTRACT_FINAL_REPLY_RE = re.compile(
    r"""(?i)final\s*selected\s*(?:reply|response|answer|output)\s*[:=]\s*"""
    r"""(?:\u201c([^\u201d]*)\u201d|"([^"]*)"|'([^']*)')"""
)

# --- Codex work-summary patterns ---
# The Codex model sometimes treats chat replies as "tasks" and appends a full
# work summary: "Final response to user: `...` Demo script: `...`
# Files changed/created: ... Tests: ..."
# In the no-space garbled variant these become:
# "Finalresponsetouser:`...`Demoscript:..."
_WORK_SUMMARY_BLOCK_RE = re.compile(r"(?i)(?:Final\s*response\s*to\s*(?:the\s*)?user\s*[:=])")
# Extract the backtick-quoted reply from "Final response to user: `reply`"
_EXTRACT_USER_RESPONSE_RE = re.compile(
    r"""(?i)Final\s*response\s*to\s*(?:the\s*)?user\s*[:=]\s*""" r"""(?:`([^`]+)`|"([^"]+)"|'([^']+)')"""
)
# Catch everything after the user reply that is work-summary debris:
# Demo script, Files changed, Tests, etc.
_WORK_SUMMARY_TAIL_RE = re.compile(
    r"(?i)(?:Demo\s*script|Files?\s*changed|Files?\s*created|Tests?\s*:)" r".*$",
    re.DOTALL,
)


# Detect garbled no-space text from Codex tokenizer.
# If average word length exceeds 12 characters, the text is likely garbled.
def _looks_garbled(text: str) -> bool:
    """Return True if text appears to be garbled (no spaces between words)."""
    stripped = text.strip()
    if not stripped:
        return False
    # If text has backtick-quoted sections, check outside those
    clean = re.sub(r"`[^`]*`", "", stripped)
    if not clean.strip():
        return False
    words = clean.split()
    if len(words) <= 2:
        # Very few words — check if any single "word" is suspiciously long
        # and contains mixed case transitions (e.g. "yo!what'sup?WhatcanI")
        for w in words:
            if len(w) > 30 and re.search(r"[a-z][A-Z]", w):
                return True
        return False
    avg_len = sum(len(w) for w in words) / len(words)
    return avg_len > 12


# Unambiguous words (4+ chars) safe to split before.
# Avoids short words like "can"/"are"/"for" that appear inside longer words.
_GARBLED_SAFE_WORDS = [
    "What",
    "Where",
    "When",
    "Which",
    "While",
    "Could",
    "Would",
    "Should",
    "Have",
    "Help",
    "Here",
    "However",
    "This",
    "That",
    "There",
    "These",
    "Those",
    "Then",
    "Than",
    "With",
    "From",
    "About",
    "Into",
    "Your",
    "Today",
    "Just",
    "Only",
    "Also",
    "Still",
    "Some",
    "More",
    "Most",
    "Many",
    "Much",
    "Like",
    "Want",
    "Need",
    "Know",
    "Think",
    "Make",
    "Does",
    "Will",
    "Well",
    "Going",
    "Doing",
    "Being",
    "Classic",
    "Sure",
    "Hello",
    "Great",
]


def _fix_garbled_spaces(text: str) -> str:
    """Attempt to insert spaces into garbled no-space text.

    Only call this on text already detected as garbled by _looks_garbled().
    """
    out = text
    # Pass 1: Space after sentence-ending punctuation followed by a letter
    out = re.sub(r"([?!.])([A-Za-z])", r"\1 \2", out)
    # Pass 2: camelCase boundaries (e.g. "helpYou" → "help You")
    out = re.sub(r"([a-z])([A-Z])", r"\1 \2", out)
    # Pass 3: Insert space before unambiguous words when jammed after lowercase
    for word in _GARBLED_SAFE_WORDS:
        out = re.sub(r"([a-z])(" + re.escape(word) + r")", r"\1 \2", out, flags=re.I)
    # Clean up double spaces
    out = re.sub(r"  +", " ", out)
    return out


_REASONING_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:(?:ok(?:ay)?|alright|right|well|sure)\s*[,:\-]\s*)?"
    r"(?:let me|lemme|i(?:'m| am| will|\'ll| am going to))\s+"
    r"(?:think(?: this through)?|reason(?: this out)?|walk through (?:my )?(?:thinking|reasoning)|"
    r"break(?: this)? down|analy[sz]e(?: this)?|figure (?:this )?out|"
    r"inspect|check|look(?: into)?|search|scan|read|open)\b[^.!?\n]*(?:[.!?]|$)\s*"
)

_REASONING_LINE_PATTERNS = (
    r"^\s*(?:thinking out loud|internal reasoning|chain of thought)\b.*$",
    r"^\s*(?:let me|lemme)\s+(?:think|reason|walk through|break(?: this)? down|analy[sz]e|inspect|check|look(?: into)?|search|scan|read|open)\b.*$",
    r"^\s*i(?:'m| am)\s+(?:thinking|reasoning|analyzing)\b.*$",
    r"^\s*i(?:'ll| will| am going to)\s+(?:think|reason|analy[sz]e|inspect|check|look(?: into)?|search|scan|read|open)\b.*$",
    # Candidate selection / evaluation reasoning
    r"^\s*(?:selected?\s+)?candidate\s*[:=#\d].*$",
    r"^\s*rationale\b.*$",
    r"^\s*final\s+selected\s+(?:reply|response|answer|output)\s*[:=].*$",
    r"^\s*(?:option|choice|candidate)\s*\d+\s*[:=].*$",
    r"^\s*scoring\s*[:=].*$",
    r"^\s*evaluation\s*[:=].*$",
    r"^\s*(?:tone|safety|quality)\s*(?:\+\s*(?:tone|safety|quality))*\s*[:=].*$",
    # Rubric / scoring patterns
    r"^\s*(?:impact|feasibility|strategic\s*fit|differentiation|time.to.value)\s*\(?\s*\d+\s*\)?\s*[:\|].*$",
    # Codex work-summary patterns
    r"^\s*final\s*response\s*to\s*(?:the\s*)?user\s*[:=].*$",
    r"^\s*demo\s*script\s*[:=].*$",
    r"^\s*files?\s*(?:changed|created)\s*(?:/\s*(?:changed|created))?\s*[:=].*$",
    r"^\s*tests?\s*[:=].*$",
    r"^\s*no\s*code\s*changes\s*were\s*made.*$",
    r"^\s*expected\s*(?:assistant\s*)?output\s*[:=].*$",
)
_META_REASONING_PHRASE_RE = re.compile(
    r"(?i)\b(?:here(?:'s| is)\s+)?(?:my\s+)?(?:thought process|chain of thought|internal reasoning)\b[:\-]?\s*"
)
_AS_AI_PREFIX_RE = re.compile(r"(?i)^\s*as an ai(?: language)? model[,:\-]?\s*")
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
_REASONING_SCAFFOLD_RE = re.compile(r"(?is)\b(let'?s break down|step by step|thought process|reasoning)\b")
_NUMBERED_LIST_RE = re.compile(r"(?m)^\s*\d+\.\s+")
_ANSWER_SENTENCE_RE = re.compile(
    r"(?is)(therefore|so|thus|final answer|answer to .*? is|the answer is)\b.*?[.!?](?:\s|$)"
)
_CODE_OUTPUT_PROMPT_RE = re.compile(
    r"(?is)"
    r"(?:\b(return|respond|output|emit)\b[^.\n]{0,120}\b(?:only|just)\b[^.\n]{0,120}\b"
    r"(?:code|python|json|yaml|xml|sql|bash|shell)\b)"
    r"|(?:\bonly the (?:python\s+)?code\b)"
    r"|(?:\bcode continuation\b)"
    r"|(?:\bno explanations?\b)"
    r"|(?:\bno markdown\b)"
)
_CODE_LINE_RE = re.compile(
    r"(?m)^\s*(?:"
    r"def\b|class\b|import\b|from\b|if\b|elif\b|else:|for\b|while\b|try:|except\b|with\b|"
    r"return\b|yield\b|pass\b|break\b|continue\b|"
    r"@[A-Za-z_][\w.]*|"
    r"[A-Za-z_][A-Za-z0-9_]*\s*=|"
    r"#"
    r")"
)


def prompt_requests_code_output(prompt_text: str) -> bool:
    src = str(prompt_text or "")
    if not src.strip():
        return False
    if _CODE_OUTPUT_PROMPT_RE.search(src):
        return True
    # A prompt containing explicit function/class snippets usually expects code output.
    return bool(re.search(r"(?m)^\s*(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\b", src))


def _text_looks_code(text: str) -> bool:
    src = str(text or "")
    if not src.strip():
        return False
    hits = len(_CODE_LINE_RE.findall(src))
    if hits >= 2:
        return True
    if hits >= 1 and any(line.startswith((" ", "\t")) for line in src.splitlines() if line.strip()):
        return True
    return False


def _is_code_sensitive_output(prompt_text: str, text: str) -> bool:
    return prompt_requests_code_output(prompt_text) or _text_looks_code(text)


def _ensure_first_code_line_indented(text: str) -> str:
    lines = str(text or "").splitlines()
    first_idx = -1
    for idx, line in enumerate(lines):
        if line.strip():
            first_idx = idx
            break
    if first_idx < 0:
        return str(text or "")
    first = lines[first_idx]
    if first.startswith((" ", "\t")):
        return str(text or "")
    if any(line.startswith((" ", "\t")) for line in lines[first_idx + 1 :] if line.strip()):
        lines[first_idx] = "    " + first
        return "\n".join(lines)
    return str(text or "")


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


def _likely_reasoning_or_work_summary(text: str) -> bool:
    src = str(text or "")
    if not src.strip():
        return False

    if _looks_garbled(src):
        return True

    if (
        _WORK_SUMMARY_BLOCK_RE.search(src)
        or _EXTRACT_USER_RESPONSE_RE.search(src)
        or _WORK_SUMMARY_TAIL_RE.search(src)
        or _REASONING_BLOCK_TAG_RE.search(src)
        or _REASONING_BLOCK_FENCE_RE.search(src)
        or _REASONING_SCAFFOLD_RE.search(src)
        or _CANDIDATE_SELECTION_BLOCK_RE.search(src)
        or _CANDIDATE_SELECTION_NOSPACE_RE.search(src)
        or _EXTRACT_FINAL_REPLY_RE.search(src)
        or _REASONING_PREFIX_RE.search(src)
        or _META_REASONING_PHRASE_RE.search(src)
        or _AS_AI_PREFIX_RE.search(src)
    ):
        return True

    for line in src.splitlines():
        if any(re.search(pat, line, re.I) for pat in _REASONING_LINE_PATTERNS):
            return True
    return False


def strip_internal_reasoning_narration(text: str, *, prompt_text: str = "") -> tuple[str, bool]:
    """Remove internal-monologue leakage while preserving user-facing content."""
    src = str(text or "")
    if not src.strip():
        return src, False
    code_sensitive = _is_code_sensitive_output(prompt_text, src)
    if not _likely_reasoning_or_work_summary(src):
        return src, False

    out = src
    changed = False

    # --- Priority 1: Codex work-summary format ---
    # The Codex model often wraps its reply in a work-summary block:
    #   "Final response to user: `actual reply here` Demo script: ..."
    # In garbled no-space form: "Finalresponsetouser:`actualreplyhere`Demoscript:..."
    _user_response_match = _EXTRACT_USER_RESPONSE_RE.search(out)
    if _user_response_match:
        extracted = (
            _user_response_match.group(1) or _user_response_match.group(2) or _user_response_match.group(3) or ""
        )
        if extracted.strip():
            out = extracted.strip()
            # If the extracted reply is itself garbled, fix spaces
            if _looks_garbled(out):
                out = _fix_garbled_spaces(out)
            changed = True
            # Skip all other processing — we have the clean reply
            if out:
                return out, changed

    # If the text has a work-summary marker but no extractable reply,
    # strip everything from "Final response to user:" onward
    if _WORK_SUMMARY_BLOCK_RE.search(out):
        # Take only text before "Final response to user:"
        before = _WORK_SUMMARY_BLOCK_RE.split(out)[0].strip()
        if before:
            out = before
            changed = True
        # Also strip any trailing work-summary debris
        out2 = _WORK_SUMMARY_TAIL_RE.sub("", out).strip()
        if out2 and out2 != out:
            out = out2
            changed = True

    # --- Priority 2: Detect garbled no-space text ---
    # If after the above, the text still looks garbled, try to salvage it.
    if _looks_garbled(out):
        # Try to find any backtick-quoted content as the actual reply
        backtick_matches = re.findall(r"`([^`]+)`", out)
        if backtick_matches:
            # Use the first backtick-quoted segment as the reply
            candidate = backtick_matches[0].strip()
            if _looks_garbled(candidate):
                candidate = _fix_garbled_spaces(candidate)
            out = candidate
            changed = True
        else:
            # Last resort: apply space insertion heuristics
            out = _fix_garbled_spaces(out)
            changed = True

    out2 = _REASONING_BLOCK_TAG_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    out2 = _REASONING_BLOCK_FENCE_RE.sub("", out)
    if out2 != out:
        out = out2
        changed = True

    # Strip candidate-selection reasoning blocks (e.g. "Selected candidate: 3
    # Rationale (tone + safety): ... Final selected reply: "...")
    # First, try to extract the quoted final reply from the reasoning block.
    _final_reply_match = _EXTRACT_FINAL_REPLY_RE.search(out)
    if _final_reply_match:
        # Use the captured quoted reply text (group 1, 2, or 3 depending on quote style)
        extracted = _final_reply_match.group(1) or _final_reply_match.group(2) or _final_reply_match.group(3) or ""
        if extracted.strip():
            out = extracted.strip()
            changed = True
    else:
        # No quoted reply found — strip the entire block
        out2 = _CANDIDATE_SELECTION_BLOCK_RE.sub("", out)
        if out2 != out:
            out = out2
            changed = True
        out2 = _CANDIDATE_SELECTION_NOSPACE_RE.sub("", out)
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
        if code_sensitive:
            out = out.strip("\n")
            out = _ensure_first_code_line_indented(out)
        else:
            out = re.sub(r"[ \t]{2,}", " ", out)
            out = re.sub(r"\s+([.,!?])", r"\1", out)
            out = out.strip()

    if out:
        return out, changed
    if changed:
        # Avoid synthetic fallback text if sanitization over-trims.
        return src, False
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
    code_sensitive = _is_code_sensitive_output(prompt_text, src)
    if code_sensitive:
        # In code-output mode, pseudo-call regexes can strip legitimate code lines
        # like print(...). Preserve output exactly.
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
        if code_sensitive:
            out = out.strip("\n")
            out = _ensure_first_code_line_indented(out)
        else:
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
    if _is_code_sensitive_output(prompt, src):
        # Keep code output intact; sentence-based trimming can invalidate syntax.
        return src, False

    prompt_l = prompt.lower()
    asks_one_sentence = bool(re.search(r"\b(one|single)\s+sentence\b", prompt_l))
    asks_one_thing_short_window = bool(
        re.search(r"\bone thing\b", prompt_l) and re.search(r"\bnext\b.*\bminute", prompt_l)
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
    if re.search(
        r"\b(where should i look first|what should i do first|what should i look at first|first step|first thing)\b",
        prompt_l,
    ):
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
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"[ \t]+([.,!?])", r"\1", out)
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


_SIMPLIFIED_REVIEW_HINT_TEXT = (
    "- Keep review feedback plain-language and concise.\n"
    "- Prefer a simple good/bad summary with concrete next action.\n"
    "- Avoid deep technical jargon unless the user explicitly asks for it."
)


def simplified_review_default_hint(
    review_depth: str,
    *,
    non_coder_profile: bool = False,
) -> str:
    normalized = str(review_depth or "").strip().lower().replace("-", "_")
    if normalized in {"simple", "simplified", "plain", "non_technical"}:
        return format_input_continuity_hint(_SIMPLIFIED_REVIEW_HINT_TEXT).strip()
    if normalized in {"technical", "detailed", "deep"}:
        return ""
    if bool(non_coder_profile):
        return format_input_continuity_hint(_SIMPLIFIED_REVIEW_HINT_TEXT).strip()
    return ""


_BEST_PRACTICE_HINT_TEXT = (
    "- User likely wants non-technical, robust best-practice guidance by default.\n"
    "- Lead with one strongest recommended approach, not multiple equivalent options.\n"
    "- Prefer production-safe defaults, clear tradeoffs, and concrete execution steps.\n"
    "- Do not ship workaround-only outcomes when a direct fix is achievable.\n"
    "- If an issue appears during execution, own it and fix it before finalizing.\n"
    "- If code is required, provide copy-paste-ready snippets with minimal setup.\n"
    "- Ask follow-up questions only when required inputs are missing."
)


def prompt_requests_best_practice_gate(prompt_text: str) -> bool:
    src = str(prompt_text or "").strip().lower()
    if not src:
        return False

    asks_quality = bool(
        re.search(
            r"\b(best[- ]?practice|robust|production[- ]?ready|battle[- ]?tested|gold[- ]?standard)\b",
            src,
        )
    )
    mentions_method = bool(re.search(r"\b(method|approach|workflow|playbook|mehtod)\b", src))
    non_technical_signal = bool(
        re.search(
            r"\b("
            r"idk how to code|"
            r"i\s*(?:do\s*not|don't|dont)\s*know how to code|"
            r"i(?:'m| am)?\s*not\s*(?:a\s*)?(?:coder|developer|programmer)|"
            r"non[- ]?technical|"
            r"no coding experience|"
            r"beginner"
            r")\b",
            src,
        )
    )
    always_default_signal = bool(re.search(r"\b(always|every time|default to)\b", src))
    gate_signal = bool(re.search(r"\b(gate|guardrail|policy|rule)\b", src))

    if asks_quality and (non_technical_signal or always_default_signal):
        return True
    if non_technical_signal and mentions_method:
        return True
    if asks_quality and gate_signal:
        return True
    return False


def best_practice_default_hint() -> str:
    return format_input_continuity_hint(_BEST_PRACTICE_HINT_TEXT).strip()


def best_practice_gate_hint(prompt_text: str) -> str:
    if not prompt_requests_best_practice_gate(prompt_text):
        return ""
    return best_practice_default_hint()
