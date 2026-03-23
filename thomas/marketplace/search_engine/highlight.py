"""Highlighting implementation for search results."""

from ._types import FieldType
from .index import InvertedIndex


class HighlightFragment:
    """A highlighted text fragment."""

    def __init__(self, text: str, score: float = 0.0) -> None:
        """Initialize fragment."""
        self.text = text
        self.score = score


class Highlighter:
    """Highlights matched terms in text."""

    def __init__(
        self, pre_tag: str = "<em>", post_tag: str = "</em>", fragment_size: int = 150, num_fragments: int = 3
    ) -> None:
        """Initialize highlighter."""
        self.pre_tag = pre_tag
        self.post_tag = post_tag
        self.fragment_size = fragment_size
        self.num_fragments = num_fragments

    def highlight(self, text: str, terms: set[str]) -> list[str]:
        """Highlight terms in text."""
        if not terms or not text:
            return []

        fragments = self._extract_fragments(text, terms)
        if not fragments:
            return [text]

        # Sort by score and return top fragments
        sorted_fragments = sorted(fragments, key=lambda f: f.score, reverse=True)
        return [f.text for f in sorted_fragments[: self.num_fragments]]

    def _extract_fragments(self, text: str, terms: set[str]) -> list[HighlightFragment]:
        """Extract fragments containing terms."""
        fragments: list[HighlightFragment] = []
        text_lower = text.lower()

        # Find all match positions
        matches: list[tuple] = []
        for term in terms:
            pos = 0
            while True:
                idx = text_lower.find(term.lower(), pos)
                if idx == -1:
                    break
                matches.append((idx, idx + len(term)))
                pos = idx + 1

        if not matches:
            return []

        # Sort matches
        matches.sort(key=lambda x: x[0])

        # Extract fragments around matches
        seen_positions = set()
        for match_start, match_end in matches:
            # Calculate fragment boundaries
            frag_start = max(0, match_start - self.fragment_size // 2)
            frag_end = min(len(text), match_end + self.fragment_size // 2)

            if frag_start in seen_positions:
                continue

            seen_positions.add(frag_start)

            # Extract and highlight fragment
            fragment = text[frag_start:frag_end]
            highlighted = self._highlight_fragment(fragment, match_start - frag_start, match_end - frag_start, terms)

            # Score fragment
            term_count = sum(1 for _ in self._find_term_positions(fragment, terms))
            score = float(term_count)

            fragments.append(HighlightFragment(highlighted, score))

        return fragments

    def _highlight_fragment(self, fragment: str, match_start: int, match_end: int, terms: set[str]) -> str:
        """Highlight terms in fragment."""
        # Find and highlight all terms
        result = fragment
        offset = 0

        for term in terms:
            pos = 0
            while True:
                idx = result.lower().find(term.lower(), pos)
                if idx == -1:
                    break

                # Adjust for offset
                actual_idx = idx + offset
                result = (
                    result[:actual_idx]
                    + self.pre_tag
                    + result[actual_idx : actual_idx + len(term)]
                    + self.post_tag
                    + result[actual_idx + len(term) :]
                )

                offset += len(self.pre_tag) + len(self.post_tag)
                pos = idx + len(term)

        return result

    def _find_term_positions(self, text: str, terms: set[str]) -> list[tuple]:
        """Find all term positions in text."""
        positions: list[tuple] = []
        text_lower = text.lower()

        for term in terms:
            pos = 0
            while True:
                idx = text_lower.find(term.lower(), pos)
                if idx == -1:
                    break
                positions.append((idx, idx + len(term)))
                pos = idx + 1

        return positions


class UnifiedHighlighter:
    """Unified highlighting across different field types."""

    def __init__(self, pre_tag: str = "<em>", post_tag: str = "</em>") -> None:
        """Initialize unified highlighter."""
        self.pre_tag = pre_tag
        self.post_tag = post_tag

    def highlight_field(self, field_type: FieldType, text: str, terms: set[str]) -> list[str] | None:
        """Highlight based on field type."""
        if field_type == FieldType.TEXT:
            highlighter = Highlighter(self.pre_tag, self.post_tag)
            return highlighter.highlight(text, terms)
        elif field_type == FieldType.KEYWORD:
            # For keywords, only highlight if exact match
            text_lower = text.lower()
            for term in terms:
                if text_lower == term.lower():
                    return [self.pre_tag + text + self.post_tag]
            return [text]
        else:
            # No highlighting for numeric, date, boolean
            return None

    def highlight_document(self, index: InvertedIndex, doc_id: int, terms: set[str]) -> dict[str, list[str]]:
        """Highlight all fields in document."""
        doc = index.document_store.get_document(doc_id)
        if not doc:
            return {}

        highlights = {}
        for field_name, field_mapping in index.config.field_mappings.items():
            if field_name not in doc:
                continue

            value = doc[field_name]
            field_type = field_mapping.type

            highlighted = self.highlight_field(field_type, str(value), terms)
            if highlighted:
                highlights[field_name] = highlighted

        return highlights
