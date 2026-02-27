"""Main code generation engine."""

from __future__ import annotations

import ast
import re
import subprocess
from typing import Any

from thomas.codegen import _scaffolds
from thomas.codegen._types import CRUDOutput, GeneratedCode, ProjectScaffold
from thomas.codegen.templates import get_registry


class CodeGeneratorError(RuntimeError):
    """Code generation error."""

    pass


class CodeGenerator:
    """Main code generation engine for creating code from templates and specifications."""

    def __init__(self):
        """Initialize code generator."""
        self.registry = get_registry()

    def generate(
        self,
        template_name: str,
        context: dict[str, Any],
        language: str = "python",
    ) -> GeneratedCode:
        """Generate code from a template.

        Args:
            template_name: Name of template to use
            context: Dictionary of template variables
            language: Programming language

        Returns:
            GeneratedCode with generated code and metadata
        """
        template = self.registry.get(template_name)
        if not template:
            raise CodeGeneratorError(f"Template not found: {template_name}")

        missing = set(template.required_context_keys) - set(context.keys())
        if missing:
            raise CodeGeneratorError(f"Missing context keys: {missing}")

        code = template.template_string
        for key, value in context.items():
            code = code.replace("{" + key + "}", str(value))

        return GeneratedCode(
            code=code,
            language=template.language,
            template=template_name,
            filepath_suggestion=self._suggest_filepath(template_name, context),
        )

    def scaffold_project(
        self,
        project_type: str,
        name: str,
        options: dict[str, Any] | None = None,
    ) -> ProjectScaffold:
        """Scaffold a complete project structure.

        Args:
            project_type: Type of project (python_cli, fastapi, flask, react, node_api)
            name: Project name
            options: Additional options

        Returns:
            ProjectScaffold with generated files and structure
        """
        options = options or {}
        scaffold = ProjectScaffold(name=name)

        scaffold_map = {
            "python_cli": (
                _scaffolds.scaffold_python_cli,
                {
                    "type": "python_cli",
                    "main_file": f"{name}/cli.py",
                    "test_dir": f"{name}/tests",
                },
            ),
            "fastapi": (
                _scaffolds.scaffold_fastapi,
                {
                    "type": "fastapi",
                    "main_file": f"{name}/main.py",
                    "api_dir": f"{name}/api",
                },
            ),
            "flask": (
                _scaffolds.scaffold_flask,
                {
                    "type": "flask",
                    "main_file": f"{name}/app.py",
                    "templates_dir": f"{name}/templates",
                },
            ),
            "react": (
                _scaffolds.scaffold_react,
                {
                    "type": "react",
                    "main_file": f"{name}/src/index.jsx",
                    "components_dir": f"{name}/src/components",
                },
            ),
            "node_api": (
                _scaffolds.scaffold_node_api,
                {
                    "type": "node_api",
                    "main_file": f"{name}/server.js",
                    "routes_dir": f"{name}/routes",
                },
            ),
        }

        if project_type not in scaffold_map:
            raise CodeGeneratorError(f"Unknown project type: {project_type}")

        scaffold_func, structure = scaffold_map[project_type]
        scaffold.files.extend(scaffold_func(name, options))
        scaffold.structure = structure

        return scaffold

    def generate_crud(
        self,
        model_name: str,
        fields: list[dict[str, str]],
        language: str = "python",
        framework: str | None = None,
    ) -> CRUDOutput:
        """Generate CRUD operations for a model.

        Args:
            model_name: Model/entity name
            fields: List of {name, type} dicts
            language: Programming language
            framework: Optional framework

        Returns:
            CRUDOutput with CRUD operations and tests
        """
        if language == "python":
            return self._crud_python(model_name, fields)
        elif language == "javascript":
            return self._crud_javascript(model_name, fields)
        else:
            raise CodeGeneratorError(f"CRUD not supported for {language}")

    def generate_api(
        self,
        spec: dict[str, Any],
        framework: str = "fastapi",
    ) -> dict[str, GeneratedCode]:
        """Generate API endpoints from spec.

        Args:
            spec: API specification with endpoints
            framework: Web framework

        Returns:
            Dictionary of {endpoint_name: GeneratedCode}
        """
        result = {}

        for endpoint_name, endpoint in spec.get("endpoints", {}).items():
            method = endpoint.get("method", "GET").upper()
            path = endpoint.get("path", "/")
            description = endpoint.get("description", "")

            if framework == "fastapi":
                context = {
                    "method": method.lower(),
                    "path": path,
                    "handler_name": self._camel_to_snake(endpoint_name),
                    "description": description,
                    "params": endpoint.get("params", ""),
                    "body": "pass",
                }
                result[endpoint_name] = self.generate("python.fastapi_endpoint", context)
            elif framework == "express":
                context = {
                    "method": method,
                    "path": path,
                    "description": description,
                    "body": "res.json({ message: 'TODO' });",
                }
                result[endpoint_name] = self.generate("javascript.express_route", context)
            else:
                raise CodeGeneratorError(f"API not supported for {framework}")

        return result

    def generate_tests(
        self,
        source_file: str,
        framework: str = "pytest",
    ) -> str:
        """Generate test stubs for a source file.

        Args:
            source_file: Path to source file
            framework: Test framework

        Returns:
            Generated test code
        """
        try:
            with open(source_file) as f:
                source = f.read()
        except Exception as e:
            raise CodeGeneratorError(f"Failed to read: {e}")

        if source_file.endswith(".py"):
            return self._tests_python(source)
        elif source_file.endswith((".js", ".ts")):
            return self._tests_javascript(source)
        else:
            raise CodeGeneratorError(f"Unsupported type: {source_file}")

    def generate_migration(
        self,
        model_name: str,
        fields: list[dict[str, str]],
        dialect: str = "sqlite",
    ) -> GeneratedCode:
        """Generate database migration.

        Args:
            model_name: Table name
            fields: List of {name, type} dicts
            dialect: SQL dialect

        Returns:
            GeneratedCode with migration SQL
        """
        table_name = self._camel_to_snake(model_name)
        columns_list = []

        for field in fields:
            col = f"    {field.get('name')} {field.get('type')}"
            if field.get("primary_key"):
                col += " PRIMARY KEY"
            elif field.get("nullable") is False:
                col += " NOT NULL"
            if field.get("unique"):
                col += " UNIQUE"
            columns_list.append(col)

        columns = ",\n".join(columns_list)
        context = {
            "migration_name": f"create_{table_name}",
            "migration_sql": f"CREATE TABLE {table_name} (\n{columns}\n);",
            "timestamp": "2026-02-26",
        }

        return self.generate("sql.migration_up", context)

    def validate(self, code: str, language: str) -> dict[str, Any]:
        """Validate generated code syntax.

        Args:
            code: Code to validate
            language: Programming language

        Returns:
            {valid: bool, errors: List[str]}
        """
        errors: list[str] = []

        if language == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                errors.append(f"Syntax error at line {e.lineno}: {e.msg}")

        elif language == "javascript":
            try:
                result = subprocess.run(
                    ["node", "--check"],
                    input=code,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    errors.append(result.stderr)
            except Exception:
                if code.count("{") != code.count("}"):
                    errors.append("Mismatched braces")

        elif language == "sql":
            if not any(kw in code.upper() for kw in ["CREATE", "SELECT", "INSERT"]):
                errors.append("No SQL keywords found")

        return {"valid": len(errors) == 0, "errors": errors}

    def format_code(self, code: str, language: str) -> str:
        """Format generated code.

        Args:
            code: Code to format
            language: Programming language

        Returns:
            Formatted code
        """
        if language == "python":
            try:
                result = subprocess.run(
                    ["black", "--quiet", "-"],
                    input=code,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass

        return code

    # Private helpers

    def _suggest_filepath(self, template_name: str, context: dict[str, Any]) -> str:
        """Suggest filepath based on template."""
        if "class_name" in context:
            name = self._camel_to_snake(context["class_name"])
            return f"{name}.py" if "python" in template_name else f"{name}.js"
        elif "function_name" in context:
            name = context["function_name"]
            return f"{name}.py" if "python" in template_name else f"{name}.js"
        return "generated_code.py"

    def _camel_to_snake(self, name: str) -> str:
        """Convert CamelCase to snake_case."""
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

    def _snake_to_camel(self, name: str) -> str:
        """Convert snake_case to camelCase."""
        components = name.split("_")
        return components[0] + "".join(x.title() for x in components[1:])

    def _crud_python(
        self,
        model_name: str,
        fields: list[dict[str, str]],
    ) -> CRUDOutput:
        """Generate Python CRUD."""
        snake = self._camel_to_snake(model_name)

        return CRUDOutput(
            model=model_name,
            create=f"async def create_{snake}(data): return {model_name}(**data)",
            read=f"async def read_{snake}(id): return None",
            update=f"async def update_{snake}(id, data): return None",
            delete=f"async def delete_{snake}(id): return True",
            tests=f"def test_{snake}(): pass",
        )

    def _crud_javascript(
        self,
        model_name: str,
        fields: list[dict[str, str]],
    ) -> CRUDOutput:
        """Generate JavaScript CRUD."""
        camel = self._snake_to_camel(model_name)

        return CRUDOutput(
            model=model_name,
            create=f"async function create{camel}(data) {{ return data; }}",
            read=f"async function read{camel}(id) {{ return null; }}",
            update=f"async function update{camel}(id, data) {{ return data; }}",
            delete=f"async function delete{camel}(id) {{ return true; }}",
            tests=f"test('{model_name}', () => {{ expect(true).toBe(true); }});",
        )

    def _tests_python(self, source: str) -> str:
        """Generate Python tests."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return "# Failed to parse\n"

        tests = '"""Auto-generated tests."""\n\nimport pytest\n\n'

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                tests += f"def test_{node.name}():\n    pass\n\n"

        return tests

    def _tests_javascript(self, source: str) -> str:
        """Generate JavaScript tests."""
        return "describe('Module', () => { test('test', () => { expect(true).toBe(true); }); });\n"
