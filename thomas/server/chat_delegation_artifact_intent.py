"""Does the artifact have anything to do with what was asked?

Thomas's success check reduces to "a non-empty file exists". That is how a
request for a graph of current trends was closed as verified by a one-button
arcade game, and how the task line "Start a local dev/static server if needed"
was closed as verified by an arcade football game. Once success is inferred from
the existence of a side effect, the wrong artifact is indistinguishable from the
right one, and Thomas can neither retry correctly nor report honestly.

The Canvas path already refuses this: chat_delegation_canvas_review compares the
requested subject against the tokens actually visible in the render and fails
closed. That check has simply never been shared with the path that produces most
deliverables. This module is that check, generalised.

Deliberately a floor, not a rubric. It fires only when an artifact shares
*nothing at all* with a request that was specific enough to share something. A
verifier that rejects good work is not an improvement on one that accepts bad
work -- it just moves the dishonesty. Anything subtler than "these are unrelated"
belongs to a model, not to token overlap.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Text we can inspect. A PDF or PNG is not checkable this way, and guessing
# about one is worse than admitting we cannot check it.
_READABLE_SUFFIXES = {
    ".html", ".htm", ".md", ".markdown", ".txt", ".csv", ".tsv", ".json",
    ".js", ".mjs", ".ts", ".py", ".css", ".xml", ".yaml", ".yml", ".rst", ".svg",
}

_MAX_READ_BYTES = 400_000
_TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")
# Stylesheet and script bodies survive tag-stripping and are pure noise:
# "grid", "block", "filter", "function" would make a chart request look
# satisfied by any page that merely uses CSS grid.
_NOISE_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_FILENAME_RE = re.compile(r"\b([\w.-]+\.[A-Za-z0-9]{1,5})\b")

# Words that carry no subject: they appear in every request and every document,
# so counting them as agreement would make the check pass on anything.
_STOPWORD_TEXT = """
a an and are as at be been but by can could did do does doing done for from get
give go had has have her him his how i if in into is it its just let make made me
my need needs new now of on one only or our out own please put should show so
some take than that the their them then there these they this those to too two up
us use used using want was way we well were what when where which while who why
will with would you your yours about after again all also am any because before
being below between both during each few further here more most no nor not off
once other over same such through under until very via
create creates created build builds built write writes written add adds added
update updates updated change changes changed fix fixes fixed generate generates
generated produce produces produced file files folder page pages thing things
small tiny simple quick basic single nice good great cool please thanks thank
html css javascript js code app application script program version
called named titled name title right now here thing stuff something anything
"""
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())

# A request has to be specific enough to test before we test it. "fix it" or
# "make it nicer" carries no subject at all, and inventing one would be a guess.
_MIN_SUBJECT_TOKENS = 3


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(str(text or "").casefold()) if t not in _STOPWORDS}


def _readable_text(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return ""
        raw = path.read_bytes()[:_MAX_READ_BYTES]
    except OSError:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if path.suffix.casefold() in {".html", ".htm", ".svg", ".xml"}:
        # Markup names (div, span, href) are not subject matter; strip them so
        # every HTML file does not look vaguely related to every request.
        text = _NOISE_BLOCK_RE.sub(" ", text)
        text = _TAG_RE.sub(" ", text)
    return text


def _delivered_a_named_file(prompt: str, created_files) -> bool:
    """True when the request named a file by name and that file was produced.

    This outranks word overlap. Someone who asks for clicker.html and receives
    clicker.html got exactly what they specified, even if the app inside calls
    itself Teal Tapper -- a synonym is not a wrong deliverable, and rejecting it
    would replace lying about failure with lying about success in the other
    direction.
    """
    asked = {m.group(1).casefold() for m in _FILENAME_RE.finditer(str(prompt or ""))}
    if not asked:
        return False
    made = {Path(str(f or "")).name.casefold() for f in (created_files or [])}
    return bool(asked & made)


def artifact_intent_issues(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str] | tuple[str, ...] | None,
) -> list[str]:
    """Report artifacts that share no subject with the request.

    Returns an empty list whenever the question cannot be answered honestly:
    no request, no artifacts, a request too vague to have a subject, or files we
    cannot read. Silence here means "not checkable", never "checked and fine".
    """
    subject = _tokens(prompt)
    if len(subject) < _MIN_SUBJECT_TOKENS:
        return []
    if work_dir is None or not created_files:
        return []
    if _delivered_a_named_file(prompt, created_files):
        return []

    # One shared word is too easy to hit by accident: a request for a snake game
    # "at the right moment" matches an arcade game that says "right". Require the
    # same agreement the Canvas reviewer asks for, which is proven in use.
    required = min(2, max(1, (len(subject) + 2) // 3))

    checked = 0
    unrelated: list[tuple[str, int]] = []
    try:
        base = work_dir.resolve()
    except (OSError, ValueError):
        return []
    for raw in created_files:
        rel = str(raw or "").strip().replace("\\", "/").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            continue
        path = work_dir / rel
        # Containment is checked after resolving, not inferred from the string.
        # A leading "C:/" survives the ".." test and then WINS the join on
        # Windows, so work_dir / "C:/secret.html" is simply C:\secret.html --
        # this read files outside the workspace and named their full path in a
        # user-visible message. Resolving also settles symlinks and short names.
        try:
            if not path.resolve().is_relative_to(base):
                continue
        except (OSError, ValueError):
            continue
        if path.suffix.casefold() not in _READABLE_SUFFIXES:
            continue
        text = _readable_text(path)
        if not text.strip():
            continue
        checked += 1
        matched = subject & _tokens(text)
        if len(matched) >= required:
            # On topic. Judging how *well* it answers is not a job for word
            # counting, and pretending otherwise is how a rubber stamp starts.
            return []
        unrelated.append((rel, len(matched)))

    if not checked or not unrelated:
        return []
    return [
        f"{name} does not appear to be about what was asked "
        f"(matched {hits} of the requested subject: {', '.join(sorted(subject)[:6])})"
        for name, hits in unrelated
    ]


def intent_evidence(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    """The same check, as recordable evidence rather than a verdict."""
    issues = artifact_intent_issues(prompt, work_dir, created_files)
    subject = sorted(_tokens(prompt))
    return {
        "subject_tokens": subject[:24],
        "checkable": len(subject) >= _MIN_SUBJECT_TOKENS,
        "issues": issues,
        "matches_request": not issues,
    }
