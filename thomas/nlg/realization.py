"""Surface realization: converting syntax trees to text.

Implements surface realization including:
- Linearizing syntax trees to word sequences
- Punctuation insertion rules
- Capitalization rules
- Whitespace normalization
- Paragraph formatting
- Text wrapping
- Orthographic rules
- Markdown formatting
"""

import re

from thomas.nlg._exceptions import RealizationError
from thomas.nlg._types import SyntaxTree


class Realizer:
    """Realizes surface text from syntax trees.

    Converts syntax trees to properly formatted natural language text
    with correct punctuation, capitalization, and formatting.
    """

    def __init__(self) -> None:
        """Initialize realizer."""
        self.capitalize_starts = True
        self.add_punctuation = True
        self.normalize_whitespace = True
        self.wrap_length = 80

    def realize(self, tree: SyntaxTree) -> str:
        """Realize syntax tree as surface text.

        Args:
            tree: Syntax tree

        Returns:
            Realized text

        Raises:
            RealizationError: If realization fails
        """
        if tree is None:
            raise RealizationError("Null syntax tree")

        # Linearize tree
        text = self.linearize(tree)

        # Apply surface processes
        if self.add_punctuation:
            text = self._add_punctuation(text, tree)

        if self.normalize_whitespace:
            text = self._normalize_whitespace(text)

        if self.capitalize_starts:
            text = self._capitalize_sentences(text)

        return text

    def linearize(self, tree: SyntaxTree) -> str:
        """Linearize syntax tree to word sequence.

        Args:
            tree: Syntax tree

        Returns:
            Word sequence

        Raises:
            RealizationError: If linearization fails
        """
        if tree is None:
            raise RealizationError("Null tree for linearization")

        if tree.get_depth() > 100:
            raise RealizationError(f"Tree too deep: {tree.get_depth()}")

        words = tree.get_yield()

        if not words:
            raise RealizationError("Tree has no yield")

        return " ".join(words)

    def _add_punctuation(self, text: str, tree: SyntaxTree) -> str:
        """Add punctuation based on syntax tree.

        Args:
            text: Linearized text
            tree: Syntax tree

        Returns:
            Text with punctuation
        """
        # Check if tree already ends with punctuation
        if tree.label == "S":
            # Add period to sentences
            if not text.endswith((".", "?", "!")):
                text = text + "."

        # Handle questions (check for question word or aux-inversion)
        if self._is_question(tree):
            text = text.rstrip(".")
            if not text.endswith("?"):
                text = text + "?"

        # Handle exclamations
        if self._is_exclamation(tree):
            text = text.rstrip(".")
            if not text.endswith("!"):
                text = text + "!"

        # Add commas for clauses
        text = self._add_clause_commas(text)

        return text

    def _is_question(self, tree: SyntaxTree) -> bool:
        """Check if tree represents a question.

        Args:
            tree: Syntax tree

        Returns:
            True if question
        """
        if tree.features.get("mood") == "interrogative":
            return True

        # Check for question words
        for child in tree.children:
            if child.label in ("WHNP", "WHPP", "WHADVP"):
                return True
            if child.word and child.word.lemma.lower() in (
                "what",
                "who",
                "when",
                "where",
                "why",
                "how",
            ):
                return True

        return False

    def _is_exclamation(self, tree: SyntaxTree) -> bool:
        """Check if tree represents an exclamation.

        Args:
            tree: Syntax tree

        Returns:
            True if exclamation
        """
        return tree.features.get("mood") == "exclamative"

    def _add_clause_commas(self, text: str) -> str:
        """Add commas for clause boundaries.

        Args:
            text: Text to process

        Returns:
            Text with clause commas
        """
        # Simple heuristic: add comma before relative clauses
        text = re.sub(r"\s+(who|which|that)\s+", r", \1 ", text)
        return text

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace in text.

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        # Remove extra spaces
        text = re.sub(r"\s+", " ", text)

        # Fix space before punctuation
        text = re.sub(r"\s+([.,!?;:])", r"\1", text)

        # Fix space after opening quotes
        text = re.sub(r'(["(\'])\s+', r"\1", text)

        # Fix space before closing quotes
        text = re.sub(r'\s+([")\'])', r"\1", text)

        return text.strip()

    def _capitalize_sentences(self, text: str) -> str:
        """Capitalize sentence starts.

        Args:
            text: Text to capitalize

        Returns:
            Capitalized text
        """
        sentences = re.split(r"([.!?])", text)

        capitalized = []
        for i, part in enumerate(sentences):
            if i % 2 == 0:  # Sentence text
                if part.strip():
                    # Capitalize first letter
                    part = part[0].upper() + part[1:] if len(part) > 0 else part
            capitalized.append(part)

        return "".join(capitalized)

    def format_paragraphs(self, texts: list[str]) -> str:
        """Format multiple texts as paragraphs.

        Args:
            texts: Text segments

        Returns:
            Formatted paragraphs

        Raises:
            RealizationError: If formatting fails
        """
        if not texts:
            raise RealizationError("No texts to format")

        return "\n\n".join(texts)

    def wrap_text(self, text: str, length: int = 80) -> str:
        """Wrap text to specified line length.

        Args:
            text: Text to wrap
            length: Maximum line length

        Returns:
            Wrapped text
        """
        if length <= 0:
            raise RealizationError("Invalid wrap length")

        words = text.split()
        lines: list[str] = []
        current_line = ""

        for word in words:
            if len(current_line) + len(word) + 1 <= length:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return "\n".join(lines)

    def apply_orthography(self, text: str) -> str:
        """Apply orthographic rules.

        Args:
            text: Text to process

        Returns:
            Text with orthography applied
        """
        # Numbers under 10 as words
        text = re.sub(r"\b([0-9])\b", self._number_to_word, text)

        # A/an selection
        text = self._apply_article_rules(text)

        # Apostrophes
        text = self._apply_apostrophes(text)

        return text

    def _number_to_word(self, match) -> str:
        """Convert single digit number to word.

        Args:
            match: Regex match

        Returns:
            Word form of number
        """
        words = [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
        ]
        num = int(match.group(1))
        return words[num]

    def _apply_article_rules(self, text: str) -> str:
        """Fix article selection (a/an).

        Args:
            text: Text to process

        Returns:
            Text with correct articles
        """
        # a -> an before vowels
        text = re.sub(r"\ba\s+([aeiouAEIOU])", r"an \1", text)  # an -> a after vowel
        text = re.sub(r"\ban\s+([bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ])", r"a \1", text)

        return text

    def _apply_apostrophes(self, text: str) -> str:
        """Apply apostrophe rules.

        Args:
            text: Text to process

        Returns:
            Text with apostrophes
        """
        # Possessives
        text = re.sub(r"(\w+)\s+s\b", r"\1's", text)

        return text

    def format_with_markdown(self, text: str, bold: bool = False, italic: bool = False, heading_level: int = 0) -> str:
        """Apply markdown formatting.

        Args:
            text: Text to format
            bold: Bold formatting
            italic: Italic formatting
            heading_level: Heading level (0 = no heading)

        Returns:
            Markdown-formatted text
        """
        if heading_level > 0:
            return "#" * heading_level + " " + text

        if bold:
            text = "**" + text + "**"

        if italic:
            text = "*" + text + "*"

        return text

    def format_list(self, items: list[str], list_type: str = "unordered", indent: int = 0) -> str:
        """Format a list.

        Args:
            items: List items
            list_type: "ordered" or "unordered"
            indent: Indentation level

        Returns:
            Formatted list
        """
        prefix = "  " * indent

        if list_type == "ordered":
            lines = [f"{prefix}{i + 1}. {item}" for i, item in enumerate(items)]
        else:
            lines = [f"{prefix}- {item}" for item in items]

        return "\n".join(lines)

    def format_table(self, rows: list[list[str]], headers: list[str] | None = None) -> str:
        """Format a markdown table.

        Args:
            rows: Table rows
            headers: Column headers

        Returns:
            Markdown table
        """
        if not rows:
            return ""

        # Calculate column widths
        col_count = len(rows[0])
        col_widths = [0] * col_count

        all_rows = []
        if headers:
            all_rows.append(headers)
            col_widths = [len(h) for h in headers]

        all_rows.extend(rows)

        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))

        # Build table
        lines = []

        if headers:
            # Header row
            header_cells = [h.ljust(col_widths[i]) for i, h in enumerate(headers)]
            lines.append("| " + " | ".join(header_cells) + " |")

            # Separator
            seps = ["-" * col_widths[i] for i in range(col_count)]
            lines.append("|" + "|".join([s.center(col_widths[i] + 2) for i, s in enumerate(seps)]) + "|")

        # Data rows
        for row in rows:
            cells = [cell.ljust(col_widths[i]) for i, cell in enumerate(row)]
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)
