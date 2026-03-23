"""Core data types for document processing.

This module defines all fundamental data structures used throughout
the document processing pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TextBlockType(Enum):
    """Classification of text block types."""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    OTHER = "other"


class FontStyle(Enum):
    """Font style enumeration."""

    NORMAL = "normal"
    BOLD = "bold"
    ITALIC = "italic"
    BOLD_ITALIC = "bold_italic"
    UNDERLINE = "underline"


class HorizontalAlignment(Enum):
    """Horizontal text alignment."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class VerticalAlignment(Enum):
    """Vertical text alignment."""

    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class LanguageCode(Enum):
    """ISO 639-1 language codes."""

    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    ITALIAN = "it"
    PORTUGUESE = "pt"
    RUSSIAN = "ru"
    CHINESE_SIMPLIFIED = "zh_CN"
    CHINESE_TRADITIONAL = "zh_TW"
    JAPANESE = "ja"


@dataclass
class BoundingBox:
    """Represents a rectangular region on a page.

    Attributes:
        x0: Left edge coordinate in points.
        y0: Top edge coordinate in points.
        x1: Right edge coordinate in points.
        y1: Bottom edge coordinate in points.
        page_number: Optional page number this box is on.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int | None = None

    def width(self) -> float:
        """Get bounding box width."""
        return self.x1 - self.x0

    def height(self) -> float:
        """Get bounding box height."""
        return self.y1 - self.y0

    def area(self) -> float:
        """Get bounding box area."""
        return self.width() * self.height()

    def center(self) -> tuple[float, float]:
        """Get center point of bounding box."""
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def overlaps(self, other: "BoundingBox") -> bool:
        """Check if this box overlaps with another."""
        return not (self.x1 < other.x0 or self.x0 > other.x1 or self.y1 < other.y0 or self.y0 > other.y1)

    def contains(self, point: tuple[float, float]) -> bool:
        """Check if point is contained in this box."""
        x, y = point
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass
class FontInfo:
    """Typographic information for text.

    Attributes:
        name: Font family name.
        size: Font size in points.
        is_bold: Whether text is bold.
        is_italic: Whether text is italic.
        color: RGB color tuple (0-255, 0-255, 0-255).
    """

    name: str
    size: float
    is_bold: bool = False
    is_italic: bool = False
    color: tuple[int, int, int] = (0, 0, 0)

    def style(self) -> FontStyle:
        """Get the FontStyle enumeration value."""
        if self.is_bold and self.is_italic:
            return FontStyle.BOLD_ITALIC
        elif self.is_bold:
            return FontStyle.BOLD
        elif self.is_italic:
            return FontStyle.ITALIC
        return FontStyle.NORMAL


@dataclass
class Style:
    """Formatting style properties.

    Attributes:
        font: Font information.
        font_style: Font style enumeration.
        text_color: RGB text color.
        background_color: RGB background color.
        text_decoration: Additional decorations (underline, strikethrough).
    """

    font: FontInfo
    font_style: FontStyle = FontStyle.NORMAL
    text_color: tuple[int, int, int] = (0, 0, 0)
    background_color: tuple[int, int, int] | None = None
    text_decoration: list[str] = field(default_factory=list)


@dataclass
class Token:
    """A single token (word) with metadata.

    Attributes:
        text: The token text.
        bbox: Bounding box on page.
        style: Font and style information.
        page_number: Page this token appears on.
        confidence: OCR or recognition confidence (0-1).
    """

    text: str
    bbox: BoundingBox
    style: Style | None = None
    page_number: int = 1
    confidence: float = 1.0

    def is_punctuation(self) -> bool:
        """Check if token is pure punctuation."""
        return bool(self.text) and all(not c.isalnum() for c in self.text)

    def is_numeric(self) -> bool:
        """Check if token is purely numeric."""
        try:
            float(self.text)
            return True
        except ValueError:
            return False


@dataclass
class Sentence:
    """A sentence with component tokens.

    Attributes:
        tokens: List of tokens in sentence.
        text: Full sentence text.
        position: Character position in document.
        page_number: Page number.
    """

    tokens: list[Token]
    text: str
    position: int = 0
    page_number: int = 1

    def word_count(self) -> int:
        """Get word count in sentence."""
        return len(self.tokens)

    def char_count(self) -> int:
        """Get character count."""
        return len(self.text)

    def average_token_length(self) -> float:
        """Get average token length."""
        if not self.tokens:
            return 0.0
        return sum(len(t.text) for t in self.tokens) / len(self.tokens)


@dataclass
class Paragraph:
    """A paragraph containing sentences.

    Attributes:
        sentences: List of sentences.
        text: Full paragraph text.
        block_type: Type of text block.
        bbox: Bounding box on page.
        indent_level: Indentation level (0 = no indent).
    """

    sentences: list[Sentence]
    text: str
    block_type: TextBlockType = TextBlockType.PARAGRAPH
    bbox: BoundingBox | None = None
    indent_level: int = 0

    def word_count(self) -> int:
        """Get total word count."""
        return sum(s.word_count() for s in self.sentences)

    def sentence_count(self) -> int:
        """Get sentence count."""
        return len(self.sentences)


@dataclass
class TextBlock:
    """A block of text with layout information.

    Attributes:
        text: Block text content.
        bbox: Bounding box position.
        block_type: Type of text block.
        paragraphs: Paragraphs in this block.
        page_number: Page number.
        confidence: Extraction confidence (0-1).
    """

    text: str
    bbox: BoundingBox
    block_type: TextBlockType = TextBlockType.OTHER
    paragraphs: list[Paragraph] = field(default_factory=list)
    page_number: int = 1
    confidence: float = 1.0

    def word_count(self) -> int:
        """Get word count."""
        return len(self.text.split())


@dataclass
class TableCell:
    """A cell within a table.

    Attributes:
        text: Cell content.
        row_index: Row position.
        col_index: Column position.
        row_span: Number of rows spanned.
        col_span: Number of columns spanned.
        is_header: Whether this is a header cell.
        style: Optional style information.
    """

    text: str
    row_index: int
    col_index: int
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    style: Style | None = None


@dataclass
class Table:
    """A table structure.

    Attributes:
        cells: List of cells in table.
        num_rows: Number of rows.
        num_cols: Number of columns.
        caption: Optional table caption.
        bbox: Bounding box on page.
        page_number: Page number.
    """

    cells: list[TableCell]
    num_rows: int
    num_cols: int
    caption: str | None = None
    bbox: BoundingBox | None = None
    page_number: int = 1

    def get_row(self, row_idx: int) -> list[TableCell]:
        """Get all cells in a row."""
        return [c for c in self.cells if c.row_index == row_idx]

    def get_column(self, col_idx: int) -> list[TableCell]:
        """Get all cells in a column."""
        return [c for c in self.cells if c.col_index == col_idx]

    def to_dict_list(self) -> list[dict[str, str]]:
        """Convert table to list of dictionaries (header-based)."""
        result: list[dict[str, str]] = []
        header_cells = self.get_row(0)
        for row_idx in range(1, self.num_rows):
            row = self.get_row(row_idx)
            row_dict = {}
            for i, cell in enumerate(row):
                header_text = header_cells[i].text if i < len(header_cells) else f"Col{i}"
                row_dict[header_text] = cell.text
            result.append(row_dict)
        return result


@dataclass
class Figure:
    """A figure or image in document.

    Attributes:
        caption: Figure caption text.
        bbox: Position on page.
        page_number: Page number.
        alt_text: Alternative text description.
        image_path: Optional path to image file.
    """

    caption: str
    bbox: BoundingBox
    page_number: int = 1
    alt_text: str | None = None
    image_path: str | None = None


@dataclass
class Header:
    """Document or page header.

    Attributes:
        text: Header text.
        bbox: Position on page.
        page_number: Page number.
        section: Associated section name.
    """

    text: str
    bbox: BoundingBox
    page_number: int = 1
    section: str | None = None


@dataclass
class Footer:
    """Document or page footer.

    Attributes:
        text: Footer text.
        bbox: Position on page.
        page_number: Page number.
    """

    text: str
    bbox: BoundingBox
    page_number: int = 1


@dataclass
class Annotation:
    """An annotation or mark in document.

    Attributes:
        content: Annotation text.
        bbox: Position on page.
        annotation_type: Type (highlight, comment, etc).
        page_number: Page number.
        author: Author of annotation.
        created: Creation timestamp.
    """

    content: str
    bbox: BoundingBox
    annotation_type: str = "comment"
    page_number: int = 1
    author: str | None = None
    created: str | None = None


@dataclass
class Bookmark:
    """A bookmark/outline entry.

    Attributes:
        title: Bookmark title.
        page_number: Target page.
        level: Nesting level (0 = root).
        target_bbox: Optional bounding box.
    """

    title: str
    page_number: int
    level: int = 0
    target_bbox: BoundingBox | None = None


@dataclass
class TOCEntry:
    """Table of contents entry.

    Attributes:
        title: Entry title.
        page_number: Page number.
        level: Heading level (1-6).
        section_number: Optional section numbering.
    """

    title: str
    page_number: int
    level: int = 1
    section_number: str | None = None


@dataclass
class ReadingOrder:
    """Defines reading order of page elements.

    Attributes:
        elements: Ordered list of element IDs or indices.
        flow_direction: Left-to-right or right-to-left.
    """

    elements: list[int]
    flow_direction: str = "ltr"


@dataclass
class Layout:
    """Document page layout information.

    Attributes:
        page_width: Page width in points.
        page_height: Page height in points.
        margin_left: Left margin.
        margin_right: Right margin.
        margin_top: Top margin.
        margin_bottom: Bottom margin.
        columns: Number of columns.
        line_height: Line height.
        reading_order: Reading order information.
    """

    page_width: float
    page_height: float
    margin_left: float = 36.0
    margin_right: float = 36.0
    margin_top: float = 36.0
    margin_bottom: float = 36.0
    columns: int = 1
    line_height: float = 1.5
    reading_order: ReadingOrder | None = None

    def content_width(self) -> float:
        """Get content width after margins."""
        return self.page_width - self.margin_left - self.margin_right

    def content_height(self) -> float:
        """Get content height after margins."""
        return self.page_height - self.margin_top - self.margin_bottom


@dataclass
class Metadata:
    """Document metadata.

    Attributes:
        title: Document title.
        author: Document author.
        subject: Document subject.
        keywords: List of keywords.
        creation_date: Creation date string.
        modification_date: Last modification date.
        creator_tool: Software that created the document.
        language: Language code.
        page_count: Total pages.
        word_count: Total words.
        custom_properties: Additional properties.
    """

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: list[str] = field(default_factory=list)
    creation_date: str | None = None
    modification_date: str | None = None
    creator_tool: str | None = None
    language: LanguageCode | None = None
    page_count: int = 0
    word_count: int = 0
    custom_properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Page:
    """A single page in a document.

    Attributes:
        page_number: Page number (1-indexed).
        text: Extracted text content.
        text_blocks: Identified text blocks.
        tables: Tables on page.
        figures: Figures/images on page.
        header: Page header.
        footer: Page footer.
        annotations: Annotations on page.
        layout: Layout information.
        width: Page width in points.
        height: Page height in points.
    """

    page_number: int
    text: str
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    header: Header | None = None
    footer: Footer | None = None
    annotations: list[Annotation] = field(default_factory=list)
    layout: Layout | None = None
    width: float = 612.0
    height: float = 792.0

    def word_count(self) -> int:
        """Get word count on page."""
        return len(self.text.split())


@dataclass
class Document:
    """Complete document representation.

    Attributes:
        pages: List of pages.
        metadata: Document metadata.
        text: Full document text.
        bookmarks: Navigation bookmarks.
        toc: Table of contents.
    """

    pages: list[Page] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)
    text: str = ""
    bookmarks: list[Bookmark] = field(default_factory=list)
    toc: list[TOCEntry] = field(default_factory=list)

    def page_count(self) -> int:
        """Get total page count."""
        return len(self.pages)

    def word_count(self) -> int:
        """Get total word count."""
        return len(self.text.split())

    def get_page(self, page_number: int) -> Page | None:
        """Get page by number."""
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None

    def extract_text(self) -> str:
        """Extract all text from document."""
        return "\n".join(page.text for page in self.pages)
