"""Name whole long request requirements before a Thomas project starts."""

from __future__ import annotations

from thomas.core.acceptance_contract import requirement_statements

LONG_REQUIREMENT_CHARS = 300


def long_requirements(prompt_text: str) -> list[dict[str, int | str]]:
    """Describe distinct long statements in request order without truncating their length."""
    seen: set[str] = set()
    found: list[dict[str, int | str]] = []
    for statement in requirement_statements(prompt_text):
        if len(statement) <= LONG_REQUIREMENT_CHARS or statement in seen:
            continue
        seen.add(statement)
        found.append({"chars": len(statement), "opening": statement[:100] + "..."})
    return found


def long_requirements_notice(found: list[dict[str, int | str]]) -> str:
    """Explain that the judge treats each named long requirement as one item."""
    if not found:
        return ""
    count = len(found)
    verb = "is" if count == 1 else "are"
    named = "; ".join(f'({item["chars"]:,} characters) "{item["opening"]}"' for item in found)
    return (
        f"Kept whole: {count} of your requirements {verb} longer than {LONG_REQUIREMENT_CHARS} characters: "
        f"{named}. The judge rules on each as one item, so a long one can be split."
    )
