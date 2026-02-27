"""
Tests for template engine and management.
"""

import pytest

from thomas.notify._exceptions import TemplateException
from thomas.notify._types import (
    ChannelType,
    Template,
)
from thomas.notify.templates import (
    TemplateEngine,
    TemplateManager,
)


class TestTemplateEngine:
    """Tests for template rendering engine."""

    def test_register_and_get_template(self) -> None:
        """Test template registration and retrieval."""
        engine = TemplateEngine()

        template = Template(
            template_id="t1",
            name="Test",
            channel_type=ChannelType.EMAIL,
            subject="Subject",
            body="Body",
        )

        engine.register_template(template)
        retrieved = engine.get_template("t1")

        assert retrieved.template_id == "t1"

    def test_substitute_variables(self) -> None:
        """Test variable substitution."""
        engine = TemplateEngine()

        content = "Hello {{name}}, welcome to {{app}}!"

        result = engine._substitute_variables(
            content,
            {"name": "John", "app": "MyApp"},
        )

        assert "John" in result
        assert "MyApp" in result

    def test_process_conditionals(self) -> None:
        """Test conditional block processing."""
        engine = TemplateEngine()

        content = "{{#if premium}}You are premium{{/if}}"

        result = engine._process_conditionals(content, {"premium": True})

        assert "You are premium" in result

    def test_process_conditionals_false(self) -> None:
        """Test conditional block with false condition."""
        engine = TemplateEngine()

        content = "{{#if premium}}Premium{{/if}}"

        result = engine._process_conditionals(content, {"premium": False})

        assert "Premium" not in result

    def test_process_loops(self) -> None:
        """Test loop block processing."""
        engine = TemplateEngine()

        content = "Items: {{#each items}}{{this}}, {{/each}}"

        result = engine._process_loops(content, {"items": ["a", "b", "c"]})

        assert "a" in result
        assert "b" in result
        assert "c" in result

    def test_render_template(self) -> None:
        """Test full template rendering."""
        engine = TemplateEngine()

        template = Template(
            template_id="welcome",
            name="Welcome",
            channel_type=ChannelType.EMAIL,
            subject="Welcome {{name}}",
            body="Hello {{name}}, welcome to {{platform}}!",
        )

        engine.register_template(template)

        result = engine.render(
            "welcome",
            {"name": "Alice", "platform": "MyApp"},
        )

        assert "Alice" in result["subject"]
        assert "Alice" in result["body"]
        assert "MyApp" in result["body"]

    def test_extract_variables(self) -> None:
        """Test variable extraction."""
        engine = TemplateEngine()

        template = Template(
            template_id="t1",
            name="Test",
            channel_type=ChannelType.EMAIL,
            subject="Hello {{name}}",
            body="Welcome {{name}}, your code is {{code}}",
        )

        engine.register_template(template)

        variables = engine.extract_variables("t1")

        assert "name" in variables
        assert "code" in variables

    def test_get_localized_template(self) -> None:
        """Test localized template retrieval."""
        engine = TemplateEngine()

        en_template = Template(
            template_id="greeting",
            name="Greeting",
            channel_type=ChannelType.EMAIL,
            subject="Hello",
            body="Welcome",
            locale="en_US",
        )

        fr_template = Template(
            template_id="greeting_fr_FR",
            name="Greeting FR",
            channel_type=ChannelType.EMAIL,
            subject="Bonjour",
            body="Bienvenue",
            locale="fr_FR",
        )

        engine.register_template(en_template)
        engine.register_template(fr_template)

        localized = engine._get_localized_template(en_template, "fr_FR")

        assert localized.locale == "fr_FR"


class TestTemplateManager:
    """Tests for template management."""

    def test_create_template(self) -> None:
        """Test template creation."""
        manager = TemplateManager()

        template = manager.create_template(
            template_id="welcome",
            name="Welcome Email",
            channel_type=ChannelType.EMAIL,
            subject="Welcome {{name}}",
            body="Hello {{name}}!",
        )

        assert template.template_id == "welcome"
        assert template.version == 1

    def test_create_duplicate_template_raises(self) -> None:
        """Test creating duplicate template raises."""
        manager = TemplateManager()

        manager.create_template(
            template_id="t1",
            name="Template",
            channel_type=ChannelType.EMAIL,
            subject="Subject",
            body="Body",
        )

        with pytest.raises(TemplateException):
            manager.create_template(
                template_id="t1",
                name="Template 2",
                channel_type=ChannelType.EMAIL,
                subject="Subject 2",
                body="Body 2",
            )

    def test_update_template(self) -> None:
        """Test template update creates new version."""
        manager = TemplateManager()

        manager.create_template(
            template_id="t1",
            name="Template",
            channel_type=ChannelType.EMAIL,
            subject="Original",
            body="Body",
        )

        updated = manager.update_template(
            template_id="t1",
            subject="Updated",
        )

        assert updated.version == 2
        assert updated.subject == "Updated"

    def test_get_template_versions(self) -> None:
        """Test getting all template versions."""
        manager = TemplateManager()

        manager.create_template(
            template_id="t1",
            name="Template",
            channel_type=ChannelType.EMAIL,
            subject="V1",
            body="Body",
        )

        manager.update_template(
            template_id="t1",
            subject="V2",
        )

        manager.update_template(
            template_id="t1",
            subject="V3",
        )

        versions = manager.get_template_versions("t1")

        assert len(versions) == 3
        assert versions[0].version == 1
        assert versions[2].version == 3

    def test_validate_template(self) -> None:
        """Test template validation."""
        manager = TemplateManager()

        manager.create_template(
            template_id="t1",
            name="Template",
            channel_type=ChannelType.EMAIL,
            subject="Subject {{name}}",
            body="Body {{name}}",
        )

        assert manager.validate_template("t1") is True

    def test_create_localized_variant(self) -> None:
        """Test creating localized template variant."""
        manager = TemplateManager()

        manager.create_template(
            template_id="greeting",
            name="Greeting",
            channel_type=ChannelType.EMAIL,
            subject="Hello {{name}}",
            body="Welcome {{name}}",
        )

        localized = manager.create_localized_variant(
            base_template_id="greeting",
            locale="es_ES",
            subject="Hola {{name}}",
            body="Bienvenido {{name}}",
        )

        assert localized.locale == "es_ES"
        assert "Hola" in localized.subject
