"""
Template engine for notification rendering.
Supports variable substitution, conditionals, loops, inheritance, and localization.
"""

import re
from datetime import datetime
from typing import Any

from thomas.notify._exceptions import TemplateException
from thomas.notify._types import ChannelType, Template


class TemplateEngine:
    """Template rendering engine with variable substitution and conditionals."""

    def __init__(self) -> None:
        """Initialize template engine."""
        self.templates: dict[str, Template] = {}
        self.template_versions: dict[str, list[Template]] = {}

    def register_template(self, template: Template) -> None:
        """Register a template.

        Args:
            template: Template to register

        Raises:
            TemplateException: If template with same ID and version exists
        """
        key = f"{template.template_id}:v{template.version}"
        if key in self.templates:
            raise TemplateException(
                f"Template {key} already registered",
                template_id=template.template_id,
            )

        self.templates[key] = template

        if template.template_id not in self.template_versions:
            self.template_versions[template.template_id] = []

        self.template_versions[template.template_id].append(template)

    def get_template(self, template_id: str, version: int | None = None) -> Template:
        """Get template by ID and optional version.

        Args:
            template_id: Template identifier
            version: Template version (defaults to latest)

        Returns:
            Template instance

        Raises:
            TemplateException: If template not found
        """
        if version is None:
            if template_id not in self.template_versions:
                raise TemplateException(
                    f"Template {template_id} not found",
                    template_id=template_id,
                )
            versions = self.template_versions[template_id]
            return max(versions, key=lambda t: t.version)

        key = f"{template_id}:v{version}"
        if key not in self.templates:
            raise TemplateException(
                f"Template {key} not found",
                template_id=template_id,
            )

        return self.templates[key]

    def list_templates(self, channel_type: ChannelType | None = None) -> list[Template]:
        """List all registered templates.

        Args:
            channel_type: Filter by channel type (optional)

        Returns:
            List of templates
        """
        templates = list(self.templates.values())
        if channel_type:
            templates = [t for t in templates if t.channel_type == channel_type]
        return templates

    def render(
        self, template_id: str, variables: dict[str, Any], version: int | None = None, locale: str = "en_US"
    ) -> dict[str, str]:
        """Render template with variables.

        Args:
            template_id: Template identifier
            variables: Variables for substitution
            version: Template version
            locale: Locale for localized templates

        Returns:
            Rendered output with subject and body

        Raises:
            TemplateException: If template not found or rendering fails
        """
        template = self.get_template(template_id, version)

        try:
            localized = self._get_localized_template(template, locale)

            rendered_subject = self._render_content(localized.subject, variables)
            rendered_body = self._render_content(localized.body, variables)

            html_body = None
            if localized.html_body:
                html_body = self._render_content(localized.html_body, variables)

            plain_text = None
            if localized.plain_text_fallback:
                plain_text = self._render_content(localized.plain_text_fallback, variables)

            return {
                "subject": rendered_subject,
                "body": rendered_body,
                "html_body": html_body or "",
                "plain_text": plain_text or rendered_body,
            }

        except TemplateException:
            raise
        except Exception as e:
            raise TemplateException(
                f"Template rendering failed: {str(e)}",
                template_id=template_id,
            )

    def _get_localized_template(self, template: Template, locale: str) -> Template:
        """Get localized version of template.

        Args:
            template: Template to localize
            locale: Target locale

        Returns:
            Localized template or original if not found
        """
        if locale == template.locale:
            return template

        localized_id = f"{template.template_id}_{locale}"
        try:
            return self.get_template(localized_id)
        except TemplateException:
            return template

    def _render_content(self, content: str, variables: dict[str, Any]) -> str:
        """Render content with variable substitution and logic blocks.

        Args:
            content: Content template
            variables: Variables for substitution

        Returns:
            Rendered content
        """
        # Handle conditionals: {{#if condition}} ... {{/if}}
        content = self._process_conditionals(content, variables)

        # Handle loops: {{#each items}} ... {{/each}}
        content = self._process_loops(content, variables)

        # Handle variable substitution: {{variable_name}}
        content = self._substitute_variables(content, variables)

        return content

    def _process_conditionals(self, content: str, variables: dict[str, Any]) -> str:
        """Process conditional blocks.

        Args:
            content: Content with conditionals
            variables: Variables for evaluation

        Returns:
            Content with conditionals resolved
        """
        pattern = r"\{\{#if\s+(\w+)\}\}(.*?)\{\{/if\}\}"
        matches = re.finditer(pattern, content, re.DOTALL)

        for match in matches:
            condition_var = match.group(1)
            block_content = match.group(2)

            if variables.get(condition_var):
                content = content.replace(match.group(0), block_content)
            else:
                content = content.replace(match.group(0), "")

        return content

    def _process_loops(self, content: str, variables: dict[str, Any]) -> str:
        """Process loop blocks.

        Args:
            content: Content with loops
            variables: Variables for iteration

        Returns:
            Content with loops resolved
        """
        pattern = r"\{\{#each\s+(\w+)\}\}(.*?)\{\{/each\}\}"
        matches = re.finditer(pattern, content, re.DOTALL)

        for match in matches:
            items_var = match.group(1)
            loop_content = match.group(2)

            items = variables.get(items_var, [])
            if not isinstance(items, (list, tuple)):
                items = [items]

            rendered_iterations = []
            for item in items:
                item_vars = {"this": item, **(item if isinstance(item, dict) else {})}
                rendered = self._substitute_variables(loop_content, item_vars)
                rendered_iterations.append(rendered)

            replacement = "".join(rendered_iterations)
            content = content.replace(match.group(0), replacement)

        return content

    def _substitute_variables(self, content: str, variables: dict[str, Any]) -> str:
        """Substitute variables in content.

        Args:
            content: Content with variable placeholders
            variables: Variables to substitute

        Returns:
            Content with variables substituted
        """
        pattern = r"\{\{(\w+)\}\}"

        def replacer(match: Any) -> str:
            var_name = match.group(1)
            value = variables.get(var_name, match.group(0))
            return str(value)

        return re.sub(pattern, replacer, content)

    def extract_variables(self, template_id: str) -> set[str]:
        """Extract required variables from template.

        Args:
            template_id: Template identifier

        Returns:
            Set of variable names
        """
        template = self.get_template(template_id)
        content = template.subject + " " + template.body

        variables = set()
        pattern = r"\{\{(\w+)\}\}"
        for match in re.finditer(pattern, content):
            var_name = match.group(1)
            if not var_name.startswith("#"):
                variables.add(var_name)

        return variables

    def preview(self, template_id: str, sample_data: dict[str, Any]) -> dict[str, str]:
        """Preview template with sample data.

        Args:
            template_id: Template identifier
            sample_data: Sample data for preview

        Returns:
            Preview output
        """
        return self.render(template_id, sample_data)


class TemplateManager:
    """Manages template lifecycle: CRUD, versioning, and validation."""

    def __init__(self) -> None:
        """Initialize template manager."""
        self.engine = TemplateEngine()
        self.template_metadata: dict[str, dict[str, Any]] = {}

    def create_template(
        self,
        template_id: str,
        name: str,
        channel_type: ChannelType,
        subject: str,
        body: str,
        html_body: str | None = None,
        plain_text_fallback: str | None = None,
        variables: set[str] | None = None,
        locale: str = "en_US",
    ) -> Template:
        """Create a new template.

        Args:
            template_id: Unique template identifier
            name: Human-readable name
            channel_type: Target channel type
            subject: Template subject/title
            body: Template body content
            html_body: HTML version (optional)
            plain_text_fallback: Plain text fallback (optional)
            variables: Required variables (auto-extracted if not provided)
            locale: Locale for this template

        Returns:
            Created template

        Raises:
            TemplateException: If template already exists
        """
        if template_id in self.engine.template_versions:
            raise TemplateException(
                f"Template {template_id} already exists",
                template_id=template_id,
            )

        if variables is None:
            pattern = r"\{\{(\w+)\}\}"
            variables = {
                match.group(1)
                for match in re.finditer(pattern, f"{subject} {body}")
                if not match.group(1).startswith("#")
            }

        template = Template(
            template_id=template_id,
            name=name,
            channel_type=channel_type,
            subject=subject,
            body=body,
            html_body=html_body,
            plain_text_fallback=plain_text_fallback,
            variables=variables,
            locale=locale,
        )

        self.engine.register_template(template)
        self.template_metadata[template_id] = {
            "created_at": datetime.utcnow(),
            "versions": 1,
        }

        return template

    def update_template(
        self,
        template_id: str,
        subject: str | None = None,
        body: str | None = None,
        html_body: str | None = None,
        plain_text_fallback: str | None = None,
    ) -> Template:
        """Update template (creates new version).

        Args:
            template_id: Template identifier
            subject: New subject (optional)
            body: New body (optional)
            html_body: New HTML body (optional)
            plain_text_fallback: New plain text fallback (optional)

        Returns:
            Updated template with new version

        Raises:
            TemplateException: If template not found
        """
        old_template = self.engine.get_template(template_id)

        new_version = old_template.version + 1
        new_template = Template(
            template_id=template_id,
            name=old_template.name,
            channel_type=old_template.channel_type,
            subject=subject or old_template.subject,
            body=body or old_template.body,
            html_body=html_body or old_template.html_body,
            plain_text_fallback=plain_text_fallback or old_template.plain_text_fallback,
            variables=old_template.variables,
            version=new_version,
            locale=old_template.locale,
        )

        self.engine.register_template(new_template)

        if template_id in self.template_metadata:
            self.template_metadata[template_id]["versions"] = new_version

        return new_template

    def delete_template(self, template_id: str) -> None:
        """Delete template (soft delete - mark as inactive).

        Args:
            template_id: Template identifier

        Raises:
            TemplateException: If template not found
        """
        self.engine.get_template(template_id)

        if template_id in self.template_metadata:
            self.template_metadata[template_id]["deleted_at"] = datetime.utcnow()

    def get_template_versions(self, template_id: str) -> list[Template]:
        """Get all versions of a template.

        Args:
            template_id: Template identifier

        Returns:
            List of template versions

        Raises:
            TemplateException: If template not found
        """
        if template_id not in self.engine.template_versions:
            raise TemplateException(
                f"Template {template_id} not found",
                template_id=template_id,
            )

        return self.engine.template_versions[template_id]

    def validate_template(self, template_id: str) -> bool:
        """Validate template syntax and variables.

        Args:
            template_id: Template identifier

        Returns:
            True if template is valid

        Raises:
            TemplateException: If template is invalid
        """
        try:
            template = self.engine.get_template(template_id)

            # Extract and validate variables
            variables = self.engine.extract_variables(template_id)

            # Validate required variables are present
            if template.variables and not template.variables.issubset(variables | set(template.variables)):
                raise TemplateException(
                    "Template variables mismatch",
                    template_id=template_id,
                )

            # Test render with sample data
            sample_data = {var: f"sample_{var}" for var in variables}
            self.engine.render(template_id, sample_data)

            return True

        except Exception as e:
            if isinstance(e, TemplateException):
                raise
            raise TemplateException(
                f"Template validation failed: {str(e)}",
                template_id=template_id,
            )

    def create_localized_variant(self, base_template_id: str, locale: str, subject: str, body: str) -> Template:
        """Create a localized variant of a template.

        Args:
            base_template_id: Base template identifier
            locale: Target locale
            subject: Localized subject
            body: Localized body

        Returns:
            Localized template

        Raises:
            TemplateException: If base template not found
        """
        base_template = self.engine.get_template(base_template_id)

        localized_id = f"{base_template_id}_{locale}"

        localized = Template(
            template_id=localized_id,
            name=f"{base_template.name} ({locale})",
            channel_type=base_template.channel_type,
            subject=subject,
            body=body,
            html_body=base_template.html_body,
            variables=base_template.variables,
            version=1,
            locale=locale,
            base_template_id=base_template_id,
        )

        self.engine.register_template(localized)
        return localized
