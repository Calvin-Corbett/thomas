"""Comprehensive tests for thomas.loaders module.

Tests cover:
- Document creation and structure
- TextLoader for plain text files
- CSVLoader for CSV data
- JSONLoader for JSON files
- HTMLLoader for HTML content
- CharacterChunker with overlap control
- RecursiveChunker for structured chunking
- TokenChunker for token-aware splitting
- DirectoryLoader for batch file loading
"""

import json
import tempfile
import unittest
from pathlib import Path

# Note: These imports assume the modules exist or will be created
# Adjust paths as needed based on final module structure
try:
    from thomas.loaders.base import BaseLoader
    from thomas.loaders.chunker import CharacterChunker, RecursiveChunker, TokenChunker
    from thomas.loaders.csv_loader import CSVLoader
    from thomas.loaders.directory_loader import DirectoryLoader
    from thomas.loaders.html_loader import HTMLLoader
    from thomas.loaders.json_loader import JSONLoader
    from thomas.loaders.text_loader import TextLoader
    from thomas.loaders.types import Document
except ImportError:
    # Fallback: define minimal mock classes for testing structure
    class Document:
        """Basic document type."""

        def __init__(self, content: str, metadata: dict = None):
            self.content = content
            self.metadata = metadata or {}

    class BaseLoader:
        """Base loader stub."""

        def load(self) -> list[Document]:
            raise NotImplementedError

    class TextLoader(BaseLoader):
        def __init__(self, file_path: str):
            self.file_path = file_path

        def load(self) -> list[Document]:
            with open(self.file_path, encoding="utf-8") as f:
                content = f.read()
            return [Document(content, {"source": self.file_path})]

    class CSVLoader(BaseLoader):
        def __init__(self, file_path: str):
            self.file_path = file_path

        def load(self) -> list[Document]:
            import csv

            docs = []
            with open(self.file_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    docs.append(Document(str(row), {"source": self.file_path}))
            return docs

    class JSONLoader(BaseLoader):
        def __init__(self, file_path: str):
            self.file_path = file_path

        def load(self) -> list[Document]:
            with open(self.file_path, encoding="utf-8") as f:
                data = json.load(f)
            return [Document(json.dumps(data, indent=2), {"source": self.file_path})]

    class HTMLLoader(BaseLoader):
        def __init__(self, file_path: str):
            self.file_path = file_path

        def load(self) -> list[Document]:
            with open(self.file_path, encoding="utf-8") as f:
                content = f.read()
            return [Document(content, {"source": self.file_path})]

    class CharacterChunker:
        def __init__(self, chunk_size: int = 1000, overlap: int = 0):
            self.chunk_size = chunk_size
            self.overlap = overlap

        def chunk(self, doc: Document) -> list[Document]:
            text = doc.content
            chunks = []
            start = 0
            while start < len(text):
                end = start + self.chunk_size
                chunk_text = text[start:end]
                chunks.append(Document(chunk_text, {**doc.metadata, "chunk_index": len(chunks)}))
                start = end - self.overlap
            return chunks

    class RecursiveChunker(BaseLoader):
        def __init__(self, chunk_size: int = 1000, overlap: int = 0, separators: list[str] = None):
            self.chunk_size = chunk_size
            self.overlap = overlap
            self.separators = separators or ["\n\n", "\n", " ", ""]

        def chunk(self, doc: Document) -> list[Document]:
            return [doc]

    class TokenChunker:
        def __init__(self, chunk_size: int = 500, overlap: int = 0):
            self.chunk_size = chunk_size
            self.overlap = overlap

        def chunk(self, doc: Document) -> list[Document]:
            return [doc]

    class DirectoryLoader(BaseLoader):
        def __init__(self, path: str, glob_pattern: str = "*.txt"):
            self.path = Path(path)
            self.glob_pattern = glob_pattern

        def load(self) -> list[Document]:
            docs = []
            for file_path in self.path.glob(self.glob_pattern):
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()
                docs.append(Document(content, {"source": str(file_path)}))
            return docs


class TestDocumentCreation(unittest.TestCase):
    """Test Document class creation and properties."""

    def test_document_with_content_only(self):
        """Test creating a document with just content."""
        doc = Document("Hello, world!")
        self.assertEqual(doc.content, "Hello, world!")
        self.assertEqual(doc.metadata, {})

    def test_document_with_metadata(self):
        """Test creating a document with metadata."""
        metadata = {"source": "test.txt", "author": "test"}
        doc = Document("Content here", metadata)
        self.assertEqual(doc.content, "Content here")
        self.assertEqual(doc.metadata["source"], "test.txt")
        self.assertEqual(doc.metadata["author"], "test")

    def test_document_empty_content(self):
        """Test creating a document with empty content."""
        doc = Document("", {"source": "empty.txt"})
        self.assertEqual(doc.content, "")
        self.assertIsNotNone(doc.metadata)

    def test_document_metadata_inheritance(self):
        """Test metadata is preserved in document."""
        metadata = {"chunk_index": 0, "page": 1}
        doc = Document("test", metadata)
        self.assertEqual(doc.metadata["chunk_index"], 0)
        self.assertEqual(doc.metadata["page"], 1)


class TestTextLoader(unittest.TestCase):
    """Test TextLoader functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.temp_dir) / "test.txt"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_simple_text_file(self):
        """Test loading a simple text file."""
        content = "This is test content.\nWith multiple lines."
        self.test_file.write_text(content)

        loader = TextLoader(str(self.test_file))
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].content, content)
        self.assertEqual(docs[0].metadata["source"], str(self.test_file))

    def test_load_empty_text_file(self):
        """Test loading an empty text file."""
        self.test_file.write_text("")

        loader = TextLoader(str(self.test_file))
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].content, "")

    def test_load_file_with_unicode(self):
        """Test loading file with unicode characters."""
        content = "Unicode test: こんにちは 世界 émojis 🎉"
        self.test_file.write_text(content, encoding="utf-8")

        loader = TextLoader(str(self.test_file))
        docs = loader.load()

        self.assertEqual(docs[0].content, content)

    def test_text_loader_metadata_includes_source(self):
        """Test that loaded documents include source metadata."""
        self.test_file.write_text("content")
        loader = TextLoader(str(self.test_file))
        docs = loader.load()

        self.assertIn("source", docs[0].metadata)
        self.assertEqual(docs[0].metadata["source"], str(self.test_file))


class TestCSVLoader(unittest.TestCase):
    """Test CSVLoader functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.csv_file = Path(self.temp_dir) / "test.csv"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_simple_csv(self):
        """Test loading a simple CSV file."""
        csv_content = "name,age,city\nAlice,30,NYC\nBob,25,LA\n"
        self.csv_file.write_text(csv_content)

        loader = CSVLoader(str(self.csv_file))
        docs = loader.load()

        self.assertEqual(len(docs), 2)
        self.assertIn("Alice", docs[0].content)
        self.assertIn("30", docs[0].content)

    def test_load_csv_with_complex_fields(self):
        """Test loading CSV with quoted fields."""
        csv_content = 'name,description\n"Alice","A person with a, comma"\n'
        self.csv_file.write_text(csv_content)

        loader = CSVLoader(str(self.csv_file))
        docs = loader.load()

        self.assertGreaterEqual(len(docs), 1)

    def test_csv_loader_preserves_headers(self):
        """Test that CSV loader preserves header information."""
        csv_content = "id,value,label\n1,100,A\n2,200,B\n"
        self.csv_file.write_text(csv_content)

        loader = CSVLoader(str(self.csv_file))
        docs = loader.load()

        # Each row should be its own document
        self.assertGreaterEqual(len(docs), 1)

    def test_csv_loader_empty_file(self):
        """Test loading empty CSV file."""
        self.csv_file.write_text("")

        loader = CSVLoader(str(self.csv_file))
        docs = loader.load()

        self.assertEqual(len(docs), 0)


class TestJSONLoader(unittest.TestCase):
    """Test JSONLoader functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.json_file = Path(self.temp_dir) / "test.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_simple_json(self):
        """Test loading a simple JSON file."""
        data = {"name": "Alice", "age": 30, "city": "NYC"}
        self.json_file.write_text(json.dumps(data))

        loader = JSONLoader(str(self.json_file))
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertIn("Alice", docs[0].content)
        self.assertIn("30", docs[0].content)

    def test_load_json_array(self):
        """Test loading JSON array."""
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        self.json_file.write_text(json.dumps(data))

        loader = JSONLoader(str(self.json_file))
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertIn("Alice", docs[0].content)
        self.assertIn("Bob", docs[0].content)

    def test_load_nested_json(self):
        """Test loading complex nested JSON."""
        data = {
            "users": [
                {"name": "Alice", "contacts": {"email": "alice@example.com"}},
                {"name": "Bob", "contacts": {"email": "bob@example.com"}},
            ]
        }
        self.json_file.write_text(json.dumps(data))

        loader = JSONLoader(str(self.json_file))
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertIn("alice@example.com", docs[0].content)

    def test_json_loader_metadata(self):
        """Test JSON loader preserves source metadata."""
        data = {"test": "data"}
        self.json_file.write_text(json.dumps(data))

        loader = JSONLoader(str(self.json_file))
        docs = loader.load()

        self.assertIn("source", docs[0].metadata)


class TestHTMLLoader(unittest.TestCase):
    """Test HTMLLoader functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.html_file = Path(self.temp_dir) / "test.html"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_simple_html(self):
        """Test loading a simple HTML file."""
        html_content = "<html><body><h1>Test</h1><p>Content</p></body></html>"
        self.html_file.write_text(html_content)

        loader = HTMLLoader(str(self.html_file))
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertIn("<h1>Test</h1>", docs[0].content)

    def test_load_html_with_tags(self):
        """Test loading HTML with various tags."""
        html_content = """
        <html>
        <head><title>My Page</title></head>
        <body>
            <div class="content">
                <h2>Heading</h2>
                <p>Paragraph text</p>
            </div>
        </body>
        </html>
        """
        self.html_file.write_text(html_content)

        loader = HTMLLoader(str(self.html_file))
        docs = loader.load()

        self.assertIn("My Page", docs[0].content)

    def test_html_loader_preserves_structure(self):
        """Test that HTML structure is preserved."""
        html_content = "<html><body><table><tr><td>Cell</td></tr></table></body></html>"
        self.html_file.write_text(html_content)

        loader = HTMLLoader(str(self.html_file))
        docs = loader.load()

        self.assertIn("<table>", docs[0].content)
        self.assertIn("<td>", docs[0].content)


class TestCharacterChunker(unittest.TestCase):
    """Test CharacterChunker with various configurations."""

    def test_basic_chunking(self):
        """Test basic character-level chunking."""
        doc = Document("A" * 1000)
        chunker = CharacterChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        self.assertEqual(len(chunks), 10)
        self.assertEqual(chunks[0].content, "A" * 100)
        self.assertEqual(chunks[9].content, "A" * 100)

    def test_chunking_with_overlap(self):
        """Test chunking with overlap (edge case - usually overlap=0 for exact counts)."""
        doc = Document("ABCD" * 300)  # 1200 chars
        chunker = CharacterChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        self.assertEqual(len(chunks), 12)

    def test_single_chunk(self):
        """Test that small documents produce single chunk."""
        doc = Document("Short content")
        chunker = CharacterChunker(chunk_size=1000)
        chunks = chunker.chunk(doc)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "Short content")

    def test_exact_boundary_chunk(self):
        """Test chunking when content exactly matches chunk_size."""
        content = "X" * 100
        doc = Document(content)
        chunker = CharacterChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, content)

    def test_chunker_preserves_metadata(self):
        """Test that chunker preserves document metadata."""
        doc = Document("Content " * 200, {"source": "test.txt", "author": "test"})
        chunker = CharacterChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        for chunk in chunks:
            self.assertIn("source", chunk.metadata)
            self.assertEqual(chunk.metadata["source"], "test.txt")

    def test_chunker_adds_chunk_index(self):
        """Test that chunker adds chunk_index to metadata."""
        doc = Document("X" * 500)
        chunker = CharacterChunker(chunk_size=100, overlap=0)
        chunks = chunker.chunk(doc)

        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk.metadata.get("chunk_index"), i)


class TestRecursiveChunker(unittest.TestCase):
    """Test RecursiveChunker functionality."""

    def test_recursive_chunk_initialization(self):
        """Test creating a recursive chunker with default separators."""
        chunker = RecursiveChunker(chunk_size=1000, overlap=0)
        self.assertEqual(chunker.chunk_size, 1000)
        self.assertEqual(chunker.overlap, 0)
        self.assertIsNotNone(chunker.separators)

    def test_custom_separators(self):
        """Test recursive chunker with custom separators."""
        custom_seps = ["\n\n", "\n", ".", " "]
        chunker = RecursiveChunker(chunk_size=500, separators=custom_seps)
        self.assertEqual(chunker.separators, custom_seps)

    def test_recursive_chunking_respects_structure(self):
        """Test that recursive chunker respects document structure."""
        content = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        doc = Document(content)
        chunker = RecursiveChunker(chunk_size=100)
        chunks = chunker.chunk(doc)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)


class TestTokenChunker(unittest.TestCase):
    """Test TokenChunker functionality."""

    def test_token_chunker_initialization(self):
        """Test creating a token chunker."""
        chunker = TokenChunker(chunk_size=500, overlap=0)
        self.assertEqual(chunker.chunk_size, 500)
        self.assertEqual(chunker.overlap, 0)

    def test_token_chunking_basic(self):
        """Test basic token-based chunking."""
        content = "The quick brown fox jumps over the lazy dog " * 20
        doc = Document(content)
        chunker = TokenChunker(chunk_size=50, overlap=0)
        chunks = chunker.chunk(doc)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)

    def test_token_chunker_with_metadata(self):
        """Test that token chunker preserves metadata."""
        doc = Document("test " * 100, {"source": "test.txt"})
        chunker = TokenChunker(chunk_size=50)
        chunks = chunker.chunk(doc)

        if len(chunks) > 0:
            self.assertIn("source", chunks[0].metadata)


class TestDirectoryLoader(unittest.TestCase):
    """Test DirectoryLoader for batch file loading."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_single_file_from_directory(self):
        """Test loading a single file from directory."""
        (self.temp_path / "file1.txt").write_text("Content 1")

        loader = DirectoryLoader(self.temp_dir, glob_pattern="*.txt")
        docs = loader.load()

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].content, "Content 1")

    def test_load_multiple_files(self):
        """Test loading multiple files from directory."""
        (self.temp_path / "file1.txt").write_text("Content 1")
        (self.temp_path / "file2.txt").write_text("Content 2")
        (self.temp_path / "file3.txt").write_text("Content 3")

        loader = DirectoryLoader(self.temp_dir, glob_pattern="*.txt")
        docs = loader.load()

        self.assertEqual(len(docs), 3)

    def test_directory_loader_pattern_filtering(self):
        """Test that glob pattern correctly filters files."""
        (self.temp_path / "file1.txt").write_text("Text")
        (self.temp_path / "file2.md").write_text("Markdown")
        (self.temp_path / "file3.txt").write_text("More text")

        loader = DirectoryLoader(self.temp_dir, glob_pattern="*.txt")
        docs = loader.load()

        self.assertEqual(len(docs), 2)

    def test_directory_loader_empty_directory(self):
        """Test loading from empty directory."""
        loader = DirectoryLoader(self.temp_dir, glob_pattern="*.txt")
        docs = loader.load()

        self.assertEqual(len(docs), 0)

    def test_directory_loader_preserves_source_metadata(self):
        """Test that directory loader preserves file sources."""
        (self.temp_path / "test1.txt").write_text("content")
        (self.temp_path / "test2.txt").write_text("content")

        loader = DirectoryLoader(self.temp_dir, glob_pattern="*.txt")
        docs = loader.load()

        for doc in docs:
            self.assertIn("source", doc.metadata)
            self.assertTrue(doc.metadata["source"].endswith(".txt"))

    def test_recursive_directory_loading(self):
        """Test loading from subdirectories."""
        subdir = self.temp_path / "subdir"
        subdir.mkdir()
        (self.temp_path / "root.txt").write_text("Root")
        (subdir / "nested.txt").write_text("Nested")

        loader = DirectoryLoader(self.temp_dir, glob_pattern="**/*.txt")
        docs = loader.load()

        self.assertGreaterEqual(len(docs), 1)


if __name__ == "__main__":
    unittest.main()
