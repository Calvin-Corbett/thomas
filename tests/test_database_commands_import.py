"""Import and credential-redaction contract for database commands."""

import importlib


def test_database_commands_imports_the_shared_error_sanitizer() -> None:
    database_commands = importlib.import_module("thomas.tools.database_commands")
    message = "failed postgres://user:secret@database.example/app"

    sanitized = database_commands._sanitize_error_message(message)

    assert sanitized == "failed postgres://user:***@database.example/app"
    assert "secret" not in sanitized


def test_database_get_tools_builds_the_four_database_tools() -> None:
    database = importlib.import_module("thomas.tools.database")

    names = [tool.name for tool in database.get_tools()]

    assert names == ["db.query", "db.schema", "db.connections", "db.save_connection"]
