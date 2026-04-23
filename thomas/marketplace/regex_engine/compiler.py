"""
High-level regex compiler.

Orchestrates parsing, optimization, NFA/DFA construction, and matching.
Provides compiled regex object with match/search/findall/sub/split API.
Includes LRU compile cache.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import lru_cache

from ._exceptions import CompileError, ParseError
from ._types import CompileConfig, MatchResult, RegexFlags
from .backtracking import BacktrackingMatcher
from .dfa import construct_dfa, minimize_dfa
from .matcher import NFAMatcher
from .nfa import build_nfa
from .optimizer import optimize
from .parser import parse


class CompiledRegex:
    """Compiled regex object."""

    def __init__(self, pattern: str, config: CompileConfig, ast=None, nfa=None, dfa=None) -> None:
        """Initialize compiled regex."""
        self.pattern = pattern
        self.config = config
        self.ast = ast
        self.nfa = nfa
        self.dfa = dfa
        self.matcher: NFAMatcher | None = None
        self.backtracking_matcher: BacktrackingMatcher | None = None

        if nfa:
            self.matcher = NFAMatcher(nfa)
        if ast:
            self.backtracking_matcher = BacktrackingMatcher(ast)

    def match(self, text: str, pos: int = 0) -> MatchResult | None:
        """
        Match at specific position.

        Args:
            text: String to match
            pos: Starting position (default 0)

        Returns:
            MatchResult if match, None otherwise
        """
        if self.matcher:
            return self.matcher.match(text, pos)
        elif self.backtracking_matcher:
            matched, end_pos, groups = self.backtracking_matcher.match(text, pos)
            if matched:
                return MatchResult(matched=True, groups=(), start=pos, end=end_pos)
            return None
        return None

    def search(self, text: str) -> MatchResult | None:
        """
        Search for first match.

        Args:
            text: String to search

        Returns:
            MatchResult if found, None otherwise
        """
        if self.matcher:
            return self.matcher.search(text)
        elif self.backtracking_matcher:
            matched, start_pos, end_pos, groups = self.backtracking_matcher.search(text)
            if matched:
                return MatchResult(
                    matched=True,
                    groups=(),
                    start=start_pos,
                    end=end_pos,
                )
            return None
        return None

    def findall(self, text: str) -> list[str]:
        """
        Find all matches.

        Args:
            text: String to search

        Returns:
            List of matched strings
        """
        if self.matcher:
            return self.matcher.findall(text)
        elif self.backtracking_matcher:
            matches = []
            result = self.search(text)
            while result and result.matched:
                match_text = text[result.start : result.end]
                matches.append(match_text)
                # Continue search from end of match
                remaining = text[result.end :]
                if not remaining:
                    break
                next_result = self.search(remaining)
                if next_result:
                    # Adjust positions
                    result = MatchResult(
                        matched=True,
                        groups=next_result.groups,
                        start=result.end + next_result.start,
                        end=result.end + next_result.end,
                    )
                else:
                    break
            return matches
        return []

    def finditer(self, text: str) -> Iterator[MatchResult]:
        """
        Find all matches as iterator.

        Args:
            text: String to search

        Yields:
            MatchResult for each match
        """
        if self.matcher:
            return self.matcher.finditer(text)
        else:
            # Fallback implementation
            matches = self.findall(text)
            for match_text in matches:
                yield MatchResult(matched=True, groups=(match_text,), start=0, end=len(match_text))

    def sub(
        self,
        replacement: str | Callable,
        text: str,
        count: int = 0,
    ) -> str:
        """
        Substitute pattern matches.

        Args:
            replacement: Replacement string or callable
            text: Text to process
            count: Maximum replacements (0 = all)

        Returns:
            Text with replacements
        """
        if isinstance(replacement, str):
            # Simple string replacement
            result = text
            pos = 0
            replacements_made = 0

            while pos <= len(text):
                match = self.search(text[pos:])
                if not match or not match.matched:
                    break

                if count > 0 and replacements_made >= count:
                    break

                match_text = text[pos + match.start : pos + match.end]
                result = result[: pos + match.start] + replacement + result[pos + match.end :]
                pos += match.end if match.end > 0 else 1
                replacements_made += 1

            return result

        elif callable(replacement):
            # Callable replacement
            result = text
            pos = 0
            replacements_made = 0

            while pos <= len(text):
                match = self.search(text[pos:])
                if not match or not match.matched:
                    break

                if count > 0 and replacements_made >= count:
                    break

                repl_text = replacement(match)
                result = result[: pos + match.start] + repl_text + result[pos + match.end :]
                pos += match.end if match.end > 0 else 1
                replacements_made += 1

            return result

        return text

    def split(self, text: str, maxsplit: int = 0) -> list[str]:
        """
        Split text by pattern matches.

        Args:
            text: Text to split
            maxsplit: Maximum splits (0 = unlimited)

        Returns:
            List of split strings
        """
        result = []
        last_end = 0
        split_count = 0

        for match in self.finditer(text):
            if maxsplit > 0 and split_count >= maxsplit:
                break

            result.append(text[last_end : match.start])
            last_end = match.end
            split_count += 1

        # Add remaining text
        result.append(text[last_end:])

        return result


class RegexCompiler:
    """Compiles regex patterns."""

    def __init__(self, cache_size: int = 128) -> None:
        """Initialize compiler."""
        self.cache_size = cache_size

    @lru_cache(maxsize=128)
    def compile(self, pattern: str, flags: int = 0) -> CompiledRegex:
        """
        Compile regex pattern.

        Args:
            pattern: Regex pattern string
            flags: RegexFlags bitmask

        Returns:
            CompiledRegex object

        Raises:
            ParseError: If pattern is invalid
            CompileError: If compilation fails
        """
        try:
            # Parse pattern
            ast = parse(pattern)

            # Optimize AST
            ast = optimize(ast)

            # Build NFA
            nfa = build_nfa(ast)

            # Build and minimize DFA
            dfa = construct_dfa(nfa)
            dfa = minimize_dfa(dfa)

            # Create config
            config = CompileConfig(flags=RegexFlags(flags))

            return CompiledRegex(pattern, config, ast=ast, nfa=nfa, dfa=dfa)

        except ParseError:
            raise
        except Exception as e:
            raise CompileError(f"Failed to compile pattern: {e}") from e


# Global compiler instance
_compiler = RegexCompiler()


def compile(pattern: str, flags: int = 0) -> CompiledRegex:
    """
    Compile a regex pattern.

    Args:
        pattern: Regex pattern string
        flags: RegexFlags bitmask (default 0)

    Returns:
        CompiledRegex object

    Example:
        >>> regex = compile(r"[a-z]+")
        >>> regex.match("hello")
    """
    return _compiler.compile(pattern, flags)
