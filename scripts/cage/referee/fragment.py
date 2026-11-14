"""Class D content rules: what a changelog fragment must be to land without a card.

The first half is a vendored copy of the repository's own fragment grammar (``scripts/forge/changelog_fragments.py``:
the name pattern, the section header, the bullet). The referee may import nothing from the repository, so the rules
are copied here and a drift test fails when the two differ. One difference on purpose: the name is matched with
``fullmatch``, so a name ending in a line break is refused here.

The second half is stricter than the repository: ASCII only, at most 4 KB, no URL, e-mail, HTML or Markdown link,
and wording that does not describe the person who owns the project in the third person or judge their ability.
"""

from __future__ import annotations

import re

SECTIONS = ("Added", "Changed", "Fixed", "Removed", "Security")
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+\.md$")
_SECTION = re.compile(r"^### (Added|Changed|Fixed|Removed|Security)\s*$")
_BULLET = re.compile(r"^- \S")

MAX_BYTES = 4096
_URL = re.compile(r"(?i)[a-z][a-z0-9+.-]*://|\bwww\.|\b(?:mailto|data|javascript|file|ftp):")
_DOMAIN = re.compile(
    r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|ai|app|co|us|uk|de|ru|cn|info|biz|xyz|site|online"
    r"|shop|top|me|tv|ly|gg|to|ch|fr|nl|jp|in|br|au)\b"
)  # a bare host: file names such as ledger.py, notes.md or run.sh and version numbers are not in the list
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+")
_HTML = re.compile(r"<[A-Za-z!/?]|&#?[A-Za-z0-9]+;")
_LINK = re.compile(r"!?\[[^\]]*\]\s*[(\[]|^\s*\[[^\]]+\]:", re.M)
# Wording about the person who owns the project: no third-person reference, no judgement of ability or background.
_WORDING = re.compile(
    r"(?i)\b(?:the (?:project )?owner|the user|calvin)\b"
    r"|\b(?:non[- ]?technical|not (?:a|an) (?:programmer|developer|coder|engineer)|novice|beginner|inexperienced"
    r"|unskilled|amateur)\b"
    r"|\b(?:can(?:'|no)t|cannot|could not|unable to) (?:read|understand|write) (?:the )?code\b"
    r"|\b(?:did(?: not|n't)|does(?: not|n't)|do(?: not|n't)) (?:understand|know how)\b"
)


def parse_fragment(text: str) -> dict[str, list[str]]:
    """Section name -> bullets, each bullet with its continuation lines (a copy of the repository's parser)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        head = _SECTION.match(line)
        if head:
            current = head.group(1)
            sections.setdefault(current, [])
            continue
        if current is None or not line.strip():
            continue
        if _BULLET.match(line):
            sections[current].append(line.rstrip())
        elif sections[current] and line.startswith("  "):
            sections[current][-1] += "\n" + line.rstrip()
    return sections


def grammar_problems(name: str, text: str) -> list[str]:
    """The repository's ``check_fragment`` rules, applied to a name and text instead of a file."""
    problems: list[str] = []
    if not _NAME.fullmatch(name):
        problems.append("name")
    sections = parse_fragment(text)
    if not sections:
        problems.append("no_section")
        if not any(_BULLET.match(line) for line in text.splitlines()):
            problems.append("no_bullet")
    problems += ["empty_section" for bullets in sections.values() if not bullets]
    return problems


def content_problems(name: str, data: bytes) -> list[str]:
    """Short codes for everything wrong with a fragment. An empty list means the referee may land it."""
    problems: list[str] = []
    if len(data) > MAX_BYTES:
        problems.append("too_large")
    if any(b > 0x7E or (b < 0x20 and b != 0x0A) for b in data):
        return problems + ["not_plain_ascii"]  # no point reading further text that is not text
    text = data.decode("ascii")
    problems += grammar_problems(name, text)
    flat = " ".join(text.split())  # line breaks and runs of spaces cannot split a phrase the rules look for
    for code, pattern in (
        ("url", _URL),
        ("url", _DOMAIN),
        ("email", _EMAIL),
        ("html", _HTML),
        ("link", _LINK),
        ("wording", _WORDING),
    ):
        if pattern.search(flat if code == "wording" else text):
            problems.append(code)
    return problems
