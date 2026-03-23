"""
Regex matching using NFA simulation (Thompson's algorithm).

Implements match, search, findall, finditer operations using parallel NFA state tracking.
Also includes capture group extraction.
"""

from __future__ import annotations

from collections.abc import Iterator

from ._types import MatchResult
from .nfa import NFA, NFAState


class NFAMatcher:
    """Matches strings using NFA simulation."""

    def __init__(self, nfa: NFA) -> None:
        """Initialize matcher with NFA."""
        self.nfa = nfa

    def match(self, text: str, pos: int = 0) -> MatchResult | None:
        """
        Match at specific position.

        Args:
            text: String to match
            pos: Starting position

        Returns:
            MatchResult if match, None otherwise
        """
        result = self._simulate(text, pos, anchored_start=True)
        return result

    def search(self, text: str) -> MatchResult | None:
        """
        Search for first match in text.

        Args:
            text: String to search

        Returns:
            MatchResult if found, None otherwise
        """
        for i in range(len(text)):
            result = self._simulate(text, i, anchored_start=False)
            if result and result.matched:
                return result
        return None

    def findall(self, text: str) -> list[str]:
        """
        Find all matches.

        Args:
            text: String to search

        Returns:
            List of matched strings
        """
        matches = []
        pos = 0

        while pos <= len(text):
            result = self.search(text[pos:])
            if not result or not result.matched:
                break
            match_text = result.group
            if match_text:
                matches.append(match_text)
                pos += result.end if result.end > 0 else 1
            else:
                pos += 1

        return matches

    def finditer(self, text: str) -> Iterator[MatchResult]:
        """
        Find all matches as iterator.

        Args:
            text: String to search

        Yields:
            MatchResult for each match
        """
        pos = 0

        while pos <= len(text):
            result = self.search(text[pos:])
            if not result or not result.matched:
                break
            yield result
            pos += result.end if result.end > 0 else 1

    def _simulate(self, text: str, start_pos: int = 0, anchored_start: bool = False) -> MatchResult | None:
        """
        Simulate NFA matching using Thompson's algorithm.

        Tracks all active states in parallel.
        """
        # Start with epsilon closure of NFA start state
        current_states: set[NFAState] = self._epsilon_closure({self.nfa.start})
        capture_groups: dict[int, str | None] = {}
        start_index = start_pos

        for pos in range(start_pos, len(text) + 1):
            char = text[pos] if pos < len(text) else None

            # Check if NFA end state is in current states (match)
            if self.nfa.end in current_states:
                # Extract capture groups
                groups = self._extract_groups(capture_groups)
                matched_text = text[start_index:pos]
                return MatchResult(
                    matched=True,
                    groups=(matched_text,) + groups,
                    start=start_index,
                    end=pos,
                )

            # If we're at end of text and end state is in current states
            if pos >= len(text) and self.nfa.end in current_states:
                groups = self._extract_groups(capture_groups)
                matched_text = text[start_index:pos]
                return MatchResult(
                    matched=True,
                    groups=(matched_text,) + groups,
                    start=start_index,
                    end=pos,
                )

            # Move on character
            if char is None:
                break

            next_states: set[NFAState] = set()

            for state in current_states:
                # Direct character transition
                if char in state.transitions:
                    for next_state in state.transitions[char]:
                        next_states.add(next_state)

                # Dot transition (matches any char except newline)
                if "." in state.transitions and char != "\n":
                    for next_state in state.transitions["."]:
                        next_states.add(next_state)

            if not next_states:
                # No match found
                return None

            current_states = self._epsilon_closure(next_states)

            # Track capture groups
            for state in current_states:
                if state.group_enter is not None:
                    if state.group_enter not in capture_groups:
                        capture_groups[state.group_enter] = ""
                if state.group_exit is not None:
                    if state.group_exit not in capture_groups:
                        capture_groups[state.group_exit] = ""

        # Check if match at end
        if self.nfa.end in current_states:
            groups = self._extract_groups(capture_groups)
            matched_text = text[start_index : len(text)]
            return MatchResult(
                matched=True,
                groups=(matched_text,) + groups,
                start=start_index,
                end=len(text),
            )

        return None

    def _epsilon_closure(self, states: set[NFAState]) -> set[NFAState]:
        """Compute epsilon closure of state set."""
        closure = set()
        stack = list(states)

        while stack:
            state = stack.pop()
            if state not in closure:
                closure.add(state)
                if None in state.transitions:
                    for next_state in state.transitions[None]:
                        if next_state not in closure:
                            stack.append(next_state)

        return closure

    def _extract_groups(self, capture_groups: dict[int, str | None]) -> tuple:
        """Extract captured groups from capture tracking."""
        if not capture_groups:
            return ()

        max_group = max(capture_groups.keys()) if capture_groups else 0
        groups = []

        for i in range(1, max_group + 1):
            groups.append(capture_groups.get(i))

        return tuple(groups)


def match(nfa: NFA, text: str, pos: int = 0) -> MatchResult | None:
    """Match at specific position in text."""
    matcher = NFAMatcher(nfa)
    return matcher.match(text, pos)


def search(nfa: NFA, text: str) -> MatchResult | None:
    """Search for first match in text."""
    matcher = NFAMatcher(nfa)
    return matcher.search(text)


def findall(nfa: NFA, text: str) -> list[str]:
    """Find all matches in text."""
    matcher = NFAMatcher(nfa)
    return matcher.findall(text)


def finditer(nfa: NFA, text: str) -> Iterator[MatchResult]:
    """Find all matches as iterator."""
    matcher = NFAMatcher(nfa)
    return matcher.finditer(text)
