"""Template environment and loaders."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._exceptions import CircularIncludeError
from ._types import Block, Extends, Extension, TemplateConfig
from .filters import BUILTIN_FILTERS
from .lexer import Lexer
from .parser import Parser
from .renderer import Renderer
from .tests_builtin import BUILTIN_TESTS


class Loader(ABC):
    """Base class for template loaders."""

    @abstractmethod
    def get_source(self, name: str) -> tuple[str, str | None]:
        """
        Load template source.

        Args:
            name: Template name

        Returns:
            Tuple of (source, filename)
        """
        pass

    def get_filename(self, name: str) -> str | None:
        """Get filename for template."""
        _, filename = self.get_source(name)
        return filename


class FileSystemLoader(Loader):
    """Load templates from filesystem."""

    def __init__(self, searchpath: str | list[str], encoding: str = "utf-8") -> None:
        """
        Initialize filesystem loader.

        Args:
            searchpath: Path or list of paths to search
            encoding: File encoding
        """
        if isinstance(searchpath, str):
            self.searchpath = [Path(searchpath)]
        else:
            self.searchpath = [Path(p) for p in searchpath]
        self.encoding = encoding
        self._cache: dict[str, tuple[str, float]] = {}

    def get_source(self, name: str) -> tuple[str, str | None]:
        """Load template from filesystem."""
        for path in self.searchpath:
            template_path = path / name
            if template_path.exists():
                with open(template_path, encoding=self.encoding) as f:
                    source = f.read()
                return source, str(template_path)

        raise FileNotFoundError(f"Template not found: {name}")


class DictLoader(Loader):
    """Load templates from dictionary."""

    def __init__(self, templates: dict[str, str]) -> None:
        """
        Initialize dict loader.

        Args:
            templates: Dict of template name -> source
        """
        self.templates = templates

    def get_source(self, name: str) -> tuple[str, str | None]:
        """Load template from dict."""
        if name not in self.templates:
            raise KeyError(f"Template not found: {name}")
        return self.templates[name], None


class PackageLoader(Loader):
    """Load templates from Python package."""

    def __init__(self, package_name: str, package_path: str = "templates", encoding: str = "utf-8") -> None:
        """
        Initialize package loader.

        Args:
            package_name: Package name
            package_path: Path within package
            encoding: File encoding
        """
        self.package_name = package_name
        self.package_path = package_path
        self.encoding = encoding

    def get_source(self, name: str) -> tuple[str, str | None]:
        """Load template from package."""
        try:
            import importlib.resources as resources

            # Try new API first (Python 3.9+)
            try:
                pkg = resources.files(self.package_name)
                template_path = pkg / self.package_path / name
                source = template_path.read_text(encoding=self.encoding)
                return source, None
            except (AttributeError, FileNotFoundError):
                # Fall back to older API
                import pkg_resources

                path = f"{self.package_name}/{self.package_path}/{name}"
                source = pkg_resources.resource_string(self.package_name, f"{self.package_path}/{name}").decode(
                    self.encoding
                )
                return source, None
        except (ImportError, FileNotFoundError) as e:
            raise FileNotFoundError(f"Template not found: {name}") from e


class PrefixLoader(Loader):
    """Load templates with name prefix."""

    def __init__(self, loaders: dict[str, Loader]) -> None:
        """
        Initialize prefix loader.

        Args:
            loaders: Dict of prefix -> loader
        """
        self.loaders = loaders

    def get_source(self, name: str) -> tuple[str, str | None]:
        """Load template with prefix."""
        for prefix, loader in self.loaders.items():
            if name.startswith(prefix + "/"):
                rest = name[len(prefix) + 1 :]
                return loader.get_source(rest)

        raise KeyError(f"No loader found for: {name}")


class Environment:
    """Template environment managing loaders, filters, and rendering."""

    def __init__(
        self,
        loader: Loader | None = None,
        config: TemplateConfig | None = None,
        extensions: list[Extension] | None = None,
    ) -> None:
        """
        Initialize environment.

        Args:
            loader: Template loader
            config: Template configuration
            extensions: List of extensions
        """
        self.loader = loader or DictLoader({})
        self.config = config or TemplateConfig()
        self.extensions = extensions or []

        # Built-in filters and tests
        self.filters: dict[str, Callable[..., Any]] = dict(BUILTIN_FILTERS)
        self.tests: dict[str, Callable[[Any, ...], bool]] = dict(BUILTIN_TESTS)

        # Global variables
        self.globals: dict[str, Any] = {}

        # Template cache
        self._cache: dict[str, tuple[Any, str]] = {}
        self._include_stack: list[str] = []

        # Load extensions
        for ext in self.extensions:
            self.filters.update(ext.filters)
            self.tests.update(ext.tests)
            self.globals.update(ext.globals)

    def add_filter(self, name: str, func: Callable[..., Any]) -> None:
        """Register a filter."""
        self.filters[name] = func

    def add_test(self, name: str, func: Callable[[Any, ...], bool]) -> None:
        """Register a test function."""
        self.tests[name] = func

    def add_global(self, name: str, value: Any) -> None:
        """Add global variable."""
        self.globals[name] = value

    def get_template(self, name: str) -> Template:
        """
        Get compiled template.

        Args:
            name: Template name

        Returns:
            Compiled template
        """
        # Check cache
        if self.config.cache_compiled and name in self._cache:
            ast, _source_hash = self._cache[name]
            return Template(self, ast, name)

        # Load and compile template
        source, filename = self.loader.get_source(name)
        source_hash = self._hash_source(source)

        # Lex and parse
        lexer = Lexer(source, self.config)
        tokens = lexer.tokenize()

        parser = Parser(tokens, filename or name)
        ast = parser.parse()

        # Cache if enabled
        if self.config.cache_compiled:
            self._cache[name] = (ast, source_hash)

        return Template(self, ast, name)

    def from_string(self, source: str) -> Template:
        """
        Create template from string.

        Args:
            source: Template source

        Returns:
            Compiled template
        """
        lexer = Lexer(source, self.config)
        tokens = lexer.tokenize()

        parser = Parser(tokens, "<string>")
        ast = parser.parse()

        return Template(self, ast, "<string>")

    def _hash_source(self, source: str) -> str:
        """Hash template source."""
        return hashlib.md5(source.encode()).hexdigest()

    def clear_cache(self) -> None:
        """Clear template cache."""
        self._cache.clear()


class Template:
    """Compiled template."""

    def __init__(self, environment: Environment, ast: Any, name: str) -> None:
        """
        Initialize template.

        Args:
            environment: Template environment
            ast: Template AST
            name: Template name
        """
        self.environment = environment
        self.ast = ast
        self.name = name

    def render(self, **context: Any) -> str:
        """
        Render template with context.

        Args:
            **context: Context variables

        Returns:
            Rendered output
        """
        ctx = dict(self.environment.globals)
        ctx.update(context)

        if self.name in self.environment._include_stack:
            raise CircularIncludeError(f"Circular include detected: {self.name}")

        self.environment._include_stack.append(self.name)

        try:
            renderer = Renderer(
                self.environment.config,
                self.environment.filters,
                self.environment.tests,
            )
            block_overrides = {node.name: node.body for node in self.ast.body if isinstance(node, Block)}
            parent_name = next((node.parent for node in self.ast.body if isinstance(node, Extends)), None)
            render_ast = self.environment.get_template(parent_name).ast if parent_name else self.ast
            output = renderer.render(render_ast, ctx, block_overrides=block_overrides)
        finally:
            self.environment._include_stack.pop()

        return output

    def render_to_file(self, filename: str, **context: Any) -> None:
        """
        Render template and write to file.

        Args:
            filename: Output filename
            **context: Context variables
        """
        output = self.render(**context)
        with open(filename, "w") as f:
            f.write(output)

    def module(self, **context: Any) -> Any:
        """
        Render template as module.

        Args:
            **context: Context variables

        Returns:
            Module-like object
        """

        # Simplified - returns dict of rendered variables
        class TemplateModule:
            def __init__(self, rendered: str) -> None:
                self.module = rendered

        return TemplateModule(self.render(**context))
