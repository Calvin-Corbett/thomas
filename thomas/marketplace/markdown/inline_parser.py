"""
Inline Markdown parser.

Parses inline content (emphasis, strong, code, links, images, etc.) within blocks.
Implements CommonMark-compliant emphasis parsing with stack-based delimiter matching.
"""

from __future__ import annotations

from dataclasses import dataclass

from thomas.marketplace.markdown._types import (
    Code,
    Emphasis,
    Footnote,
    HTMLInline,
    Image,
    InlineNode,
    LineBreak,
    Link,
    SoftBreak,
    Strikethrough,
    Strong,
    Text,
)


@dataclass
class Delimiter:
    """Stack entry for emphasis delimiter tracking."""

    char: str  # '*' or '_'
    position: int  # Position in content
    can_open: bool
    can_close: bool
    num: int  # Number of delimiters


class InlineParser:
    """Parser for inline Markdown content."""

    def __init__(self) -> None:
        """Initialize inline parser."""
        self.pos = 0
        self.text = ""
        self.references: dict[str, tuple[str, str | None]] = {}

    def parse(self, text: str, references: dict[str, tuple[str, str | None]] | None = None) -> list[InlineNode]:
        """Parse inline content into AST nodes.

        Args:
            text: Text to parse
            references: Dictionary of link references

        Returns:
            List of inline nodes
        """
        self.text = text
        self.pos = 0
        self.references = references or {}
        return self._parse_inline_content()

    def _parse_inline_content(self) -> list[InlineNode]:
        """Parse inline content recursively."""
        nodes: list[InlineNode] = []

        while self.pos < len(self.text):
            ch = self.text[self.pos]

            # Hard line break (two spaces or backslash)
            if self._match_hard_break():
                nodes.append(LineBreak())
                continue

            # Soft line break
            if ch == "\n":
                # Two trailing spaces before newline indicate hard break.
                if self.pos >= 2 and self.text[self.pos - 2 : self.pos] == "  ":
                    if nodes and isinstance(nodes[-1], Text):
                        nodes[-1].content = nodes[-1].content[:-2]
                        if nodes[-1].content == "":
                            nodes.pop()
                    nodes.append(LineBreak())
                    self.pos += 1
                    continue
                nodes.append(SoftBreak())
                self.pos += 1
                continue

            # Backslash escape
            if ch == "\\" and self.pos + 1 < len(self.text):
                next_ch = self.text[self.pos + 1]
                if next_ch in "\\`*_{}[]()#+-.!|":
                    nodes.append(Text(next_ch))
                    self.pos += 2
                    continue

            # Code span
            if ch == "`":
                code_node = self._parse_code()
                if code_node:
                    nodes.append(code_node)
                    continue

            # Link or image
            if ch == "!" and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == "[":
                image_node = self._parse_image()
                if image_node:
                    nodes.append(image_node)
                    continue

            if ch == "[":
                link_node = self._parse_link()
                if link_node:
                    nodes.append(link_node)
                    continue

            # Autolink
            if ch == "<":
                autolink = self._parse_autolink()
                if autolink:
                    nodes.append(autolink)
                    continue

            # HTML inline
            if ch == "<" and self._is_html_tag():
                html = self._parse_html_inline()
                if html:
                    nodes.append(html)
                    continue

            # Emphasis and strong
            if ch in "*_":
                emph = self._try_emphasis()
                if emph:
                    nodes.append(emph)
                    continue

            # Strikethrough (extension)
            if ch == "~" and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == "~":
                strike = self._try_strikethrough()
                if strike:
                    nodes.append(strike)
                    continue

            # Footnote reference (extension)
            if ch == "[" and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == "^":
                footnote = self._try_footnote()
                if footnote:
                    nodes.append(footnote)
                    continue

            # Entity reference
            if ch == "&":
                entity = self._parse_entity()
                if entity:
                    nodes.append(entity)
                    continue

            # Plain text
            text_node = self._collect_plain_text()
            if text_node:
                nodes.append(text_node)

        # Post-process to handle emphasis
        nodes = self._process_emphasis(nodes)
        return nodes

    def _match_hard_break(self) -> bool:
        """Check for hard line break."""
        if self.pos + 1 >= len(self.text):
            return False

        # Backslash newline
        if self.text[self.pos] == "\\" and self.text[self.pos + 1] == "\n":
            self.pos += 2
            return True

        # Two spaces or tab followed by newline
        if self.text[self.pos] in " \t" and self.text[self.pos + 1] == "\n":
            spaces = 0
            start = self.pos
            while self.pos < len(self.text) and self.text[self.pos] in " \t":
                spaces += 1
                self.pos += 1

            if self.pos < len(self.text) and self.text[self.pos] == "\n":
                if spaces >= 2:
                    self.pos += 1
                    return True
            self.pos = start

        return False

    def _parse_code(self) -> Code | None:
        """Parse inline code span."""
        if self.text[self.pos] != "`":
            return None

        start = self.pos
        num_backticks = 0

        # Count opening backticks
        while self.pos < len(self.text) and self.text[self.pos] == "`":
            num_backticks += 1
            self.pos += 1

        # Find closing backticks
        while self.pos < len(self.text):
            if self.text[self.pos] == "`":
                close_start = self.pos
                close_count = 0
                while self.pos < len(self.text) and self.text[self.pos] == "`":
                    close_count += 1
                    self.pos += 1

                if close_count == num_backticks:
                    content = self.text[start + num_backticks : close_start]
                    # Strip leading/trailing space if surrounded
                    if len(content) > 0 and content[0] == " " and content[-1] == " " and len(content) > 1:
                        content = content[1:-1]
                    return Code(content, num_backticks)
            else:
                self.pos += 1

        # No closing found
        self.pos = start
        return None

    def _parse_link(self) -> Link | None:
        """Parse link [text](url "title") or reference link."""
        if self.text[self.pos] != "[":
            return None

        start = self.pos
        self.pos += 1

        # Parse link text
        text_content = []
        depth = 1
        while self.pos < len(self.text) and depth > 0:
            ch = self.text[self.pos]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "\\" and self.pos + 1 < len(self.text):
                self.pos += 2
                continue
            text_content.append(ch)
            self.pos += 1

        if depth != 0:
            self.pos = start
            return None

        link_text = "".join(text_content)
        self.pos += 1  # Skip closing ]

        # Check for (url) or [ref]
        if self.pos < len(self.text) and self.text[self.pos] == "(":
            return self._parse_link_destination(link_text)
        elif self.pos < len(self.text) and self.text[self.pos] == "[":
            return self._parse_reference_link(link_text)
        else:
            # Implicit reference
            if link_text.lower() in {k.lower(): k for k in self.references.keys()}:
                ref_key = next(k for k in self.references.keys() if k.lower() == link_text.lower())
                url, title = self.references[ref_key]
                link = Link(children=self._parse_inline_content_text(link_text), url=url, title=title)
                return link

            self.pos = start
            return None

    def _parse_link_destination(self, link_text: str) -> Link | None:
        """Parse link destination (url)."""
        self.pos += 1  # Skip (

        # Skip whitespace
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
            self.pos += 1

        # Parse URL
        url = ""
        if self.text[self.pos] == "<":
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos] != ">":
                url += self.text[self.pos]
                self.pos += 1
            if self.pos < len(self.text):
                self.pos += 1
        else:
            paren_depth = 0
            while self.pos < len(self.text):
                ch = self.text[self.pos]
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    if paren_depth == 0:
                        break
                    paren_depth -= 1
                elif ch in " \t\n":
                    break
                url += ch
                self.pos += 1

        # Skip whitespace
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
            self.pos += 1

        # Parse optional title
        title = None
        if self.pos < len(self.text) and self.text[self.pos] in "'\"(":
            quote = self.text[self.pos]
            if quote == "(":
                close_quote = ")"
            else:
                close_quote = quote
            self.pos += 1
            title_chars = []
            while self.pos < len(self.text) and self.text[self.pos] != close_quote:
                title_chars.append(self.text[self.pos])
                self.pos += 1
            if self.pos < len(self.text):
                title = "".join(title_chars)
                self.pos += 1

        # Skip whitespace and closing )
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
            self.pos += 1

        if self.pos < len(self.text) and self.text[self.pos] == ")":
            self.pos += 1
            link = Link(children=self._parse_inline_content_text(link_text), url=url, title=title)
            return link

        return None

    def _parse_reference_link(self, link_text: str) -> Link | None:
        """Parse reference link [text][ref]."""
        self.pos += 1  # Skip [

        ref_content = []
        depth = 1
        while self.pos < len(self.text) and depth > 0:
            ch = self.text[self.pos]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            ref_content.append(ch)
            self.pos += 1

        if depth != 0:
            return None

        ref_text = "".join(ref_content).strip()
        if not ref_text:
            ref_text = link_text

        self.pos += 1  # Skip ]

        # Look up reference (case-insensitive)
        ref_key = next((k for k in self.references.keys() if k.lower() == ref_text.lower()), None)
        if ref_key:
            url, title = self.references[ref_key]
            link = Link(children=self._parse_inline_content_text(link_text), url=url, title=title)
            return link

        return None

    def _parse_image(self) -> Image | None:
        """Parse image ![alt](src "title")."""
        if not (self.text[self.pos] == "!" and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == "["):
            return None

        start = self.pos
        self.pos += 2  # Skip ![

        # Parse alt text
        alt_text = []
        depth = 1
        while self.pos < len(self.text) and depth > 0:
            ch = self.text[self.pos]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            alt_text.append(ch)
            self.pos += 1

        if depth != 0:
            self.pos = start
            return None

        alt = "".join(alt_text)
        self.pos += 1  # Skip ]

        if self.pos < len(self.text) and self.text[self.pos] == "(":
            self.pos += 1

            # Parse image URL
            url = ""
            while self.pos < len(self.text) and self.text[self.pos] not in ") \t\n":
                url += self.text[self.pos]
                self.pos += 1

            # Parse title
            title = None
            while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
                self.pos += 1

            if self.pos < len(self.text) and self.text[self.pos] in "'\"":
                quote = self.text[self.pos]
                self.pos += 1
                title_chars = []
                while self.pos < len(self.text) and self.text[self.pos] != quote:
                    title_chars.append(self.text[self.pos])
                    self.pos += 1
                if self.pos < len(self.text):
                    title = "".join(title_chars)
                    self.pos += 1

            while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
                self.pos += 1

            if self.pos < len(self.text) and self.text[self.pos] == ")":
                self.pos += 1
                return Image(alt=alt, src=url, title=title)

        self.pos = start
        return None

    def _parse_autolink(self) -> Link | None:
        """Parse autolink <url>."""
        if self.text[self.pos] != "<":
            return None

        start = self.pos
        self.pos += 1

        url = ""
        while self.pos < len(self.text) and self.text[self.pos] != ">":
            if self.text[self.pos] in "<\n":
                self.pos = start
                return None
            url += self.text[self.pos]
            self.pos += 1

        if self.pos < len(self.text) and self.text[self.pos] == ">":
            self.pos += 1
            link = Link(children=[Text(url)], url=url)
            return link

        self.pos = start
        return None

    def _is_html_tag(self) -> bool:
        """Check if current position is HTML tag."""
        if self.pos >= len(self.text) or self.text[self.pos] != "<":
            return False

        pos = self.pos + 1
        if pos >= len(self.text):
            return False

        ch = self.text[pos]
        return ch.isalpha() or ch in "/!?"

    def _parse_html_inline(self) -> HTMLInline | None:
        """Parse inline HTML tag."""
        start = self.pos
        self.pos += 1  # Skip <

        # Collect tag content
        while self.pos < len(self.text) and self.text[self.pos] != ">":
            self.pos += 1

        if self.pos < len(self.text) and self.text[self.pos] == ">":
            self.pos += 1
            html = self.text[start : self.pos]
            return HTMLInline(html)

        self.pos = start
        return None

    def _parse_entity(self) -> Text | None:
        """Parse HTML entity reference."""
        if self.text[self.pos] != "&":
            return None

        start = self.pos
        self.pos += 1

        # Numeric entity &#123; or &#xABC;
        if self.pos < len(self.text) and self.text[self.pos] == "#":
            self.pos += 1
            is_hex = False
            if self.pos < len(self.text) and self.text[self.pos] in "xX":
                is_hex = True
                self.pos += 1

            num_start = self.pos
            while self.pos < len(self.text) and (
                self.text[self.pos].isdigit() or (is_hex and self.text[self.pos] in "a-fA-F")
            ):
                self.pos += 1

            if self.pos < len(self.text) and self.text[self.pos] == ";" and self.pos > num_start:
                try:
                    num_str = self.text[num_start : self.pos]
                    if is_hex:
                        char_code = int(num_str, 16)
                    else:
                        char_code = int(num_str)
                    self.pos += 1
                    return Text(chr(char_code))
                except (ValueError, OverflowError):
                    pass

        # Named entity
        self.pos = start + 1
        name_chars = []
        while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            name_chars.append(self.text[self.pos])
            self.pos += 1

        if self.pos < len(self.text) and self.text[self.pos] == ";":
            name = "".join(name_chars)
            entities = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
            if name in entities:
                self.pos += 1
                return Text(entities[name])

        self.pos = start
        return None

    def _try_emphasis(self) -> Emphasis | Strong | None:
        """Try to parse emphasis or strong."""
        ch = self.text[self.pos]
        if ch not in "*_":
            return None

        # Count delimiters
        count = 0
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] == ch:
            count += 1
            self.pos += 1

        # Try to match closing delimiters
        if count >= 2:
            # Try strong
            closing_pos = self._find_closing_delimiters(ch, count, 2)
            if closing_pos >= 0:
                content = self.text[start + 2 : closing_pos]
                self.pos = closing_pos + 2
                children = self._parse_inline_content_text(content)
                return Strong(children=children)

        if count >= 1:
            # Try emphasis
            closing_pos = self._find_closing_delimiters(ch, count, 1)
            if closing_pos >= 0:
                content = self.text[start + 1 : closing_pos]
                self.pos = closing_pos + 1
                children = self._parse_inline_content_text(content)
                return Emphasis(children=children)

        self.pos = start
        return None

    def _find_closing_delimiters(self, char: str, count: int, num_needed: int) -> int:
        """Find closing delimiters for emphasis."""
        pos = self.pos
        while pos < len(self.text):
            if self.text[pos] == char:
                close_count = 0
                close_start = pos
                while pos < len(self.text) and self.text[pos] == char:
                    close_count += 1
                    pos += 1
                if close_count >= num_needed:
                    return close_start
            else:
                pos += 1

        return -1

    def _try_strikethrough(self) -> Strikethrough | None:
        """Try to parse strikethrough ~~text~~."""
        if not (self.pos + 1 < len(self.text) and self.text[self.pos : self.pos + 2] == "~~"):
            return None

        start = self.pos
        self.pos += 2

        # Find closing ~~
        while self.pos + 1 < len(self.text):
            if self.text[self.pos : self.pos + 2] == "~~":
                content = self.text[start + 2 : self.pos]
                self.pos += 2
                children = self._parse_inline_content_text(content)
                return Strikethrough(children=children)
            self.pos += 1

        self.pos = start
        return None

    def _try_footnote(self) -> Footnote | None:
        """Try to parse footnote reference [^label]."""
        if not (self.pos + 1 < len(self.text) and self.text[self.pos : self.pos + 2] == "[^"):
            return None

        start = self.pos
        self.pos += 2

        label_chars = []
        while self.pos < len(self.text) and self.text[self.pos] != "]":
            label_chars.append(self.text[self.pos])
            self.pos += 1

        if self.pos < len(self.text) and self.text[self.pos] == "]":
            self.pos += 1
            label = "".join(label_chars)
            if label:
                return Footnote(label=label)

        self.pos = start
        return None

    def _collect_plain_text(self) -> Text | None:
        """Collect plain text until special character."""
        start = self.pos
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in "*_`[]!<\\&~\n":
                break
            self.pos += 1

        if self.pos > start:
            return Text(self.text[start : self.pos])

        # Single character
        self.pos += 1
        return Text(self.text[start])

    def _process_emphasis(self, nodes: list[InlineNode]) -> list[InlineNode]:
        """Post-process to convert delimiters to emphasis/strong."""
        return nodes

    def _parse_inline_content_text(self, text: str) -> list[InlineNode]:
        """Parse inline content from text string."""
        saved_pos = self.pos
        saved_text = self.text
        self.text = text
        self.pos = 0
        result = self._parse_inline_content()
        self.text = saved_text
        self.pos = saved_pos
        return result

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special characters."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
