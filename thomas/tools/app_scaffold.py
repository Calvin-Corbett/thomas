"""Full-app scaffolder: prompt/spec -> a coherent, zero-wiring app.

CAP-116 "Prompt to full app scaffold". From a structured app spec (entities +
fields + a couple of routes/actions) this module deterministically generates a
complete, framework-agnostic app as an in-memory artifact set:

* **Backend generation** -- an ``app`` module exposing one handler per declared
  action plus a dispatch table (``ACTIONS``) and a ``create_app`` factory.
* **Persistence generation** -- a ``repository`` module with a SQLite-backed
  repository per entity, each offering full CRUD (create/get/list/update/delete)
  with typed row mapping.
* **Zero-wiring** -- the generated backend already imports and instantiates the
  generated repositories; every handler calls the repository for its entity, and
  ``create_app`` boots the whole thing with no manual wiring. The emitted files
  reference each other by module name, so dropping them in a directory and
  putting that directory on ``sys.path`` yields a runnable app.

Everything here is pure-stdlib and deterministic: the same spec always produces a
byte-identical file set (no timestamps, no dict-ordering dependence). The
generated persistence code is real, executable Python -- the test suite loads it
against a temporary SQLite database and round-trips a record to prove it works,
not merely that text was emitted.

The generator is the "core" of the zero-wiring prompt flow. A live lane -- taking
a natural-language prompt, running it through an LLM to produce the structured
``AppSpec``, then scaffolding -- is documented but not exercised here; this module
takes the already-structured spec (the same shape an LLM planner would emit) and
turns it into a working app.
"""

from __future__ import annotations

import keyword
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Spec model
# --------------------------------------------------------------------------- #

# Field types the scaffolder understands, mapped to (SQLite column type,
# Python-side reader). The reader converts a raw SQLite value back to the
# declared Python type (SQLite has no native bool).
_FIELD_TYPES: dict[str, str] = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
}

# CRUD operations a route/action may bind to. Each maps an action to the
# repository method its generated handler calls.
_OPERATIONS: dict[str, str] = {
    "create": "create",
    "get": "get",
    "list": "list",
    "update": "update",
    "delete": "delete",
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SpecError(ValueError):
    """Raised when an app spec is structurally invalid or inconsistent."""


def _check_identifier(value: str, what: str) -> str:
    if not isinstance(value, str) or not _IDENT_RE.match(value or ""):
        raise SpecError(f"{what} must be a valid identifier, got {value!r}")
    if keyword.iskeyword(value):
        raise SpecError(f"{what} must not be a Python keyword, got {value!r}")
    return value


@dataclass(frozen=True)
class FieldSpec:
    """A single column on an entity."""

    name: str
    type: str = "str"

    def __post_init__(self) -> None:
        _check_identifier(self.name, "field name")
        if self.name == "id":
            raise SpecError("field name 'id' is reserved (auto primary key)")
        if self.type not in _FIELD_TYPES:
            raise SpecError(
                f"field {self.name!r} has unknown type {self.type!r}; expected one of {sorted(_FIELD_TYPES)}"
            )

    @property
    def sql_type(self) -> str:
        return _FIELD_TYPES[self.type]


@dataclass(frozen=True)
class EntitySpec:
    """A persisted entity: a name plus its (non-id) fields."""

    name: str
    fields: tuple[FieldSpec, ...]

    def __post_init__(self) -> None:
        _check_identifier(self.name, "entity name")
        if not self.fields:
            raise SpecError(f"entity {self.name!r} must declare at least one field")
        seen: set[str] = set()
        for f in self.fields:
            if f.name in seen:
                raise SpecError(f"entity {self.name!r} has duplicate field {f.name!r}")
            seen.add(f.name)

    @property
    def table(self) -> str:
        return _snake(self.name)

    @property
    def class_name(self) -> str:
        return _pascal(self.name) + "Repository"

    @property
    def attr(self) -> str:
        return _snake(self.name) + "_repo"


@dataclass(frozen=True)
class ActionSpec:
    """A route/action bound to an entity and a CRUD operation."""

    name: str
    entity: str
    operation: str
    method: str = ""
    path: str = ""

    def __post_init__(self) -> None:
        _check_identifier(self.name, "action name")
        if self.operation not in _OPERATIONS:
            raise SpecError(
                f"action {self.name!r} has unknown operation {self.operation!r}; expected one of {sorted(_OPERATIONS)}"
            )

    @property
    def handler_name(self) -> str:
        return f"handle_{self.name}"

    @property
    def http_method(self) -> str:
        if self.method:
            return self.method.upper()
        return {
            "create": "POST",
            "get": "GET",
            "list": "GET",
            "update": "PUT",
            "delete": "DELETE",
        }[self.operation]

    @property
    def http_path(self) -> str:
        if self.path:
            return self.path
        base = f"/{_snake(self.entity)}"
        if self.operation in ("get", "update", "delete"):
            return base + "/{id}"
        return base


@dataclass(frozen=True)
class AppSpec:
    """A complete app description: a name, its entities, and its actions."""

    name: str
    entities: tuple[EntitySpec, ...]
    actions: tuple[ActionSpec, ...]

    def __post_init__(self) -> None:
        _check_identifier(self.name, "app name")
        if not self.entities:
            raise SpecError("app must declare at least one entity")
        names: set[str] = set()
        for e in self.entities:
            if e.name in names:
                raise SpecError(f"duplicate entity {e.name!r}")
            names.add(e.name)
        action_names: set[str] = set()
        for a in self.actions:
            if a.name in action_names:
                raise SpecError(f"duplicate action {a.name!r}")
            action_names.add(a.name)
            if a.entity not in names:
                raise SpecError(f"action {a.name!r} targets unknown entity {a.entity!r}")

    def entity(self, name: str) -> EntitySpec:
        for e in self.entities:
            if e.name == name:
                return e
        raise SpecError(f"no such entity {name!r}")

    # -- construction from a structured prompt ------------------------------ #

    @classmethod
    def from_prompt(cls, prompt: Mapping[str, Any]) -> AppSpec:
        """Build an :class:`AppSpec` from a structured prompt mapping.

        This is the shape a planner (or an LLM in the live lane) emits::

            {
              "name": "todo",
              "entities": [
                {"name": "Task", "fields": [{"name": "title", "type": "str"},
                                            {"name": "done", "type": "bool"}]},
                ...
              ],
              "actions": [
                {"name": "create_task", "entity": "Task", "operation": "create"},
                ...
              ],
            }
        """
        if not isinstance(prompt, Mapping):
            raise SpecError("prompt must be a mapping")
        raw_entities = prompt.get("entities")
        if not isinstance(raw_entities, Sequence) or isinstance(raw_entities, (str, bytes)):
            raise SpecError("prompt 'entities' must be a list")
        entities: list[EntitySpec] = []
        for raw in raw_entities:
            if not isinstance(raw, Mapping):
                raise SpecError("each entity must be a mapping")
            raw_fields = raw.get("fields") or []
            if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
                raise SpecError("entity 'fields' must be a list")
            fields: list[FieldSpec] = []
            for rf in raw_fields:
                if not isinstance(rf, Mapping):
                    raise SpecError("each field must be a mapping")
                fields.append(FieldSpec(name=str(rf.get("name", "")), type=str(rf.get("type", "str"))))
            entities.append(EntitySpec(name=str(raw.get("name", "")), fields=tuple(fields)))

        raw_actions = prompt.get("actions") or []
        if not isinstance(raw_actions, Sequence) or isinstance(raw_actions, (str, bytes)):
            raise SpecError("prompt 'actions' must be a list")
        actions: list[ActionSpec] = []
        for raw in raw_actions:
            if not isinstance(raw, Mapping):
                raise SpecError("each action must be a mapping")
            actions.append(
                ActionSpec(
                    name=str(raw.get("name", "")),
                    entity=str(raw.get("entity", "")),
                    operation=str(raw.get("operation", "")),
                    method=str(raw.get("method", "") or ""),
                    path=str(raw.get("path", "") or ""),
                )
            )
        return cls(
            name=str(prompt.get("name", "")),
            entities=tuple(entities),
            actions=tuple(actions),
        )


# --------------------------------------------------------------------------- #
# Consistency report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConsistencyReport:
    """Structured internal-consistency verdict for a scaffolded app."""

    ok: bool
    issues: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


# --------------------------------------------------------------------------- #
# Scaffold result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScaffoldResult:
    """The generated artifact set plus queryable metadata."""

    spec: AppSpec
    files: dict[str, str] = field(default_factory=dict)

    @property
    def entity_names(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.spec.entities)

    @property
    def action_names(self) -> tuple[str, ...]:
        return tuple(a.name for a in self.spec.actions)

    def repository_for(self, entity: str) -> str:
        """Return the repository class name generated for ``entity``."""
        return self.spec.entity(entity).class_name

    def handler_source(self, action: str) -> str:
        """Return the source text of the handler generated for ``action``."""
        for a in self.spec.actions:
            if a.name == action:
                return _extract_block(self.files["app.py"], f"def {a.handler_name}(")
        raise SpecError(f"no such action {action!r}")

    def write(self, directory: str | Path) -> Path:
        """Write the artifact set to ``directory`` and return the path."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        for name, source in sorted(self.files.items()):
            (root / name).write_text(source, encoding="utf-8")
        return root

    def check_consistency(self) -> ConsistencyReport:
        return check_consistency(self)


# --------------------------------------------------------------------------- #
# Name helpers
# --------------------------------------------------------------------------- #


def _snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.replace("-", "_").lower()


def _pascal(name: str) -> str:
    parts = re.split(r"[_\-\s]+", _snake(name))
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _extract_block(source: str, marker: str) -> str:
    """Return the ``def`` block beginning at ``marker`` (indentation-scoped)."""
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(marker):
            indent = len(line) - len(line.lstrip())
            block = [line]
            for nxt in lines[i + 1 :]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                block.append(nxt)
            return "\n".join(block).rstrip() + "\n"
    raise SpecError(f"block {marker!r} not found")


# --------------------------------------------------------------------------- #
# Persistence generation
# --------------------------------------------------------------------------- #


def _gen_repository_class(entity: EntitySpec) -> str:
    cols = list(entity.fields)
    col_names = [c.name for c in cols]
    ddl_cols = ", ".join(f"{c.name} {c.sql_type}" for c in cols)
    create_ddl = f"CREATE TABLE IF NOT EXISTS {entity.table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {ddl_cols})"
    params = ", ".join(col_names)
    placeholders = ", ".join("?" for _ in col_names)
    insert_sql = f"INSERT INTO {entity.table} ({params}) VALUES ({placeholders})"
    select_cols = ", ".join(["id", *col_names])

    # Per-column readers so declared types survive the SQLite round-trip.
    bool_cols = [c.name for c in cols if c.type == "bool"]

    lines: list[str] = []
    lines.append(f"class {entity.class_name}:")
    lines.append(f'    """SQLite-backed repository for {entity.name} records."""')
    lines.append("")
    lines.append("    def __init__(self, conn):")
    lines.append("        self._conn = conn")
    lines.append(f'        self._conn.execute("{create_ddl}")')
    lines.append("        self._conn.commit()")
    lines.append("")
    # _row_to_dict
    lines.append("    @staticmethod")
    lines.append("    def _row_to_dict(row):")
    lines.append("        if row is None:")
    lines.append("            return None")
    lines.append(f"        keys = {['id', *col_names]!r}")
    lines.append("        data = dict(zip(keys, row))")
    for bc in bool_cols:
        lines.append(f"        if data.get({bc!r}) is not None:")
        lines.append(f"            data[{bc!r}] = bool(data[{bc!r}])")
    lines.append("        return data")
    lines.append("")
    # create
    sig = ", ".join(col_names)
    lines.append(f"    def create(self, {sig}):")
    lines.append(f"        values = ({params},)" if len(col_names) == 1 else f"        values = ({params})")
    lines.append(f'        cur = self._conn.execute("{insert_sql}", values)')
    lines.append("        self._conn.commit()")
    lines.append("        return self.get(cur.lastrowid)")
    lines.append("")
    # get
    lines.append("    def get(self, id):")
    lines.append(f'        cur = self._conn.execute("SELECT {select_cols} FROM {entity.table} WHERE id = ?", (id,))')
    lines.append("        return self._row_to_dict(cur.fetchone())")
    lines.append("")
    # list
    lines.append("    def list(self):")
    lines.append(f'        cur = self._conn.execute("SELECT {select_cols} FROM {entity.table} ORDER BY id")')
    lines.append("        return [self._row_to_dict(r) for r in cur.fetchall()]")
    lines.append("")
    # update
    lines.append("    def update(self, id, **fields):")
    lines.append(f"        allowed = {col_names!r}")
    lines.append("        sets = [(k, v) for k, v in fields.items() if k in allowed]")
    lines.append("        if not sets:")
    lines.append("            return self.get(id)")
    lines.append('        clause = ", ".join(f"{k} = ?" for k, _ in sets)')
    lines.append("        values = [v for _, v in sets]")
    lines.append("        values.append(id)")
    lines.append(f'        self._conn.execute(f"UPDATE {entity.table} SET {{clause}} WHERE id = ?", values)')
    lines.append("        self._conn.commit()")
    lines.append("        return self.get(id)")
    lines.append("")
    # delete
    lines.append("    def delete(self, id):")
    lines.append(f'        cur = self._conn.execute("DELETE FROM {entity.table} WHERE id = ?", (id,))')
    lines.append("        self._conn.commit()")
    lines.append("        return cur.rowcount > 0")
    return "\n".join(lines)


def _gen_repository_module(spec: AppSpec) -> str:
    header = [
        '"""Generated persistence layer -- SQLite-backed repositories.',
        "",
        f"Auto-generated by thomas.tools.app_scaffold for app {spec.name!r}.",
        "Do not edit by hand; regenerate from the app spec instead.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import sqlite3",
        "",
        "",
        "def connect(path=':memory:'):",
        '    """Open a SQLite connection for this app\'s repositories."""',
        "    return sqlite3.connect(path)",
        "",
    ]
    blocks = [_gen_repository_class(e) for e in spec.entities]
    exports = ", ".join(repr(e.class_name) for e in spec.entities)
    footer = ["", "", f"__all__ = ['connect', {exports}]" if exports else "__all__ = ['connect']", ""]
    return "\n".join(header) + "\n\n" + "\n\n\n".join(blocks) + "\n" + "\n".join(footer)


# --------------------------------------------------------------------------- #
# Backend generation
# --------------------------------------------------------------------------- #


def _gen_handler(spec: AppSpec, action: ActionSpec) -> str:
    entity = spec.entity(action.entity)
    repo = f"self.{entity.attr}"
    lines: list[str] = []
    lines.append(f"    def {action.handler_name}(self, request):")
    lines.append(
        f'        """{action.http_method} {action.http_path} '
        f'-> {entity.name}.{action.operation} (wired to {entity.class_name})."""'
    )
    lines.append("        request = request or {}")
    if action.operation == "create":
        field_names = [f.name for f in entity.fields]
        args = ", ".join(f"{n}=request.get({n!r})" for n in field_names)
        lines.append(f"        record = {repo}.create({args})")
        lines.append('        return {"status": 201, "body": record}')
    elif action.operation == "get":
        lines.append(f'        record = {repo}.get(request.get("id"))')
        lines.append("        if record is None:")
        lines.append('            return {"status": 404, "body": None}')
        lines.append('        return {"status": 200, "body": record}')
    elif action.operation == "list":
        lines.append(f"        records = {repo}.list()")
        lines.append('        return {"status": 200, "body": records}')
    elif action.operation == "update":
        lines.append('        rid = request.get("id")')
        lines.append('        patch = {k: v for k, v in request.items() if k != "id"}')
        lines.append(f"        record = {repo}.update(rid, **patch)")
        lines.append("        if record is None:")
        lines.append('            return {"status": 404, "body": None}')
        lines.append('        return {"status": 200, "body": record}')
    else:  # delete
        lines.append(f'        deleted = {repo}.delete(request.get("id"))')
        lines.append("        status = 204 if deleted else 404")
        lines.append('        return {"status": status, "body": None}')
    return "\n".join(lines)


def _gen_app_module(spec: AppSpec) -> str:
    repo_classes = ", ".join(e.class_name for e in spec.entities)
    header = [
        '"""Generated backend -- request handlers wired to the persistence layer.',
        "",
        f"Auto-generated by thomas.tools.app_scaffold for app {spec.name!r}.",
        "Every handler is already wired to its entity's repository; ``create_app``",
        "boots the whole app with no manual wiring.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"from repository import connect, {repo_classes}" if repo_classes else "from repository import connect",
        "",
        "",
        "class App:",
        f'    """Backend for the {spec.name!r} app."""',
        "",
        "    def __init__(self, conn):",
        "        self._conn = conn",
    ]
    for e in spec.entities:
        header.append(f"        self.{e.attr} = {e.class_name}(conn)")
    body = [_gen_handler(spec, a) for a in spec.actions]
    # ACTIONS maps action name -> bound method resolved at call time.
    tail: list[str] = []
    tail.append("")
    tail.append("    @property")
    tail.append("    def ACTIONS(self):")
    tail.append('        """Map action name -> bound handler (the wiring table)."""')
    tail.append("        return {")
    for a in spec.actions:
        tail.append(f"            {a.name!r}: self.{a.handler_name},")
    tail.append("        }")
    tail.append("")
    tail.append("    def dispatch(self, action, request=None):")
    tail.append('        """Route an action name to its handler."""')
    tail.append("        handler = self.ACTIONS.get(action)")
    tail.append("        if handler is None:")
    tail.append('            return {"status": 404, "body": {"error": "unknown action"}}')
    tail.append("        return handler(request or {})")
    tail.append("")
    tail.append("")
    tail.append("def create_app(path=':memory:'):")
    tail.append('    """Boot the app: connect persistence and wire handlers. Zero manual wiring."""')
    tail.append("    return App(connect(path))")
    tail.append("")
    tail.append("")
    tail.append("__all__ = ['App', 'create_app']")
    tail.append("")

    parts = "\n".join(header) + "\n\n"
    parts += "\n\n".join(body)
    parts += "\n" + "\n".join(tail)
    return parts


def _gen_init_module(spec: AppSpec) -> str:
    return "\n".join(
        [
            f'"""Generated app package for {spec.name!r} (thomas.tools.app_scaffold)."""',
            "",
            "from app import App, create_app",
            "",
            "__all__ = ['App', 'create_app']",
            "",
        ]
    )


def _gen_readme(spec: AppSpec) -> str:
    lines = [
        f"# {spec.name}",
        "",
        "Zero-wiring app generated by thomas.tools.app_scaffold (CAP-116).",
        "",
        "## Entities",
    ]
    for e in spec.entities:
        cols = ", ".join(f"{f.name}:{f.type}" for f in e.fields)
        lines.append(f"- **{e.name}** ({cols}) -> `{e.class_name}` (full CRUD)")
    lines.append("")
    lines.append("## Actions")
    for a in spec.actions:
        lines.append(f"- `{a.name}`: {a.http_method} {a.http_path} -> {a.entity}.{a.operation}")
    lines.append("")
    lines.append("## Boot")
    lines.append("```python")
    lines.append("from app import create_app")
    lines.append("app = create_app()  # in-memory SQLite; pass a path to persist")
    if spec.actions:
        lines.append(f"resp = app.dispatch({spec.actions[0].name!r}, {{...}})")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def scaffold_app(spec: AppSpec) -> ScaffoldResult:
    """Generate the full zero-wiring app artifact set from ``spec``.

    Deterministic: identical specs yield byte-identical files.
    """
    if not isinstance(spec, AppSpec):
        raise SpecError("scaffold_app requires an AppSpec")
    files = {
        "__init__.py": _gen_init_module(spec),
        "repository.py": _gen_repository_module(spec),
        "app.py": _gen_app_module(spec),
        "README.md": _gen_readme(spec),
    }
    result = ScaffoldResult(spec=spec, files=files)
    report = check_consistency(result)
    if not report.ok:
        raise SpecError("generated app is inconsistent: " + "; ".join(report.issues))
    return result


def scaffold_from_prompt(prompt: Mapping[str, Any]) -> ScaffoldResult:
    """Convenience: structured prompt -> :class:`ScaffoldResult`."""
    return scaffold_app(AppSpec.from_prompt(prompt))


def check_consistency(result: ScaffoldResult) -> ConsistencyReport:
    """Verify the generated app is internally consistent and wired.

    Checks:
      * every entity has a repository class with all five CRUD methods;
      * every action has a handler in the backend;
      * every handler references (is wired to) its entity's repository;
      * the backend imports the persistence layer.
    """
    issues: list[str] = []
    spec = result.spec
    repo_src = result.files.get("repository.py", "")
    app_src = result.files.get("app.py", "")

    if "from repository import" not in app_src:
        issues.append("backend does not import the persistence layer")

    for e in spec.entities:
        if f"class {e.class_name}:" not in repo_src:
            issues.append(f"entity {e.name!r} has no repository class")
            continue
        for method in ("create", "get", "list", "update", "delete"):
            if f"def {method}(" not in repo_src:
                issues.append(f"repository {e.class_name} missing CRUD method {method!r}")
        if f"self.{e.attr} = {e.class_name}(" not in app_src:
            issues.append(f"entity {e.name!r} repository is not instantiated in backend")

    for a in spec.actions:
        if f"def {a.handler_name}(" not in app_src:
            issues.append(f"action {a.name!r} has no handler")
            continue
        entity = spec.entity(a.entity)
        handler_src = result.handler_source(a.name)
        if f"self.{entity.attr}." not in handler_src:
            issues.append(f"handler for action {a.name!r} is not wired to {entity.class_name} (entity {entity.name!r})")
        if f"{a.name!r}: self.{a.handler_name}" not in app_src:
            issues.append(f"action {a.name!r} not registered in dispatch table")

    return ConsistencyReport(ok=not issues, issues=tuple(issues))


__all__ = [
    "ActionSpec",
    "AppSpec",
    "ConsistencyReport",
    "EntitySpec",
    "FieldSpec",
    "ScaffoldResult",
    "SpecError",
    "check_consistency",
    "scaffold_app",
    "scaffold_from_prompt",
]
