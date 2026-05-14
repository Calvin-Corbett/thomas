"""Suggestion and autocomplete features."""

from collections import Counter

from .index import InvertedIndex


class TrieNode:
    """Node in a prefix trie."""

    def __init__(self) -> None:
        """Initialize trie node."""
        self.children: dict[str, TrieNode] = {}
        self.is_terminal = False
        self.frequency = 0


class PrefixTrie:
    """Trie data structure for prefix lookups."""

    def __init__(self) -> None:
        """Initialize trie."""
        self.root = TrieNode()

    def insert(self, term: str, frequency: int = 1) -> None:
        """Insert term into trie."""
        node = self.root
        for char in term:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_terminal = True
        node.frequency = frequency

    def search_prefix(self, prefix: str) -> list[tuple[str, int]]:
        """Find all terms with given prefix."""
        node = self.root
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]

        results: list[tuple[str, int]] = []
        self._collect_completions(node, prefix, results)
        return sorted(results, key=lambda x: x[1], reverse=True)

    def _collect_completions(self, node: TrieNode, prefix: str, results: list[tuple[str, int]]) -> None:
        """Recursively collect completions."""
        if node.is_terminal:
            results.append((prefix, node.frequency))

        for char, child in node.children.items():
            self._collect_completions(child, prefix + char, results)


class CompletionSuggester:
    """Prefix-based autocomplete suggestions."""

    def __init__(self, field: str = "body") -> None:
        """Initialize suggester."""
        self.field = field
        self.trie = PrefixTrie()

    def build(self, index: InvertedIndex) -> None:
        """Build trie from index terms."""
        all_terms = index.get_terms(self.field)
        for term in all_terms:
            postings = index.get_field_postings(self.field, term)
            frequency = sum(p.term_frequency for p in postings)
            self.trie.insert(term, frequency)

    def suggest(self, prefix: str, limit: int = 10) -> list[str]:
        """Get completion suggestions."""
        results = self.trie.search_prefix(prefix.lower())
        return [term for term, _ in results[:limit]]


class FuzzySuggester:
    """Fuzzy suggestions with edit distance."""

    def __init__(self, field: str = "body", max_edits: int = 2) -> None:
        """Initialize fuzzy suggester."""
        self.field = field
        self.max_edits = max_edits
        self.terms: set[str] = set()

    def build(self, index: InvertedIndex) -> None:
        """Build term dictionary."""
        self.terms = index.get_terms(self.field)

    def suggest(self, term: str, limit: int = 10) -> list[str]:
        """Get fuzzy suggestions."""
        candidates: list[tuple[str, int]] = []

        for indexed_term in self.terms:
            distance = self._levenshtein_distance(term.lower(), indexed_term)
            if distance <= self.max_edits:
                candidates.append((indexed_term, distance))

        # Sort by distance, then alphabetically
        candidates.sort(key=lambda x: (x[1], x[0]))
        return [term for term, _ in candidates[:limit]]

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein distance."""
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


class DidYouMeanSuggester:
    """Did-you-mean suggestions based on term frequency."""

    def __init__(self, field: str = "body") -> None:
        """Initialize suggester."""
        self.field = field
        self.term_frequencies: dict[str, int] = {}

    def build(self, index: InvertedIndex) -> None:
        """Build term frequency map."""
        all_terms = index.get_terms(self.field)
        for term in all_terms:
            freq = index.get_term_frequency(term)
            self.term_frequencies[term] = freq

    def suggest(self, term: str, limit: int = 5) -> list[str]:
        """Get suggestions for potentially misspelled term."""
        term_lower = term.lower()

        # If term exists with good frequency, no suggestion needed
        if term_lower in self.term_frequencies and self.term_frequencies[term_lower] > 1:
            return []

        # Find similar terms with higher frequency
        candidates: list[tuple[str, int, int]] = []

        for indexed_term, freq in self.term_frequencies.items():
            if indexed_term == term_lower:
                continue

            distance = self._damerau_levenshtein(term_lower, indexed_term)
            if distance <= 2:  # Within edit distance of 2
                candidates.append((indexed_term, distance, freq))

        # Sort by frequency first, then distance
        candidates.sort(key=lambda x: (-x[2], x[1]))
        return [term for term, _, _ in candidates[:limit]]

    def _damerau_levenshtein(self, s1: str, s2: str) -> int:
        """Calculate Damerau-Levenshtein distance (allows transposition)."""
        len1, len2 = len(s1), len(s2)
        len1 + len2 + 1

        # Create dictionary for character occurrences
        da: dict[str, int] = {}
        for char in s1 + s2:
            if char not in da:
                da[char] = 0

        # Create distance matrix with padding
        max_dist = len1 + len2
        H: dict[tuple[int, int], int] = {(-1, -1): max_dist}

        for i in range(0, len1 + 1):
            H[(i, -1)] = max_dist
            H[(i, 0)] = i
        for j in range(0, len2 + 1):
            H[(-1, j)] = max_dist
            H[(0, j)] = j

        for i in range(1, len1 + 1):
            DB = 0
            for j in range(1, len2 + 1):
                k = da.get(s2[j - 1], 0)
                l = DB
                cost = 1
                if s1[i - 1] == s2[j - 1]:
                    cost = 0
                    DB = j

                H[(i, j)] = min(
                    H[(i - 1, j)] + 1,  # deletion
                    H[(i, j - 1)] + 1,  # insertion
                    H[(i - 1, j - 1)] + cost,  # substitution
                    H[(k - 1, l - 1)] + (i - k - 1) + 1 + (j - l - 1),  # transposition
                )

            da[s1[i - 1]] = i

        return H[(len1, len2)]


class PhraseSuggester:
    """Suggests phrase completions."""

    def __init__(self, field: str = "body") -> None:
        """Initialize phrase suggester."""
        self.field = field
        self.bigrams: Counter = Counter()

    def build(self, index: InvertedIndex) -> None:
        """Build bigram frequencies from documents."""
        for doc in index.document_store._documents.values():
            if self.field in doc:
                text = str(doc[self.field]).lower().split()
                for i in range(len(text) - 1):
                    bigram = (text[i], text[i + 1])
                    self.bigrams[bigram] += 1

    def suggest(self, partial_phrase: str, limit: int = 5) -> list[str]:
        """Suggest phrase completions."""
        terms = partial_phrase.lower().split()
        if not terms:
            return []

        last_term = terms[-1]
        suggestions: list[tuple[str, int]] = []

        # Find bigrams starting with last term
        for (term1, term2), count in self.bigrams.items():
            if term1 == last_term:
                full_phrase = partial_phrase + " " + term2
                suggestions.append((full_phrase, count))

        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [phrase for phrase, _ in suggestions[:limit]]


class WeightedSuggester:
    """Combines multiple suggestion strategies with weights."""

    def __init__(self) -> None:
        """Initialize weighted suggester."""
        self.suggesters: dict[str, tuple[float, SuggestionStrategy]] = {}

    def add_suggester(self, name: str, suggester: "SuggestionStrategy", weight: float = 1.0) -> None:
        """Add suggester with weight."""
        self.suggesters[name] = (weight, suggester)

    def suggest(self, query: str, limit: int = 10) -> list[str]:
        """Get weighted suggestions."""
        scored_suggestions: dict[str, float] = {}

        for name, (weight, suggester) in self.suggesters.items():
            suggestions = suggester.suggest(query, limit)
            for i, suggestion in enumerate(suggestions):
                # Score based on rank and weight
                rank_score = (limit - i) / limit
                scored_suggestions[suggestion] = scored_suggestions.get(suggestion, 0) + rank_score * weight

        # Return top suggestions by score
        sorted_suggestions = sorted(scored_suggestions.items(), key=lambda x: x[1], reverse=True)
        return [suggestion for suggestion, _ in sorted_suggestions[:limit]]


class SuggestionStrategy:
    """Base class for suggestion strategies."""

    def suggest(self, query: str, limit: int = 10) -> list[str]:
        """Get suggestions for a query.

        Base implementation uses a trie-based prefix matching approach.
        Subclasses can override for alternative strategies (fuzzy, frequency-based, etc.).

        Args:
            query: Query prefix to find suggestions for
            limit: Maximum number of suggestions to return

        Returns:
            List of suggestion strings sorted by relevance/frequency
        """
        # Default: return empty list (subclasses should override)
        # This allows safe instantiation of the base class
        return []
