from __future__ import annotations

"""Plugin package bootstrap for Thomas.

This module generates a minimal, importable Python package implementing a Thomas
plugin skeleton. It is intended for automation and local developer tooling.

The generated package is *not* automatically installed; it simply writes files
to disk. Installation/distribution decisions are left to the caller.

Deterministic errors are provided for reliable automation.
"""

import hashlib
import json
import keyword
import re
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.plugins.p098_plugin_manifest_schema import PluginManifestSchemaError, validate_plugin_manifest

# -----------------------------
# Deterministic errors
# -----------------------------


class PluginBootstrapError(RuntimeError):
    """Deterministic error with a stable machine-readable code."""

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidInputError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="invalid_input", message=message, details=details)


class AlreadyExistsError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="already_exists", message=message, details=details)


class InstallFailedError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="install_failed", message=message, details=details)


class ExternalFailureError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="external_failure", message=message, details=details)


# -----------------------------
# Typed contracts
# -----------------------------


@dataclass(frozen=True)
class PluginBootstrapRequest:
    plugin_name: str
    destination_dir: Path
    description: str = "Thomas plugin package"
    author: str = ""
    overwrite: bool = False
    create_skill: bool = True
    skill_root: Path | None = None
    skill_name: str = ""
    skill_intents: Sequence[str] = field(default_factory=tuple)
    skill_tools: Sequence[str] = field(default_factory=tuple)
    skill_examples: Sequence[str] = field(default_factory=tuple)
    assistant_instructions: str = ""
    conversation_starters: Sequence[str] = field(default_factory=tuple)
    knowledge_files: Sequence[Path] = field(default_factory=tuple)
    allowed_tools: Sequence[str] = field(default_factory=tuple)
    allowed_apps: Sequence[str] = field(default_factory=tuple)
    allowed_apis: Sequence[str] = field(default_factory=tuple)
    plugin_version: str = "0.1.0"
    create_manifest: bool = True
    create_share_bundle: bool = False
    share_bundle_path: Path | None = None
    validate: bool = True
    install_after_bootstrap: bool = False
    install_root: Path | None = None
    install_overwrite: bool = False


@dataclass(frozen=True)
class PluginBootstrapResult:
    plugin_name: str
    package_dir: str
    manifest_file: str | None = None
    manifest_dir: str | None = None
    skill_file: str | None = None
    skill_dir: str | None = None
    installed_plugin: str | None = None
    installed_path: str | None = None
    installation_result_path: str | None = None
    install_root: str | None = None
    share_bundle_file: str | None = None
    share_bundle_sha256: str | None = None
    knowledge_files: list[str] = field(default_factory=list)
    validation_ok: bool = True
    validation_errors: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "package_dir": self.package_dir,
            "manifest_file": self.manifest_file,
            "manifest_dir": self.manifest_dir,
            "skill_file": self.skill_file,
            "skill_dir": self.skill_dir,
            "installed_plugin": self.installed_plugin,
            "installed_path": self.installed_path,
            "installation_result_path": self.installation_result_path,
            "install_root": self.install_root,
            "share_bundle_file": self.share_bundle_file,
            "share_bundle_sha256": self.share_bundle_sha256,
            "knowledge_files": self.knowledge_files,
            "validation_ok": self.validation_ok,
            "validation_errors": self.validation_errors,
            "files_created": self.files_created,
            "warnings": self.warnings,
        }


# -----------------------------
# Implementation
# -----------------------------


_PKG_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_WHITESPACE_RE = re.compile(r"\s+")
_TOML_ESCAPE_RE = re.compile(r"[\r\n\t\"]")
_PERMISSION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_MAX_KNOWLEDGE_FILE_BYTES = 2 * 1024 * 1024
_MAX_KNOWLEDGE_TOTAL_BYTES = 10 * 1024 * 1024


def _normalize_plugin_name(name: str) -> str:
    normalized = _WHITESPACE_RE.sub("_", (name or "").strip().replace("-", "_").strip())
    normalized = re.sub(r"[^0-9a-zA-Z_]", "_", normalized).strip("_")
    if not normalized:
        raise InvalidInputError("plugin_name is required.")
    return normalized


def _validate_plugin_name(name: str) -> str:
    normalized = _normalize_plugin_name(name).lower()
    if not _PKG_NAME_RE.match(normalized):
        raise InvalidInputError(
            "plugin_name must be a valid Python package identifier.",
            details={"plugin_name": normalized},
        )

    if keyword.iskeyword(normalized):
        raise InvalidInputError("plugin_name cannot be a Python keyword.", details={"plugin_name": normalized})

    return normalized


def _validate_skill_name(name: str) -> str:
    normalized = _normalize_plugin_name(name or "").replace("-", "_")
    if not _PKG_NAME_RE.match(normalized):
        raise InvalidInputError(
            "skill_name must be a valid directory name.",
            details={"skill_name": normalized},
        )
    return normalized


def _toml_escape(value: str) -> str:
    # Keep escaping simple and deterministic; this is not a full TOML encoder.
    return _TOML_ESCAPE_RE.sub(lambda m: {"\r": "\\r", "\n": "\\n", "\t": "\\t", '"': '\\"'}[m.group(0)], value)


def _py_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _write_file(path: Path, content: str, *, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise ExternalFailureError(
            "Unable to write file.",
            details={"path": str(path), "error": str(e)},
        ) from e
    return True


def _split_csv_items(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _normalize_sequence(items: Sequence[str] | str | None) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        return _split_csv_items(items)
    cleaned: list[str] = []
    for raw in items:
        text = str(raw or "").strip()
        if text:
            cleaned.append(text)
    return cleaned


def _normalize_permissions(items: Sequence[str] | str | None, *, field_name: str) -> list[str]:
    values = _normalize_sequence(items)
    normalized: list[str] = []
    for value in values:
        if not _PERMISSION_RE.fullmatch(value) or value.lower() in {"all", "any", "root", "system"}:
            raise InvalidInputError(
                f"{field_name} contains an invalid or unrestricted permission.",
                details={"field": field_name, "value": value},
            )
        if value not in normalized:
            normalized.append(value)
    return normalized


def _copy_knowledge_files(
    sources: Sequence[Path],
    *,
    package_dir: Path,
    overwrite: bool,
) -> tuple[list[str], list[str]]:
    if not sources:
        return [], []

    knowledge_dir = package_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    relative_paths: list[str] = []
    created: list[str] = []
    seen_names: set[str] = set()
    total_bytes = 0
    for raw_source in sources:
        source = Path(raw_source).expanduser()
        try:
            if source.is_symlink():
                raise InvalidInputError(
                    "Knowledge files must not be symbolic links.",
                    details={"path": str(source)},
                )
            resolved = source.resolve(strict=True)
        except InvalidInputError:
            raise
        except (OSError, RuntimeError) as exc:
            raise InvalidInputError(
                "Knowledge file does not exist or cannot be resolved.",
                details={"path": str(source), "reason": type(exc).__name__},
            ) from exc
        if not resolved.is_file():
            raise InvalidInputError("Knowledge attachment must be a file.", details={"path": str(resolved)})
        size = resolved.stat().st_size
        total_bytes += size
        if size > _MAX_KNOWLEDGE_FILE_BYTES or total_bytes > _MAX_KNOWLEDGE_TOTAL_BYTES:
            raise InvalidInputError(
                "Knowledge attachment exceeds the safe package size limit.",
                details={"path": str(resolved), "size_bytes": size, "total_bytes": total_bytes},
            )
        name = resolved.name
        if name in seen_names:
            raise InvalidInputError("Knowledge attachment names must be unique.", details={"name": name})
        seen_names.add(name)
        destination = knowledge_dir / name
        if destination.exists() and not overwrite:
            raise AlreadyExistsError(
                "Knowledge attachment already exists in the package.",
                details={"path": str(destination)},
            )
        try:
            shutil.copyfile(resolved, destination)
        except OSError as exc:
            raise ExternalFailureError(
                "Unable to copy knowledge attachment.",
                details={"source": str(resolved), "destination": str(destination), "reason": type(exc).__name__},
            ) from exc
        relative_paths.append(f"knowledge/{name}")
        created.append(str(destination))
    return relative_paths, created


def _resolve_skill_root(destination: Path, explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root

    candidates = (
        destination / ".codex" / "skills",
        destination / "skills",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _build_skill_md(
    *,
    plugin_name: str,
    description: str,
    author: str,
    intents: Sequence[str],
    tools: Sequence[str],
    examples: Sequence[str],
) -> str:
    intent_lines = "\n".join(f"- {intent}" for intent in intents) or "- General plugin development"
    tool_lines = "\n".join(f"- {tool}" for tool in tools) or "- Not defined yet"
    example_lines = "\n".join(f"- {example}" for example in examples) or "- `thomas plugin --help` (auto scaffold path)"
    authors = (author or "Unknown").strip()

    return (
        f"# {plugin_name} plugin\n\n"
        f"{description}\n\n"
        "## Scope\n"
        "Apply this skill when working on the Thomas plugin package with the same name.\n\n"
        "## Intent\n"
        f"{intent_lines}\n\n"
        "## Author\n"
        f"- {authors}\n\n"
        "## Plugin Wiring\n"
        "Use this skill to keep implementations aligned:\n"
        "- Keep plugin registration deterministic and minimal.\n"
        "- Keep runtime side-effects opt-in and testable.\n"
        "- Prefer explicit schemas and stable output on errors.\n\n"
        "## Tool Surface\n"
        f"{tool_lines}\n\n"
        "## Examples\n"
        f"{example_lines}\n\n"
        "## Safety Checks\n"
        "- Verify generated files include package entrypoints.\n"
        "- Keep credentials and tokens out of generated templates.\n"
        "- Regenerate SKILL.md when plugin behavior changes.\n"
    )


def _build_plugin_code(
    name: str,
    description: str,
    version: str,
    *,
    instructions: str,
    conversation_starters: Sequence[str],
    knowledge_files: Sequence[str],
    allowed_tools: Sequence[str],
    allowed_apps: Sequence[str],
    allowed_apis: Sequence[str],
) -> str:
    return (
        "from __future__ import annotations\n\n"
        f'"""{_py_escape(description)}"""\n\n'
        "from dataclasses import dataclass\n"
        "from pathlib import Path\n"
        "from typing import Any\n\n"
        "@dataclass\n"
        "class Plugin:\n"
        '    """Assistant-backed plugin with explicit knowledge and authority."""\n\n'
        f"    plugin_id: str = {name!r}\n"
        f'    name: str = "{_py_escape(name)}"\n'
        f'    version: str = "{_py_escape(version)}"\n'
        f'    description: str = "{_py_escape(description)}"\n'
        f"    instructions: str = {instructions!r}\n"
        f"    conversation_starters: tuple[str, ...] = {tuple(conversation_starters)!r}\n"
        f"    knowledge_files: tuple[str, ...] = {tuple(knowledge_files)!r}\n"
        f"    allowed_tools: tuple[str, ...] = {tuple(allowed_tools)!r}\n"
        f"    allowed_apps: tuple[str, ...] = {tuple(allowed_apps)!r}\n"
        f"    allowed_apis: tuple[str, ...] = {tuple(allowed_apis)!r}\n\n"
        "    def _knowledge_matches(self, query: str) -> list[dict[str, str]]:\n"
        "        package_root = Path(__file__).resolve().parent\n"
        "        needle = str(query or '').strip().lower()\n"
        "        if not needle:\n"
        "            return []\n"
        "        matches: list[dict[str, str]] = []\n"
        "        for relative in self.knowledge_files:\n"
        "            candidate = (package_root / relative).resolve()\n"
        "            try:\n"
        "                candidate.relative_to(package_root)\n"
        "            except ValueError:\n"
        "                continue\n"
        "            if not candidate.is_file() or candidate.is_symlink():\n"
        "                continue\n"
        "            text = candidate.read_text(encoding='utf-8', errors='replace')[:262144]\n"
        "            position = text.lower().find(needle)\n"
        "            if position >= 0:\n"
        "                start = max(0, position - 80)\n"
        "                end = min(len(text), position + len(needle) + 160)\n"
        "                matches.append({'file': relative, 'excerpt': text[start:end]})\n"
        "        return matches\n\n"
        "    def use(self, prompt: str, *, tool_name: str = '', knowledge_query: str = '') -> dict[str, Any]:\n"
        "        requested_tool = str(tool_name or '').strip()\n"
        "        if requested_tool and requested_tool not in self.allowed_tools:\n"
        "            raise PermissionError(f\"Tool '{requested_tool}' is not allowed for this assistant.\")\n"
        "        return {\n"
        "            'plugin_id': self.plugin_id,\n"
        "            'instructions': self.instructions,\n"
        "            'prompt': str(prompt),\n"
        "            'tool': requested_tool,\n"
        "            'knowledge': self._knowledge_matches(knowledge_query),\n"
        "        }\n\n"
        "    def register(self, registry: Any) -> None:\n"
        '        """Register plugin capabilities with a Thomas registry."""\n'
        "        _ = registry\n"
        "        return\n\n"
        "def register(registry: Any) -> None:\n"
        '    """Compatibility entrypoint for module-style plugin loading."""\n'
        "    Plugin().register(registry)\n\n"
        "def get_plugin() -> Plugin:\n"
        '    """Runtime entrypoint used by Thomas installed-plugin loading."""\n'
        "    return Plugin()\n\n"
        "def create_plugin() -> Plugin:\n"
        '    """Compatibility alias for plugin runtimes using create_plugin."""\n'
        "    return get_plugin()\n"
    )


def _build_plugin_manifest(
    *,
    plugin_name: str,
    version: str,
    description: str,
    author: str,
    instructions: str,
    conversation_starters: Sequence[str],
    knowledge_files: Sequence[str],
    allowed_tools: Sequence[str],
    allowed_apps: Sequence[str],
    allowed_apis: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    module_entrypoint = f"{plugin_name}.plugin:get_plugin"
    assistant = {
        "instructions": instructions,
        "conversation_starters": list(conversation_starters),
        "knowledge_files": list(knowledge_files),
    }
    permissions = {
        "tools": list(allowed_tools),
        "apps": list(allowed_apps),
        "apis": list(allowed_apis),
    }

    simple_manifest = {
        "name": plugin_name,
        "version": version,
        "description": description,
        "entrypoint": module_entrypoint,
        "runtime": "python",
        "capabilities": ["custom_assistant"],
        "assistant": assistant,
        "permissions": permissions,
    }
    if author:
        simple_manifest["author"] = author

    rich_manifest = {
        "schema_version": "v1",
        "plugin": {
            "id": plugin_name,
            "name": plugin_name,
            "description": description,
            "version": version,
        },
        "runtime": {
            "kind": "python",
            "entrypoint": module_entrypoint,
        },
        "tools": [],
        "assistant": assistant,
        "permissions": permissions,
    }
    if author:
        rich_manifest["plugin"]["author"] = author
    return simple_manifest, rich_manifest


def _create_share_bundle(package_dir: Path, output_path: Path, *, overwrite: bool) -> str:
    if output_path.exists() and not overwrite:
        raise AlreadyExistsError("Share bundle already exists.", details={"path": str(output_path)})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sorted(package_dir.rglob("*")):
                if source.is_symlink():
                    raise InvalidInputError(
                        "Plugin share bundles must not contain symbolic links.", details={"path": str(source)}
                    )
                if not source.is_file():
                    continue
                relative = source.relative_to(package_dir)
                if "__pycache__" in relative.parts or source.suffix.lower() in {".pyc", ".pyo"}:
                    continue
                archive.write(source, arcname=str(Path(package_dir.name) / relative).replace("\\", "/"))
    except PluginBootstrapError:
        if output_path.exists():
            output_path.unlink()
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        if output_path.exists():
            output_path.unlink()
        raise ExternalFailureError(
            "Unable to create plugin share bundle.",
            details={"path": str(output_path), "reason": type(exc).__name__},
        ) from exc
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def _to_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _validate_json_file(path: Path) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ExternalFailureError(
            "Unable to validate generated manifest.",
            details={"path": str(path), "error": type(e).__name__, "reason": str(e)},
        ) from e


def _validate_python_source(path: Path) -> None:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except Exception as e:
        raise ExternalFailureError(
            "Unable to validate generated Python source.",
            details={"path": str(path), "error": type(e).__name__, "reason": str(e)},
        ) from e


def bootstrap_plugin_package(req: PluginBootstrapRequest) -> PluginBootstrapResult:
    name = _validate_plugin_name(req.plugin_name)
    dest = req.destination_dir

    if str(dest).strip() == "":
        raise InvalidInputError("destination_dir is required.")

    package_dir = dest / name

    if package_dir.exists() and not req.overwrite:
        raise AlreadyExistsError(
            "Plugin package directory already exists.",
            details={"package_dir": str(package_dir)},
        )

    try:
        package_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ExternalFailureError(
            "Unable to create plugin package directory.",
            details={"package_dir": str(package_dir), "error": str(e)},
        ) from e

    files_created: list[str] = []
    warnings: list[str] = []
    manifest_file: Path | None = None
    skill_file: Path | None = None
    validation_errors: list[str] = []
    validation_ok = True
    installed_plugin: str | None = None
    installed_path: str | None = None
    installation_manifest_path: str | None = None
    install_root: str | None = None
    share_bundle_file: str | None = None
    share_bundle_sha256: str | None = None

    instructions = str(req.assistant_instructions or req.description).strip()
    if not instructions:
        raise InvalidInputError("assistant_instructions or description is required.")
    conversation_starters = _normalize_sequence(req.conversation_starters)
    allowed_tools = _normalize_permissions(req.allowed_tools, field_name="allowed_tools")
    allowed_apps = _normalize_permissions(req.allowed_apps, field_name="allowed_apps")
    allowed_apis = _normalize_permissions(req.allowed_apis, field_name="allowed_apis")
    knowledge_files, knowledge_created = _copy_knowledge_files(
        req.knowledge_files,
        package_dir=package_dir,
        overwrite=req.overwrite,
    )
    files_created.extend(knowledge_created)

    init_py = (
        "from __future__ import annotations\n\n"
        "from .plugin import Plugin, create_plugin, get_plugin\n\n"
        '__all__ = ["Plugin", "create_plugin", "get_plugin"]\n'
    )

    plugin_py = _build_plugin_code(
        name,
        req.description,
        req.plugin_version,
        instructions=instructions,
        conversation_starters=conversation_starters,
        knowledge_files=knowledge_files,
        allowed_tools=allowed_tools,
        allowed_apps=allowed_apps,
        allowed_apis=allowed_apis,
    )

    skill_intents = _normalize_sequence(req.skill_intents)
    skill_tools = _normalize_sequence(req.skill_tools)
    skill_examples = _normalize_sequence(req.skill_examples)
    skill_name = _validate_skill_name(req.skill_name or name)
    readme = f"# {name}\n\n{req.description}\n\nUsed with: `{skill_name}` skill.\n"

    pyproject = (
        "[build-system]\n"
        'requires = ["setuptools>=61.0"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        f'name = "{_toml_escape(name)}"\n'
        f'version = "{_py_escape(req.plugin_version)}"\n'
        f'description = "{_toml_escape(req.description)}"\n'
    )
    if req.author.strip():
        pyproject += f'authors = [{{name = "{_toml_escape(req.author.strip())}"}}]\n'

    readme = f"# {name}\n\n{req.description}\n"

    def _track(created: bool, p: Path, warn: str) -> None:
        if created:
            files_created.append(str(p))
        else:
            warnings.append(warn)

    _track(
        _write_file(package_dir / "__init__.py", init_py, overwrite=req.overwrite),
        package_dir / "__init__.py",
        "__init__.py existed; skipped.",
    )
    _track(
        _write_file(package_dir / "plugin.py", plugin_py, overwrite=req.overwrite),
        package_dir / "plugin.py",
        "plugin.py existed; skipped.",
    )
    _track(
        _write_file(package_dir / "pyproject.toml", pyproject, overwrite=req.overwrite),
        package_dir / "pyproject.toml",
        "pyproject.toml existed; skipped.",
    )
    _track(
        _write_file(package_dir / "README.md", readme, overwrite=req.overwrite),
        package_dir / "README.md",
        "README.md existed; skipped.",
    )

    if req.create_skill:
        skill_root = _resolve_skill_root(dest, req.skill_root)
        try:
            skill_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ExternalFailureError(
                "Unable to create skill root directory.",
                details={"skill_root": str(skill_root), "error": str(e)},
            ) from e

        # Keep skills discoverable by the runtime scanner in common paths.
        skill_dir = skill_root / skill_name
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ExternalFailureError(
                "Unable to create skill directory.",
                details={"skill_dir": str(skill_dir), "error": str(e)},
            ) from e

        skill_content = _build_skill_md(
            plugin_name=skill_name,
            description=req.description,
            author=req.author,
            intents=skill_intents,
            tools=skill_tools,
            examples=skill_examples,
        )

        if _write_file(skill_dir / "SKILL.md", skill_content, overwrite=req.overwrite):
            files_created.append(str(skill_dir / "SKILL.md"))
            skill_file = skill_dir / "SKILL.md"
        else:
            warnings.append("SKILL.md existed; skipped.")

    if req.create_manifest:
        try:
            simple_manifest, rich_manifest = _build_plugin_manifest(
                plugin_name=name,
                version=req.plugin_version,
                description=req.description,
                author=(req.author or "").strip(),
                instructions=instructions,
                conversation_starters=conversation_starters,
                knowledge_files=knowledge_files,
                allowed_tools=allowed_tools,
                allowed_apps=allowed_apps,
                allowed_apis=allowed_apis,
            )
            plugin_manifest = package_dir / "plugin.json"
            if _write_file(plugin_manifest, _to_json(simple_manifest), overwrite=req.overwrite):
                files_created.append(str(plugin_manifest))
                manifest_file = plugin_manifest
            else:
                warnings.append("plugin.json existed; skipped.")

            rich_manifest_path = package_dir / "manifest.json"
            if _write_file(rich_manifest_path, _to_json(rich_manifest), overwrite=req.overwrite):
                files_created.append(str(rich_manifest_path))
            else:
                warnings.append("manifest.json existed; skipped.")

            thomas_manifest = package_dir / "thomas_plugin.json"
            if _write_file(thomas_manifest, _to_json(simple_manifest), overwrite=req.overwrite):
                files_created.append(str(thomas_manifest))
            else:
                warnings.append("thomas_plugin.json existed; skipped.")
        except PluginBootstrapError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExternalFailureError(
                "Unable to write plugin manifest files.",
                details={"plugin_dir": str(package_dir), "reason": type(exc).__name__},
            ) from exc

    plugin_py_path = package_dir / "plugin.py"
    if req.validate:
        for path in (
            package_dir / "plugin.json",
            package_dir / "manifest.json",
            plugin_py_path,
            package_dir / "thomas_plugin.json",
        ):
            try:
                if path.name.endswith(".json") and path.exists():
                    _validate_json_file(path)
                    if path.name == "manifest.json":
                        validate_plugin_manifest(json.loads(path.read_text(encoding="utf-8")))
                elif path.suffix == ".py":
                    _validate_python_source(path)
            except PluginBootstrapError as exc:
                validation_ok = False
                validation_errors.append(f"{path.name}: {exc.message}")
            except PluginManifestSchemaError as exc:
                validation_ok = False
                message = str(getattr(exc, "message", "") or str(exc) or type(exc).__name__)
                validation_errors.append(f"{path.name}: {message}")

    if req.create_share_bundle:
        bundle_path = req.share_bundle_path or (dest / f"{name}-{req.plugin_version}.thomas-plugin.zip")
        share_bundle_sha256 = _create_share_bundle(package_dir, bundle_path, overwrite=req.overwrite)
        share_bundle_file = str(bundle_path.resolve())

    if req.install_after_bootstrap and req.validate and not validation_ok:
        raise InstallFailedError(
            "Validation failed; cannot install generated plugin.",
            details={"validation_errors": validation_errors, "plugin_dir": str(package_dir)},
        )

    if req.install_after_bootstrap:
        try:
            from thomas.plugins.p102_plugin_install_from_local_path import (
                PluginInstallFromLocalPathError,
                PluginInstallFromLocalPathRequest,
                install_plugin_from_local_path,
            )
        except Exception as exc:  # noqa: BLE001
            raise ExternalFailureError(
                "Unable to load plugin installer module.",
                details={"reason": type(exc).__name__},
            ) from exc

        install_root = str(req.install_root) if req.install_root is not None else None
        try:
            install_result = install_plugin_from_local_path(
                PluginInstallFromLocalPathRequest(
                    source_path=package_dir,
                    install_root=req.install_root,
                    overwrite=req.install_overwrite,
                )
            )
            installed_plugin = install_result.plugin_name
            installed_path = str(install_result.installed_path)
            installation_manifest_path = str(install_result.manifest_path)
            install_root = str(install_result.installed_path.parent)
        except PluginInstallFromLocalPathError as exc:
            raise InstallFailedError(
                "Failed to install generated plugin.",
                details={
                    "plugin_dir": str(package_dir),
                    "install_root": install_root,
                    "reason": exc.code,
                    "plugin_install_error": exc.message,
                    "details": exc.details,
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise InstallFailedError(
                "Failed to install generated plugin.",
                details={
                    "plugin_dir": str(package_dir),
                    "install_root": install_root,
                    "reason": type(exc).__name__,
                    "message": str(exc),
                },
            ) from exc

    return PluginBootstrapResult(
        plugin_name=name,
        package_dir=str(package_dir),
        manifest_file=str(manifest_file) if manifest_file else None,
        manifest_dir=str(package_dir) if req.create_manifest else None,
        installed_plugin=installed_plugin,
        installed_path=installed_path,
        installation_result_path=installation_manifest_path,
        install_root=install_root,
        share_bundle_file=share_bundle_file,
        share_bundle_sha256=share_bundle_sha256,
        knowledge_files=knowledge_files,
        validation_ok=validation_ok,
        validation_errors=validation_errors,
        skill_file=str(skill_file) if skill_file else None,
        skill_dir=str(skill_dir) if req.create_skill else None,
        files_created=files_created,
        warnings=warnings,
    )
