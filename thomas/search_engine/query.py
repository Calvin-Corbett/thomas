"""Query types and parsing for the search engine."""

import re
from abc import ABC, abstractmethod
from typing import Any

from .index import InvertedIndex


class Query(ABC):
    """Base query type."""

    @abstractmethod
    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Execute query and return doc_id, score pairs."""
        pass

    @abstractmethod
    def get_terms(self) -> set[str]:
        """Get all terms in this query."""
        pass


class TermQuery(Query):
    """Single term query."""

    def __init__(self, field: str, term: str, boost: float = 1.0) -> None:
        """Initialize term query."""
        self.field = field
        self.term = term.lower()
        self.boost = boost

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Find documents containing term."""
        postings = index.get_field_postings(self.field, self.term)
        return [(p.doc_id, float(p.term_frequency) * self.boost) for p in postings]

    def get_terms(self) -> set[str]:
        """Return term."""
        return {self.term}


class PhraseQuery(Query):
    """Multi-term phrase query with slop."""

    def __init__(self, field: str, terms: list[str], slop: int = 0, boost: float = 1.0) -> None:
        """Initialize phrase query."""
        self.field = field
        self.terms = [t.lower() for t in terms]
        self.slop = slop
        self.boost = boost

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Find documents containing phrase."""
        if not self.terms:
            return []

        # Get postings for all terms
        all_postings = []
        for term in self.terms:
            postings = index.get_field_postings(self.field, term)
            if not postings:
                return []
            all_postings.append(postings)

        # Find documents containing all terms
        docs_with_all = set(p.doc_id for p in all_postings[0])
        for postings in all_postings[1:]:
            docs_with_all &= set(p.doc_id for p in postings)

        results = []
        for doc_id in docs_with_all:
            # Get positions for each term in this doc
            positions_by_term = []
            for postings in all_postings:
                doc_posting = next((p for p in postings if p.doc_id == doc_id), None)
                if doc_posting:
                    positions_by_term.append(doc_posting.positions)

            # Check for phrase match within slop
            if self._match_phrase(positions_by_term):
                freq = min(len(pos) for pos in positions_by_term)
                results.append((doc_id, float(freq) * self.boost))

        return results

    def _match_phrase(self, positions_by_term: list[list[int]]) -> bool:
        """Check if terms form phrase within slop."""
        if not positions_by_term:
            return False

        # Check all combinations of positions
        def check_positions(indices: list[int]) -> bool:
            if len(indices) < 2:
                return True
            for i in range(len(indices) - 1):
                pos_diff = positions_by_term[i + 1][indices[i + 1]] - positions_by_term[i][indices[i]]
                if pos_diff < 1 or pos_diff > 1 + self.slop:
                    return False
            return True

        # Generate all combinations
        def generate_combinations(term_idx: int, current: list[int]) -> bool:
            if term_idx == len(positions_by_term):
                return check_positions(current)

            for pos_idx in range(len(positions_by_term[term_idx])):
                if generate_combinations(term_idx + 1, current + [pos_idx]):
                    return True
            return False

        return generate_combinations(0, [])

    def get_terms(self) -> set[str]:
        """Return all terms."""
        return set(self.terms)


class BooleanQuery(Query):
    """Boolean combination of queries."""

    def __init__(self) -> None:
        """Initialize boolean query."""
        self.must_queries: list[Query] = []
        self.should_queries: list[Query] = []
        self.must_not_queries: list[Query] = []

    def add_must(self, query: Query) -> "BooleanQuery":
        """Add required query."""
        self.must_queries.append(query)
        return self

    def add_should(self, query: Query) -> "BooleanQuery":
        """Add optional query."""
        self.should_queries.append(query)
        return self

    def add_must_not(self, query: Query) -> "BooleanQuery":
        """Add prohibited query."""
        self.must_not_queries.append(query)
        return self

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Execute boolean combination."""
        # Get must results
        if self.must_queries:
            must_results = self.must_queries[0].execute(index)
            must_docs = set(doc_id for doc_id, _ in must_results)

            for query in self.must_queries[1:]:
                results = query.execute(index)
                must_docs &= set(doc_id for doc_id, _ in results)

            if not must_docs:
                return []
        else:
            must_docs = None

        # Get should results
        should_scores: dict[int, float] = {}
        if self.should_queries:
            for query in self.should_queries:
                results = query.execute(index)
                for doc_id, score in results:
                    should_scores[doc_id] = should_scores.get(doc_id, 0) + score

        # Get must_not results
        must_not_docs = set()
        for query in self.must_not_queries:
            results = query.execute(index)
            must_not_docs.update(doc_id for doc_id, _ in results)

        # Combine results
        result_docs = must_docs if must_docs is not None else set(should_scores.keys())
        result_docs -= must_not_docs

        results = []
        for doc_id in result_docs:
            score = should_scores.get(doc_id, 1.0)
            results.append((doc_id, score))

        return sorted(results, key=lambda x: x[1], reverse=True)

    def get_terms(self) -> set[str]:
        """Get all terms."""
        terms = set()
        for query in self.must_queries + self.should_queries + self.must_not_queries:
            terms.update(query.get_terms())
        return terms


class WildcardQuery(Query):
    """Wildcard pattern matching (?, *)."""

    def __init__(self, field: str, pattern: str, boost: float = 1.0) -> None:
        """Initialize wildcard query."""
        self.field = field
        self.pattern = pattern.lower()
        self.boost = boost
        self._regex = self._pattern_to_regex(self.pattern)

    def _pattern_to_regex(self, pattern: str) -> str:
        """Convert wildcard pattern to regex."""
        regex = ""
        for char in pattern:
            if char == "*":
                regex += ".*"
            elif char == "?":
                regex += "."
            else:
                regex += re.escape(char)
        return f"^{regex}$"

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Find matching documents."""
        regex = re.compile(self._regex)
        all_terms = index.get_terms(self.field)
        matching_terms = [term for term in all_terms if regex.match(term)]

        results_dict: dict[int, float] = {}
        for term in matching_terms:
            postings = index.get_field_postings(self.field, term)
            for posting in postings:
                results_dict[posting.doc_id] = results_dict.get(posting.doc_id, 0) + posting.term_frequency

        return [(doc_id, score * self.boost) for doc_id, score in results_dict.items()]

    def get_terms(self) -> set[str]:
        """Return pattern."""
        return {self.pattern}


class FuzzyQuery(Query):
    """Fuzzy matching with edit distance."""

    def __init__(self, field: str, term: str, max_edits: int = 2, boost: float = 1.0) -> None:
        """Initialize fuzzy query."""
        self.field = field
        self.term = term.lower()
        self.max_edits = max_edits
        self.boost = boost

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Find fuzzy-matching documents."""
        all_terms = index.get_terms(self.field)
        matching_terms = [term for term in all_terms if self._levenshtein_distance(self.term, term) <= self.max_edits]

        results_dict: dict[int, float] = {}
        for term in matching_terms:
            postings = index.get_field_postings(self.field, term)
            for posting in postings:
                # Weight by inverse of distance
                distance = self._levenshtein_distance(self.term, term)
                weight = 1.0 / (1.0 + distance)
                results_dict[posting.doc_id] = results_dict.get(posting.doc_id, 0) + posting.term_frequency * weight

        return [(doc_id, score * self.boost) for doc_id, score in results_dict.items()]

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein distance between strings."""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def get_terms(self) -> set[str]:
        """Return term."""
        return {self.term}


class RangeQuery(Query):
    """Numeric or date range query."""

    def __init__(
        self, field: str, min_value: Any = None, max_value: Any = None, inclusive: bool = True, boost: float = 1.0
    ) -> None:
        """Initialize range query."""
        self.field = field
        self.min_value = min_value
        self.max_value = max_value
        self.inclusive = inclusive
        self.boost = boost

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Find documents in range."""
        results = []
        # This would require numeric indexing support
        # Simplified implementation
        return results

    def get_terms(self) -> set[str]:
        """Return range bounds."""
        return set()


class PrefixQuery(Query):
    """Prefix matching query."""

    def __init__(self, field: str, prefix: str, boost: float = 1.0) -> None:
        """Initialize prefix query."""
        self.field = field
        self.prefix = prefix.lower()
        self.boost = boost

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Find documents with prefix."""
        all_terms = index.get_terms(self.field)
        matching_terms = [term for term in all_terms if term.startswith(self.prefix)]

        results_dict: dict[int, float] = {}
        for term in matching_terms:
            postings = index.get_field_postings(self.field, term)
            for posting in postings:
                results_dict[posting.doc_id] = results_dict.get(posting.doc_id, 0) + posting.term_frequency

        return [(doc_id, score * self.boost) for doc_id, score in results_dict.items()]

    def get_terms(self) -> set[str]:
        """Return prefix."""
        return {self.prefix}


class MatchAllQuery(Query):
    """Match all documents."""

    def __init__(self, boost: float = 1.0) -> None:
        """Initialize match all query."""
        self.boost = boost

    def execute(self, index: InvertedIndex) -> list[tuple[int, float]]:
        """Return all documents."""
        doc_count = index.count_docs()
        return [(i, 1.0 * self.boost) for i in range(doc_count)]

    def get_terms(self) -> set[str]:
        """Return empty set."""
        return set()


class QueryParser:
    """Parse query strings into Query objects."""

    def __init__(self, default_field: str = "body") -> None:
        """Initialize parser."""
        self.default_field = default_field

    def parse(self, query_string: str) -> Query:
        """Parse query string."""
        if not query_string.strip():
            return MatchAllQuery()

        boolean_query = BooleanQuery()
        current_mode = "should"  # Default to optional
        tokens = self._tokenize(query_string)

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token == "+":
                current_mode = "must"
                i += 1
                continue
            elif token == "-":
                current_mode = "must_not"
                i += 1
                continue

            # Parse field:term syntax
            if ":" in token and not token.startswith('"'):
                field, term = token.split(":", 1)
                query = TermQuery(field, term)
            elif token.startswith('"'):
                # Phrase query
                phrase_terms = []
                token = token[1:]
                while i < len(tokens) and not tokens[i].endswith('"'):
                    phrase_terms.append(tokens[i])
                    i += 1
                if i < len(tokens):
                    phrase_terms.append(tokens[i].rstrip('"'))
                query = PhraseQuery(self.default_field, phrase_terms)
            else:
                # Simple term
                query = TermQuery(self.default_field, token)

            if current_mode == "must":
                boolean_query.add_must(query)
            elif current_mode == "should":
                boolean_query.add_should(query)
            else:
                boolean_query.add_must_not(query)

            current_mode = "should"
            i += 1

        return boolean_query

    def _tokenize(self, query_string: str) -> list[str]:
        """Tokenize query string."""
        tokens = []
        current = ""
        in_phrase = False

        for char in query_string:
            if char == '"':
                in_phrase = not in_phrase
                current += char
            elif char in ("+", "-") and not in_phrase and not current:
                tokens.append(char)
            elif char == " " and not in_phrase:
                if current:
                    tokens.append(current)
                    current = ""
            else:
                current += char

        if current:
            tokens.append(current)

        return tokens
