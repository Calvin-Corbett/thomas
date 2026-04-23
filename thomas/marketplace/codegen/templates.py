"""Template registry for code generation.

Templates use simple {variable} placeholders for substitution.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeTemplate:
    """A code generation template."""

    name: str
    language: str
    description: str
    template_string: str
    required_context_keys: list[str]


class TemplateRegistry:
    """Registry of code generation templates."""

    def __init__(self):
        self.templates: dict[str, CodeTemplate] = {}
        self._register_default_templates()

    def _register_default_templates(self) -> None:
        """Register built-in templates."""

        # Python templates
        self.templates["python.class"] = CodeTemplate(
            name="python.class",
            language="python",
            description="Python class",
            template_string='''"""Class {class_name}."""

from __future__ import annotations

from typing import Any, Dict, Optional


class {class_name}:
    """{description}"""

    def __init__(self{init_params}):
        """{class_name} constructor."""
        {init_body}

    def __str__(self) -> str:
        """String representation."""
        return f"{{{class_name}({repr(self)})}}"

    def __repr__(self) -> str:
        """Representation."""
        return f"<{class_name}()>"
''',
            required_context_keys=["class_name", "description"],
        )

        self.templates["python.function"] = CodeTemplate(
            name="python.function",
            language="python",
            description="Python function",
            template_string='''def {function_name}({params}) -> {return_type}:
    """{description}

    Args:
{args_doc}

    Returns:
        {return_description}
    """
    {body}
''',
            required_context_keys=["function_name", "description", "body"],
        )

        self.templates["python.fastapi_endpoint"] = CodeTemplate(
            name="python.fastapi_endpoint",
            language="python",
            description="FastAPI endpoint",
            template_string='''@app.{method}("/{path}")
async def {handler_name}({params}) -> Dict[str, Any]:
    """{description}"""
    {body}
''',
            required_context_keys=["method", "path", "handler_name", "description", "body"],
        )

        self.templates["python.dataclass"] = CodeTemplate(
            name="python.dataclass",
            language="python",
            description="Python dataclass",
            template_string='''from dataclasses import dataclass
from typing import Optional


@dataclass
class {class_name}:
    """{description}"""

{fields}
''',
            required_context_keys=["class_name", "description", "fields"],
        )

        self.templates["python.pytest_test"] = CodeTemplate(
            name="python.pytest_test",
            language="python",
            description="Pytest test function",
            template_string='''import pytest


def test_{test_name}():
    """{description}"""
    {body}


@pytest.mark.asyncio
async def test_{test_name}_async():
    """{description} (async)"""
    {body_async}
''',
            required_context_keys=["test_name", "description", "body"],
        )

        self.templates["python.cli_command"] = CodeTemplate(
            name="python.cli_command",
            language="python",
            description="Python CLI command",
            template_string='''import click


@click.command()
{options}
def {command_name}({params}):
    """{description}"""
    {body}


if __name__ == "__main__":
    {command_name}()
''',
            required_context_keys=["command_name", "description", "body"],
        )

        # JavaScript templates
        self.templates["javascript.react_component"] = CodeTemplate(
            name="javascript.react_component",
            language="javascript",
            description="React component",
            template_string="""import React from 'react';

/**
 * {class_name}
 * {description}
 */
export const {class_name} = (props) => {{
  {body}

  return (
    <div className="{class_name}">
      {jsx_body}
    </div>
  );
}};

export default {class_name};
""",
            required_context_keys=["class_name", "description", "body", "jsx_body"],
        )

        self.templates["javascript.express_route"] = CodeTemplate(
            name="javascript.express_route",
            language="javascript",
            description="Express route handler",
            template_string="""/**
 * {method} /{path}
 * {description}
 */
app.{method.lower()}('/{path}', (req, res) => {{
  {body}
}});
""",
            required_context_keys=["method", "path", "description", "body"],
        )

        self.templates["javascript.node_module"] = CodeTemplate(
            name="javascript.node_module",
            language="javascript",
            description="Node.js module",
            template_string="""/**
 * {module_name}
 * {description}
 */

class {class_name} {{
  constructor(options = {{}}) {{
    {init_body}
  }}

  {methods}
}}

module.exports = {class_name};
""",
            required_context_keys=["module_name", "class_name", "description", "methods"],
        )

        self.templates["javascript.jest_test"] = CodeTemplate(
            name="javascript.jest_test",
            language="javascript",
            description="Jest test suite",
            template_string="""describe('{suite_name}', () => {{
  test('{test_name}', () => {{
    {body}
  }});

  test('{test_name} async', async () => {{
    {body_async}
  }});
}});
""",
            required_context_keys=["suite_name", "test_name", "description", "body"],
        )

        # SQL templates
        self.templates["sql.create_table"] = CodeTemplate(
            name="sql.create_table",
            language="sql",
            description="CREATE TABLE statement",
            template_string="""CREATE TABLE {table_name} (
{columns}
);
""",
            required_context_keys=["table_name", "columns"],
        )

        self.templates["sql.select_with_join"] = CodeTemplate(
            name="sql.select_with_join",
            language="sql",
            description="SELECT with JOIN",
            template_string="""SELECT {columns}
FROM {from_table}
{joins}
WHERE {where_clause};
""",
            required_context_keys=["columns", "from_table", "where_clause"],
        )

        self.templates["sql.insert"] = CodeTemplate(
            name="sql.insert",
            language="sql",
            description="INSERT statement",
            template_string="""INSERT INTO {table_name} ({columns})
VALUES ({values});
""",
            required_context_keys=["table_name", "columns", "values"],
        )

        self.templates["sql.migration_up"] = CodeTemplate(
            name="sql.migration_up",
            language="sql",
            description="Database migration (up)",
            template_string="""-- Migration: {migration_name}
-- Created: {timestamp}

BEGIN TRANSACTION;

{migration_sql}

COMMIT;
""",
            required_context_keys=["migration_name", "migration_sql"],
        )

        # Go templates
        self.templates["go.struct"] = CodeTemplate(
            name="go.struct",
            language="go",
            description="Go struct",
            template_string="""// {struct_name} {description}
type {struct_name} struct {{
{fields}
}}
""",
            required_context_keys=["struct_name", "description", "fields"],
        )

        self.templates["go.handler"] = CodeTemplate(
            name="go.handler",
            language="go",
            description="Go HTTP handler",
            template_string="""// {handler_name} {description}
func {handler_name}(w http.ResponseWriter, r *http.Request) {{
    {body}
}}
""",
            required_context_keys=["handler_name", "description", "body"],
        )

        self.templates["go.main"] = CodeTemplate(
            name="go.main",
            language="go",
            description="Go main function",
            template_string="""package main

import (
    "fmt"
    {imports}
)

func main() {{
    // {description}
    {body}
}}
""",
            required_context_keys=["description", "body"],
        )

        self.templates["go.test"] = CodeTemplate(
            name="go.test",
            language="go",
            description="Go test function",
            template_string="""package {package_name}

import (
    "testing"
)

func Test{test_name}(t *testing.T) {{
    {body}
}}
""",
            required_context_keys=["package_name", "test_name", "description", "body"],
        )

    def get(self, template_name: str) -> CodeTemplate | None:
        """Get template by name."""
        return self.templates.get(template_name)

    def list_templates(self, language: str | None = None) -> list[CodeTemplate]:
        """List all templates, optionally filtered by language."""
        result = list(self.templates.values())
        if language:
            result = [t for t in result if t.language == language]
        return result

    def register(self, template: CodeTemplate) -> None:
        """Register a custom template."""
        self.templates[template.name] = template


# Global registry instance
_registry = TemplateRegistry()


def get_registry() -> TemplateRegistry:
    """Get the global template registry."""
    return _registry


def get_template(name: str) -> CodeTemplate | None:
    """Get a template by name."""
    return _registry.get(name)


def list_templates(language: str | None = None) -> list[CodeTemplate]:
    """List all templates, optionally filtered by language."""
    return _registry.list_templates(language)
