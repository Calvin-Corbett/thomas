"""Tests for the CAP-116 full-app scaffolder (thomas.tools.app_scaffold).

The centerpiece is a *real execution* proof: the generated persistence code is
loaded as a Python module against a temporary SQLite database and a record is
round-tripped through the generated repository -- demonstrating the scaffolder
emits working code, not just text.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys

import pytest

from thomas.tools.app_scaffold import (
    ActionSpec,
    AppSpec,
    EntitySpec,
    FieldSpec,
    SpecError,
    check_consistency,
    scaffold_app,
    scaffold_from_prompt,
)

# Structured prompt with 2+ entities exercising every field type and CRUD op.
TWO_ENTITY_PROMPT = {
    "name": "todo",
    "entities": [
        {
            "name": "Task",
            "fields": [
                {"name": "title", "type": "str"},
                {"name": "priority", "type": "int"},
                {"name": "done", "type": "bool"},
            ],
        },
        {
            "name": "User",
            "fields": [
                {"name": "email", "type": "str"},
                {"name": "score", "type": "float"},
            ],
        },
    ],
    "actions": [
        {"name": "create_task", "entity": "Task", "operation": "create"},
        {"name": "get_task", "entity": "Task", "operation": "get"},
        {"name": "list_tasks", "entity": "Task", "operation": "list"},
        {"name": "update_task", "entity": "Task", "operation": "update"},
        {"name": "delete_task", "entity": "Task", "operation": "delete"},
        {"name": "create_user", "entity": "User", "operation": "create"},
        {"name": "list_users", "entity": "User", "operation": "list"},
    ],
}


def _load_module(path, name):
    """Import a generated .py file as a fresh top-level module."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def result():
    return scaffold_from_prompt(TWO_ENTITY_PROMPT)


# --------------------------------------------------------------------------- #
# Acceptance line, part 1: backend handlers AND persistence AND they are wired.
# --------------------------------------------------------------------------- #


def test_generates_backend_and_persistence(result):
    files = result.files
    assert "app.py" in files  # backend
    assert "repository.py" in files  # persistence
    # Persistence: a repository class per entity.
    assert "class TaskRepository:" in files["repository.py"]
    assert "class UserRepository:" in files["repository.py"]
    # Backend: a handler per action.
    assert "def handle_create_task(self, request):" in files["app.py"]
    assert "def handle_create_user(self, request):" in files["app.py"]


def test_handler_for_entity_uses_generated_repository(result):
    # The Task handlers must call the generated Task repository (wiring), and
    # the User handler must call the User repository.
    task_handler = result.handler_source("create_task")
    assert "self.task_repo." in task_handler
    assert result.repository_for("Task") == "TaskRepository"

    user_handler = result.handler_source("create_user")
    assert "self.user_repo." in user_handler
    # Cross-check: the Task handler is NOT wired to the User repo.
    assert "self.user_repo." not in task_handler


# --------------------------------------------------------------------------- #
# Acceptance line, part 2: internal consistency.
# --------------------------------------------------------------------------- #


def test_internal_consistency_every_action_has_handler_every_entity_has_crud(result):
    report = check_consistency(result)
    assert report.ok, report.issues
    assert report.issues == ()

    app_src = result.files["app.py"]
    for action in result.action_names:
        assert f"def handle_{action}(" in app_src

    repo_src = result.files["repository.py"]
    for entity in result.entity_names:
        cls = result.repository_for(entity)
        assert f"class {cls}:" in repo_src
    # Full CRUD present.
    for method in ("create", "get", "list", "update", "delete"):
        assert f"def {method}(" in repo_src


def test_consistency_detects_unwired_handler(result):
    # Corrupt the generated backend so a handler no longer touches its repo.
    broken = dict(result.files)
    broken["app.py"] = result.files["app.py"].replace("self.task_repo.create(", "None  # unwired\n        _ = (")
    from thomas.tools.app_scaffold import ScaffoldResult

    corrupted = ScaffoldResult(spec=result.spec, files=broken)
    report = check_consistency(corrupted)
    assert not report.ok
    assert any("create_task" in issue for issue in report.issues)


# --------------------------------------------------------------------------- #
# Acceptance line, part 3: the generated persistence code REALLY round-trips.
# --------------------------------------------------------------------------- #


def test_generated_repository_round_trips_a_record(result, tmp_path):
    root = result.write(tmp_path / "todo_app")
    # Load the generated persistence module and run it against real SQLite.
    repo_mod = _load_module(root / "repository.py", "gen_todo_repository")
    conn = sqlite3.connect(":memory:")
    try:
        repo = repo_mod.TaskRepository(conn)
        created = repo.create(title="write tests", priority=1, done=False)
        assert created["id"] == 1
        assert created["title"] == "write tests"
        assert created["priority"] == 1
        assert created["done"] is False  # bool survived the SQLite round-trip

        fetched = repo.get(created["id"])
        assert fetched == created  # round-trip: what went in comes back out

        updated = repo.update(created["id"], done=True, priority=5)
        assert updated["done"] is True
        assert updated["priority"] == 5

        assert [r["id"] for r in repo.list()] == [1]
        assert repo.delete(created["id"]) is True
        assert repo.get(created["id"]) is None
        assert repo.list() == []
    finally:
        conn.close()
        sys.modules.pop("gen_todo_repository", None)


def test_generated_app_boots_and_dispatches_without_manual_wiring(result, tmp_path):
    root = result.write(tmp_path / "todo_boot")
    sys.path.insert(0, str(root))
    for mod in ("repository", "app"):
        sys.modules.pop(mod, None)
    try:
        _load_module(root / "repository.py", "repository")
        app_mod = _load_module(root / "app.py", "app")
        # Zero-wiring boot: create_app connects persistence + wires handlers.
        app = app_mod.create_app(":memory:")

        # Dispatch across two entities, proving handlers reach both repos.
        resp = app.dispatch("create_task", {"title": "ship", "priority": 2, "done": False})
        assert resp["status"] == 201
        assert resp["body"]["title"] == "ship"

        resp_user = app.dispatch("create_user", {"email": "a@b.co", "score": 9.5})
        assert resp_user["status"] == 201
        assert resp_user["body"]["email"] == "a@b.co"

        listed = app.dispatch("list_tasks")
        assert listed["status"] == 200
        assert len(listed["body"]) == 1

        missing = app.dispatch("get_task", {"id": 999})
        assert missing["status"] == 404

        unknown = app.dispatch("no_such_action")
        assert unknown["status"] == 404
    finally:
        for mod in ("repository", "app"):
            sys.modules.pop(mod, None)
        if str(root) in sys.path:
            sys.path.remove(str(root))


# --------------------------------------------------------------------------- #
# Acceptance line, part 4: determinism.
# --------------------------------------------------------------------------- #


def test_scaffold_is_deterministic():
    first = scaffold_from_prompt(TWO_ENTITY_PROMPT).files
    second = scaffold_from_prompt(TWO_ENTITY_PROMPT).files
    assert first == second
    # Byte-for-byte identical per file.
    for name in first:
        assert first[name] == second[name]


# --------------------------------------------------------------------------- #
# Spec validation.
# --------------------------------------------------------------------------- #


def test_action_targeting_unknown_entity_rejected():
    with pytest.raises(SpecError):
        AppSpec(
            name="bad",
            entities=(EntitySpec(name="Task", fields=(FieldSpec("title", "str"),)),),
            actions=(ActionSpec(name="x", entity="Ghost", operation="create"),),
        )


def test_unknown_field_type_rejected():
    with pytest.raises(SpecError):
        FieldSpec(name="weird", type="complex")


def test_reserved_id_field_rejected():
    with pytest.raises(SpecError):
        FieldSpec(name="id", type="int")


def test_from_prompt_requires_entities():
    with pytest.raises(SpecError):
        AppSpec.from_prompt({"name": "empty", "entities": []})


def test_programmatic_spec_matches_prompt_spec():
    programmatic = AppSpec(
        name="todo",
        entities=(
            EntitySpec(
                name="Task",
                fields=(
                    FieldSpec("title", "str"),
                    FieldSpec("priority", "int"),
                    FieldSpec("done", "bool"),
                ),
            ),
            EntitySpec(
                name="User",
                fields=(FieldSpec("email", "str"), FieldSpec("score", "float")),
            ),
        ),
        actions=(
            ActionSpec("create_task", "Task", "create"),
            ActionSpec("get_task", "Task", "get"),
            ActionSpec("list_tasks", "Task", "list"),
            ActionSpec("update_task", "Task", "update"),
            ActionSpec("delete_task", "Task", "delete"),
            ActionSpec("create_user", "User", "create"),
            ActionSpec("list_users", "User", "list"),
        ),
    )
    assert scaffold_app(programmatic).files == scaffold_from_prompt(TWO_ENTITY_PROMPT).files
