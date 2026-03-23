r"""
Thomas Regex Engine - A complete regex engine implementation from scratch.

This module implements a regex engine with the following components:
- Parser: Tokenizes and parses regex patterns into AST
- NFA: Thompson's construction of NFAs from AST
- DFA: Subset construction and Hopcroft's minimization
- Matcher: Thompson's algorithm for NFA simulation
- Backtracking: Recursive backtracking for advanced features
- Optimizer: AST optimization passes
- Compiler: High-level compilation and caching

Public API:
    compile(pattern, flags=0) -> CompiledRegex
    match(pattern, text) -> Optional[MatchResult]
    search(pattern, text) -> Optional[MatchResult]
    findall(pattern, text) -> List[str]
    finditer(pattern, text) -> Iterator[MatchResult]
    sub(pattern, replacement, text, count=0) -> str
    split(pattern, text, maxsplit=0) -> List[str]

Example:
    >>> import regex_engine
    >>> regex = regex_engine.compile(r"[a-z]+@[a-z]+\.[a-z]+")
    >>> match = regex.search("Contact: test@example.com")
    >>> if match:
    ...     print(f"Found: {match.group}")
"""

from ._exceptions import CompileError, MatchError, ParseError, RegexError
from ._types import (
    Alternation,
    Anchor,
    ASTNode,
    Backreference,
    CharClass,
    CompileConfig,
    Concatenation,
    Dot,
    Group,
    Literal,
    Lookahead,
    Lookbehind,
    MatchResult,
    Quantifier,
    RegexFlags,
)
from .compiler import CompiledRegex, compile
from .matcher import findall, finditer, match, search

__version__ = "1.0.0"
__author__ = "Claude"

__all__ = [
    # Exceptions
    "RegexError",
    "ParseError",
    "CompileError",
    "MatchError",
    # Types
    "RegexFlags",
    "CompileConfig",
    "MatchResult",
    "ASTNode",
    "Literal",
    "Dot",
    "CharClass",
    "Anchor",
    "Quantifier",
    "Alternation",
    "Concatenation",
    "Group",
    "Backreference",
    "Lookahead",
    "Lookbehind",
    # Compiler and matching
    "compile",
    "CompiledRegex",
    "match",
    "search",
    "findall",
    "finditer",
]
