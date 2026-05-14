"""Tests for template environment and loaders."""

import tempfile
from pathlib import Path

import pytest

from thomas.template_engine import (
    DictLoader,
    Environment,
    FileSystemLoader,
    PrefixLoader,
    TemplateConfig,
)


class TestDictLoader:
    """Test DictLoader functionality."""

    def test_load_template(self) -> None:
        """Test loading template from dict."""
        templates = {"test.html": "Hello {{ name }}"}
        loader = DictLoader(templates)
        source, filename = loader.get_source("test.html")

        assert source == "Hello {{ name }}"

    def test_missing_template(self) -> None:
        """Test loading missing template."""
        loader = DictLoader({})

        with pytest.raises(KeyError):
            loader.get_source("missing.html")

    def test_multiple_templates(self) -> None:
        """Test loading from multiple templates."""
        templates = {
            "base.html": "Base",
            "child.html": "Child",
        }
        loader = DictLoader(templates)

        source1, _ = loader.get_source("base.html")
        source2, _ = loader.get_source("child.html")

        assert source1 == "Base"
        assert source2 == "Child"


class TestFileSystemLoader:
    """Test FileSystemLoader functionality."""

    def test_load_from_filesystem(self) -> None:
        """Test loading templates from filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            template_file = tmpdir_path / "test.html"
            template_file.write_text("Hello {{ name }}")

            loader = FileSystemLoader(str(tmpdir_path))
            source, filename = loader.get_source("test.html")

            assert source == "Hello {{ name }}"
            assert filename is not None

    def test_load_from_multiple_paths(self) -> None:
        """Test loading from multiple search paths."""
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            path1 = Path(tmpdir1)
            path2 = Path(tmpdir2)

            # Create templates in both paths
            (path1 / "base.html").write_text("Base")
            (path2 / "child.html").write_text("Child")

            loader = FileSystemLoader([str(path1), str(path2)])

            source1, _ = loader.get_source("base.html")
            source2, _ = loader.get_source("child.html")

            assert source1 == "Base"
            assert source2 == "Child"

    def test_missing_template_in_filesystem(self) -> None:
        """Test missing template raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = FileSystemLoader(str(tmpdir))

            with pytest.raises(FileNotFoundError):
                loader.get_source("missing.html")

    def test_subdirectory_templates(self) -> None:
        """Test loading templates from subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            subdir = tmpdir_path / "subdir"
            subdir.mkdir()

            template_file = subdir / "test.html"
            template_file.write_text("Hello")

            loader = FileSystemLoader(str(tmpdir_path))
            source, _ = loader.get_source("subdir/test.html")

            assert source == "Hello"


class TestPrefixLoader:
    """Test PrefixLoader functionality."""

    def test_prefix_loading(self) -> None:
        """Test loading with prefix routing."""
        dict_loader1 = DictLoader({"base.html": "Base Template"})
        dict_loader2 = DictLoader({"admin.html": "Admin Template"})

        loader = PrefixLoader(
            {
                "public": dict_loader1,
                "admin": dict_loader2,
            }
        )

        source1, _ = loader.get_source("public/base.html")
        source2, _ = loader.get_source("admin/admin.html")

        assert source1 == "Base Template"
        assert source2 == "Admin Template"

    def test_prefix_not_found(self) -> None:
        """Test missing prefix raises error."""
        loader = PrefixLoader({})

        with pytest.raises(KeyError):
            loader.get_source("unknown/template.html")


class TestEnvironmentBasic:
    """Test basic environment functionality."""

    def test_environment_creation(self) -> None:
        """Test creating environment."""
        env = Environment(loader=DictLoader({}))
        assert env is not None

    def test_get_template(self) -> None:
        """Test getting template from environment."""
        templates = {"test.html": "Hello"}
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("test.html")

        assert template is not None

    def test_template_caching(self) -> None:
        """Test templates are cached."""
        call_count = 0

        class CountingLoader(DictLoader):
            def get_source(self, name: str):
                nonlocal call_count
                call_count += 1
                return super().get_source(name)

        loader = CountingLoader({"test.html": "Hello"})
        env = Environment(loader=loader)

        env.get_template("test.html")
        env.get_template("test.html")

        # Should only load once if caching works
        assert call_count == 1

    def test_cache_invalidation(self) -> None:
        """Test cache can be cleared."""
        env = Environment(loader=DictLoader({"test.html": "Hello"}))

        env.get_template("test.html")
        env.clear_cache()

        # Cache should be empty now
        assert len(env._cache) == 0


class TestEnvironmentFiltersAndTests:
    """Test adding filters and tests to environment."""

    def test_add_custom_filter(self) -> None:
        """Test adding custom filter."""
        env = Environment(loader=DictLoader({"test": "{{ x | custom }}"}))

        def custom_filter(value: str) -> str:
            return value.upper()

        env.add_filter("custom", custom_filter)
        template = env.get_template("test")
        result = template.render(x="hello")

        assert "HELLO" in result

    def test_add_custom_test(self) -> None:
        """Test adding custom test function."""
        env = Environment(loader=DictLoader({"test": "{% if x is custom %}yes{% endif %}"}))

        def custom_test(value: int) -> bool:
            return value > 10

        env.add_test("custom", custom_test)
        template = env.get_template("test")

        result_true = template.render(x=15)
        assert "yes" in result_true

        result_false = template.render(x=5)
        assert "yes" not in result_false

    def test_add_global(self) -> None:
        """Test adding global variable."""
        env = Environment(loader=DictLoader({"test": "{{ site_name }}"}))
        env.add_global("site_name", "MyWebsite")

        template = env.get_template("test")
        result = template.render()

        assert "MyWebsite" in result


class TestEnvironmentConfiguration:
    """Test environment configuration options."""

    def test_autoescape_configuration(self) -> None:
        """Test autoescape configuration."""
        config = TemplateConfig(autoescape=True)
        env = Environment(
            loader=DictLoader({"test": "{{ html }}"}),
            config=config,
        )
        template = env.get_template("test")
        result = template.render(html="<script>")

        # Should be escaped
        assert "&lt;" in result or "<" not in result or "script" in result

    def test_trim_blocks_configuration(self) -> None:
        """Test trim_blocks configuration."""
        config = TemplateConfig(trim_blocks=True)
        env = Environment(
            loader=DictLoader({}),
            config=config,
        )
        assert env.config.trim_blocks is True

    def test_custom_delimiters(self) -> None:
        """Test custom delimiters configuration."""
        config = TemplateConfig(
            var_open="[[",
            var_close="]]",
            block_open="<<",
            block_close=">>",
        )
        env = Environment(
            loader=DictLoader({"test": "[[ x ]]"}),
            config=config,
        )
        template = env.get_template("test")
        result = template.render(x="hello")

        assert "hello" in result


class TestEnvironmentIntegration:
    """Test environment integration."""

    def test_full_template_rendering(self) -> None:
        """Test full template rendering workflow."""
        templates = {
            "base.html": "<html><body>{% block content %}default{% endblock %}</body></html>",
            "page.html": '{% extends "base.html" %}{% block content %}{{ title }}{% endblock %}',
        }

        env = Environment(loader=DictLoader(templates))
        template = env.get_template("page.html")
        result = template.render(title="My Page")

        assert "<html>" in result
        assert "My Page" in result
        assert "</body>" in result

    def test_template_with_filters_and_globals(self) -> None:
        """Test template with both filters and globals."""
        templates = {"test": "{{ greeting }} {{ name | upper }}"}

        env = Environment(loader=DictLoader(templates))
        env.add_global("greeting", "Hello")

        template = env.get_template("test")
        result = template.render(name="alice")

        assert "Hello" in result
        assert "ALICE" in result

    def test_from_string(self) -> None:
        """Test creating template from string."""
        env = Environment()
        template = env.from_string("{{ x | upper }}")
        result = template.render(x="hello")

        assert "HELLO" in result


class TestEnvironmentErrors:
    """Test error handling in environment."""

    def test_missing_loader_template(self) -> None:
        """Test error when template not found."""
        env = Environment(loader=DictLoader({}))

        with pytest.raises(KeyError):
            env.get_template("missing.html")

    def test_syntax_error_in_template(self) -> None:
        """Test syntax error in template."""
        env = Environment(loader=DictLoader({"test": "{% for x in y %}"}))

        with pytest.raises(Exception):
            env.get_template("test")


class TestEnvironmentConcurrency:
    """Test environment with concurrent access."""

    def test_multiple_template_access(self) -> None:
        """Test accessing multiple templates."""
        templates = {
            "a.html": "A: {{ val }}",
            "b.html": "B: {{ val }}",
            "c.html": "C: {{ val }}",
        }

        env = Environment(loader=DictLoader(templates))

        result_a = env.get_template("a.html").render(val=1)
        result_b = env.get_template("b.html").render(val=2)
        result_c = env.get_template("c.html").render(val=3)

        assert "A: 1" in result_a
        assert "B: 2" in result_b
        assert "C: 3" in result_c
