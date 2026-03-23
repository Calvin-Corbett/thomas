"""Helper functions for local project analysis and metadata."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_CONFIG

log = logging.getLogger(__name__)

_REGISTRY_VERSION = 2
_REGISTRY_RELATIVE_PATH = Path(".thomas") / "linked_projects.json"
_MAX_PROJECTS = 250
_BOARD_COLUMNS = 5
_BOARD_TILE_WIDTH = 148
_BOARD_TILE_HEIGHT = 156
_BOARD_PADDING_LEFT = 32
_BOARD_PADDING_TOP = 36
_BOARD_GAP_X = 22
_BOARD_GAP_Y = 24


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify(value: str) -> str:
    out = []
    last_dash = False
    for char in _safe_text(value).lower():
        if char.isalnum():
            out.append(char)
            last_dash = False
            continue
        if not last_dash:
            out.append("-")
            last_dash = True
    return "".join(out).strip("-")


def _project_root_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def _project_id_for_path(path: Path) -> str:
    root_key = _project_root_key(path)
    digest = hashlib.sha1(root_key.encode("utf-8")).hexdigest()[:10]
    slug = _slugify(path.name) or "project"
    return f"local-{slug}-{digest}"


def _accent_for_id(project_id: str) -> str:
    palette = ["#ff7a59", "#2d8cff", "#0f9d7a", "#f4a300", "#7b61ff", "#d24d57"]
    if not project_id:
        return palette[0]
    digest = hashlib.sha1(project_id.encode("utf-8")).hexdigest()
    return palette[int(digest[:2], 16) % len(palette)]


def _emoji_for_project(kind: str, framework: str, root_name: str) -> str:
    lower_framework = _safe_text(framework).lower()
    lower_kind = _safe_text(kind).lower()
    name = _safe_text(root_name).lower()
    if "game" in name or "flappy" in name or "pong" in name:
        return "🎮"
    if "electron" in lower_framework or "tauri" in lower_framework:
        return "🖥️"
    if lower_kind == "static_site":
        return "🪄"
    if lower_kind == "python_project" or "python" in lower_framework:
        return "🐍"
    if "next" in lower_framework or "react" in lower_framework or "vite" in lower_framework:
        return "⚛️"
    if "svelte" in lower_framework:
        return "🔥"
    if "vue" in lower_framework:
        return "💚"
    if "astro" in lower_framework:
        return "🚀"
    if "remix" in lower_framework:
        return "🤖"
    if lower_kind == "hugo":
        return "🦅"
    if lower_kind == "ruby_on_rails":
        return "💎"
    if lower_kind in {"django_project", "fastapi_project"}:
        return "🐍"
    if lower_kind == "rust_project":
        return "🦀"
    if lower_kind == "go_project":
        return "🐹"
    return "📦"


def _default_board_position(index: int) -> dict[str, int]:
    col = index % _BOARD_COLUMNS
    row = index // _BOARD_COLUMNS
    x = _BOARD_PADDING_LEFT + col * (_BOARD_TILE_WIDTH + _BOARD_GAP_X)
    y = _BOARD_PADDING_TOP + row * (_BOARD_TILE_HEIGHT + _BOARD_GAP_Y)
    return {"x": x, "y": y}


def _normalize_board_position(raw: Any, *, index: int = 0) -> dict[str, int]:
    try:
        x = _safe_int(raw.get("x")) if isinstance(raw, dict) else 0
        y = _safe_int(raw.get("y")) if isinstance(raw, dict) else 0
        if x >= 0 and y >= 0:
            return {"x": x, "y": y}
    except Exception:  # pragma: no cover
        pass
    return _default_board_position(index)


def _registry_path(app: web.Application) -> Path:
    cfg: AppConfig = app.get(APP_CONFIG)
    return cfg.home_dir / _REGISTRY_RELATIVE_PATH


def _sort_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(project: dict[str, Any]) -> tuple[int, str]:
        updated = _safe_text(project.get("updated_at"))
        name = _safe_text(project.get("name")).lower()
        return (-len(updated), name)

    return sorted(projects, key=sort_key)


def _read_registry(app: web.Application) -> list[dict[str, Any]]:
    path = _registry_path(app)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        version = data.get("version", 1)
        projects = data.get("projects", [])
        if not isinstance(projects, list):
            return []
        return projects
    except Exception:  # pragma: no cover
        return []


def _write_registry(app: web.Application, projects: list[dict[str, Any]]) -> None:
    path = _registry_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"version": _REGISTRY_VERSION, "projects": projects}, f)


def _resolve_project_root(path_raw: Any) -> Path:
    if isinstance(path_raw, str) and path_raw.strip():
        expanded = Path(path_raw).expanduser()
        if expanded.exists() and expanded.is_dir():
            return expanded.resolve()
    raise web.HTTPBadRequest(text="path must be a valid, existing directory")


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _count_files(root: Path, *, limit: int = 1600) -> int:
    count = 0
    try:
        for _ in root.rglob("*"):
            count += 1
            if count >= limit:
                return limit
    except (OSError, PermissionError):
        pass
    return count


def _top_level_entries(root: Path, *, limit: int = 8) -> list[str]:
    names = []
    try:
        for entry in sorted(root.iterdir()):
            if entry.name.startswith("."):
                continue
            names.append(entry.name)
            if len(names) >= limit:
                break
    except (OSError, PermissionError):
        pass
    return names


def _read_readme_excerpt(root: Path) -> str:
    readme_files = [root / "README.md", root / "README.txt", root / "readme.md", root / "readme.txt"]
    for readme_path in readme_files:
        if readme_path.exists():
            try:
                with open(readme_path, encoding="utf-8") as f:
                    lines = [line for line in f.readlines() if _safe_text(line)]
                    return "\n".join(lines[:8])
            except (OSError, UnicodeDecodeError):
                pass
    return ""


def _merged_dependencies(package_json: dict[str, Any]) -> set[str]:
    deps = set()
    for key in ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]:
        if isinstance(package_json.get(key), dict):
            deps.update(package_json[key].keys())
    return deps


def _detect_package_manager(root: Path, package_json: dict[str, Any]) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "bun.lockb").exists():
        return "bun"
    return "npm"


def _detect_framework(root: Path, package_json: dict[str, Any]) -> str:
    deps = _merged_dependencies(package_json)
    if "next" in deps:
        return "next"
    if "react" in deps:
        if "remix" in deps:
            return "remix"
        if "gatsby" in deps:
            return "gatsby"
        return "react"
    if "vue" in deps:
        if "nuxt" in deps:
            return "nuxt"
        return "vue"
    if "svelte" in deps:
        if "sveltekit" in deps:
            return "sveltekit"
        return "svelte"
    if "astro" in deps:
        return "astro"
    if "solid-js" in deps:
        return "solidjs"
    if "angular" in deps or "@angular/core" in deps:
        return "angular"
    if "ember-source" in deps or "ember-cli" in deps:
        return "ember"
    if "jquery" in deps:
        return "jquery"
    if "preact" in deps:
        return "preact"
    if "express" in deps or "@nestjs/core" in deps or "fastify" in deps:
        return "node_backend"
    return ""


def _detect_entry_html(root: Path) -> Path | None:
    candidates = [root / "index.html", root / "public" / "index.html", root / "src" / "index.html"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _pick_launch_script(package_json: dict[str, Any], framework: str) -> str:
    scripts = package_json.get("scripts", {})
    if not isinstance(scripts, dict):
        return ""
    preferred = ["dev", "start", "serve"]
    if "astro" in framework.lower():
        preferred = ["dev", "start"]
    for script_name in preferred:
        if script_name in scripts:
            return script_name
    for script_name in scripts.keys():
        if "dev" in script_name.lower() or "start" in script_name.lower():
            return script_name
    return ""


def _command_for_script(package_manager: str, script_name: str) -> list[str]:
    if script_name:
        return [package_manager, "run", script_name] if package_manager != "npm" else ["npm", "run", script_name]
    if package_manager == "pnpm":
        return ["pnpm", "dev"]
    if package_manager == "yarn":
        return ["yarn", "dev"]
    if package_manager == "bun":
        return ["bun", "dev"]
    return ["npm", "run", "dev"]


def _command_display(command: list[str]) -> str:
    return " ".join(_safe_text(part) for part in command if _safe_text(part))


def _build_launch_profile(root: Path) -> dict[str, Any]:
    package_json = _read_json_file(root / "package.json")
    if not package_json:
        return {"available": False, "reason": "no package.json"}
    framework = _detect_framework(root, package_json)
    package_manager = _detect_package_manager(root, package_json)
    script_name = _pick_launch_script(package_json, framework)
    if not script_name:
        return {"available": False, "reason": "no suitable launch script found"}
    command = _command_for_script(package_manager, script_name)
    entry_html = _detect_entry_html(root)
    return {
        "available": True,
        "framework": framework,
        "package_manager": package_manager,
        "script": script_name,
        "command": command,
        "command_display": _command_display(command),
        "target": str(entry_html) if entry_html else "",
    }


def _detect_project_type(kind: str, framework: str, root_name: str) -> str:
    lower_kind = _safe_text(kind).lower()
    if lower_kind:
        return lower_kind
    lower_framework = _safe_text(framework).lower()
    if "python" in lower_framework:
        return "python_project"
    if "node" in lower_framework or "npm" in lower_framework or "react" in lower_framework:
        return "javascript_project"
    if "rails" in lower_framework:
        return "ruby_on_rails"
    if "django" in lower_framework:
        return "django_project"
    if "fastapi" in lower_framework:
        return "fastapi_project"
    if "rust" in lower_framework:
        return "rust_project"
    if "go" in lower_framework:
        return "go_project"
    return "software_project"


def _build_prepare_profile(root: Path, profile: dict[str, Any]) -> dict[str, Any]:
    package_json = _read_json_file(root / "package.json")
    if not package_json:
        return {"available": False, "reason": "no package.json"}
    scripts = package_json.get("scripts", {})
    if not isinstance(scripts, dict):
        return {"available": False, "reason": "no scripts in package.json"}
    candidates = []
    for script_name in ["install", "setup", "prepare"]:
        if script_name in scripts:
            package_manager = profile.get("package_manager", "npm")
            candidates.append(
                {
                    "name": script_name,
                    "command": [package_manager, "run", script_name],
                    "command_display": _command_display([package_manager, "run", script_name]),
                }
            )
    if not candidates:
        package_manager = profile.get("package_manager", "npm")
        candidates.append(
            {
                "name": "install",
                "command": [package_manager, "install"],
                "command_display": _command_display([package_manager, "install"]),
            }
        )
    return {"available": bool(candidates), "candidates": candidates}


def _build_test_candidates(root: Path, profile: dict[str, Any]) -> list[dict[str, Any]]:
    package_json = _read_json_file(root / "package.json")
    if not package_json:
        return []
    scripts = package_json.get("scripts", {})
    if not isinstance(scripts, dict):
        return []
    candidates = []
    for script_name in ["test", "test:unit", "test:integration"]:
        if script_name in scripts:
            package_manager = profile.get("package_manager", "npm")
            candidates.append(
                {
                    "name": script_name,
                    "command": [package_manager, "run", script_name],
                    "command_display": _command_display([package_manager, "run", script_name]),
                }
            )
    return candidates


def _build_scope_summary(root: Path, profile: dict[str, Any], project_type: str) -> str:
    file_count = _count_files(root)
    top_level = _top_level_entries(root)
    summary = f"{project_type.replace('_', ' ').title()} with {file_count} files"
    if top_level:
        summary += f", includes: {', '.join(top_level[:3])}"
    return summary


def _build_readiness(profile: dict[str, Any], prepare: dict[str, Any]) -> dict[str, Any]:
    launch_available = profile.get("available", False)
    install_available = prepare.get("available", False)
    readiness_score = 0
    status = "unknown"
    if launch_available:
        readiness_score += 50
    if install_available:
        readiness_score += 30
    if readiness_score >= 80:
        status = "ready"
    elif readiness_score >= 50:
        status = "likely_ready"
    elif readiness_score >= 20:
        status = "partially_ready"
    else:
        status = "unknown"
    return {
        "status": status,
        "score": readiness_score,
        "has_launch": launch_available,
        "has_prepare": install_available,
        "has_readme": bool(_read_readme_excerpt(root)),
    }


def _build_findings_preview(
    root: Path,
    profile: dict[str, Any],
    prepare: dict[str, Any],
    project_type: str,
) -> dict[str, Any]:
    findings = []
    readme = _read_readme_excerpt(root)
    if readme:
        findings.append({"category": "readme", "excerpt": readme[:500]})
    launch_cmd = profile.get("command_display", "")
    if launch_cmd:
        findings.append({"category": "launch_command", "excerpt": launch_cmd})
    test_candidates = _build_test_candidates(root, profile)
    if test_candidates:
        findings.append({"category": "testing", "excerpt": f"{len(test_candidates)} test suite(s) found"})
    return {"findings": findings, "has_findings": bool(findings)}


def _build_launch_candidates(
    root: Path,
    profile: dict[str, Any],
    project_type: str,
) -> list[dict[str, Any]]:
    candidates = []
    if profile.get("available", False):
        cmd = profile.get("command", [])
        candidates.append(
            {
                "name": profile.get("script", "dev"),
                "framework": profile.get("framework", ""),
                "command": cmd,
                "command_display": profile.get("command_display", ""),
                "target": profile.get("target", ""),
            }
        )
    if "python" in project_type.lower():
        candidates.append(
            {
                "name": "python",
                "framework": "python",
                "command": ["python", "-m", "http.server", "8000"],
                "command_display": "python -m http.server 8000",
                "target": "",
            }
        )
    return candidates


def _build_actions(
    project_type: str,
    profile: dict[str, Any],
    prepare: dict[str, Any],
    test_candidates: list[dict[str, Any]],
) -> list[str]:
    actions = []
    if profile.get("available", False):
        actions.append("launch")
    if prepare.get("available", False):
        actions.append("prepare")
    if test_candidates:
        actions.append("test")
    actions.extend(["open_entry", "open_folder"])
    return actions


def _build_project_dossier(
    root: Path,
    *,
    existing: dict[str, Any] | None = None,
    name: str | None = None,
    touch: bool = False,
    index: int = 0,
    import_method: str = "path",
) -> dict[str, Any]:
    existing = existing or {}
    project_id = existing.get("id") or _project_id_for_path(root)
    display_name = name or existing.get("name") or root.name
    package_json = _read_json_file(root / "package.json")
    framework = _detect_framework(root, package_json) if package_json else ""
    project_type = _detect_project_type(existing.get("kind", ""), framework, root.name)
    kind = project_type
    launch_profile = _build_launch_profile(root)
    prepare_profile = _build_prepare_profile(root, launch_profile)
    test_candidates = _build_test_candidates(root, launch_profile)
    readiness = _build_readiness(launch_profile, prepare_profile)
    findings = _build_findings_preview(root, launch_profile, prepare_profile, kind)
    launch_candidates = _build_launch_candidates(root, launch_profile, kind)
    actions = _build_actions(kind, launch_profile, prepare_profile, test_candidates)
    scope_summary = _build_scope_summary(root, launch_profile, kind)
    board_position = existing.get("board_position") or _normalize_board_position({}, index=index)
    now = _utc_now_iso()
    entry_path = ""
    if launch_profile.get("available", False):
        target = launch_profile.get("target", "")
        if target:
            entry_path = str(Path(target).relative_to(root)) if Path(target).is_relative_to(root) else target
    dossier = {
        "id": project_id,
        "name": display_name,
        "root_path": str(root),
        "import_method": import_method,
        "kind": kind,
        "emoji": _emoji_for_project(kind, framework, root.name),
        "accent_color": _accent_for_id(project_id),
        "framework": framework,
        "created_at": existing.get("created_at") or (now if touch else ""),
        "updated_at": now if touch else existing.get("updated_at", ""),
        "launch_count": _safe_int(existing.get("launch_count"), 0),
        "last_launched_at": existing.get("last_launched_at", ""),
        "last_prepared_at": existing.get("last_prepared_at", ""),
        "board_position": board_position,
        "entry_path": entry_path,
        "scope_summary": scope_summary,
        "profile": {
            "launch": launch_profile,
            "prepare": prepare_profile,
            "test_candidates": test_candidates,
            "readiness": readiness,
        },
        "findings": findings.get("findings", []),
        "launch_candidates": launch_candidates,
        "actions": actions,
    }
    return dossier


def _refresh_projects(app: web.Application) -> list[dict[str, Any]]:
    projects = _read_registry(app)
    missing_roots = []
    for project in projects:
        root_path = _safe_text(project.get("root_path"))
        if not root_path or not Path(root_path).exists():
            missing_roots.append(project.get("id"))
    projects = [p for p in projects if p.get("id") not in missing_roots]
    for index, project in enumerate(projects):
        try:
            root = Path(project.get("root_path"))
            updated = _build_project_dossier(root, existing=project, touch=False, index=index)
            projects[index] = updated
        except Exception:  # pragma: no cover
            pass
    return projects


def _find_project(projects: list[dict[str, Any]], project_id: str) -> tuple[int, dict[str, Any]]:
    for index, project in enumerate(projects):
        if project.get("id") == project_id:
            return index, project
    raise web.HTTPNotFound(text=f"project not found: {project_id}")


def _open_path(target: Path) -> dict[str, Any]:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=True)
        elif sys.platform == "win32":
            os.startfile(str(target))
        else:
            subprocess.run(["xdg-open", str(target)], check=True)
        return {"opened": True}
    except (subprocess.CalledProcessError, OSError) as exc:  # pragma: no cover
        return {"opened": False, "error": str(exc)}


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        if sys.platform == "win32":
            subprocess.Popen(command, cwd=str(cwd), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(command, cwd=str(cwd))
        return {"started": True}
    except (subprocess.CalledProcessError, OSError) as exc:  # pragma: no cover
        return {"started": False, "error": str(exc)}


def _perform_project_action(project: dict[str, Any], requested_action: str) -> tuple[str, dict[str, Any]]:
    root = Path(_safe_text(project.get("root_path")))
    if not root.exists():
        raise web.HTTPConflict(text="project root no longer exists")
    launch = project.get("profile", {}).get("launch", {})
    prepare = project.get("profile", {}).get("prepare", {})
    test_candidates = project.get("profile", {}).get("test_candidates", [])
    action = _safe_text(requested_action).lower()
    if action == "prepare":
        if prepare.get("available", False):
            candidates = prepare.get("candidates", [])
            command = candidates[0].get("command") if candidates and isinstance(candidates[0], dict) else []
            if not command:
                raise web.HTTPConflict(text="Thomas does not have a preparation command for this project yet")
            return action, _run_command([_safe_text(part) for part in command if _safe_text(part)], root)
    if action == "launch":
        command = launch.get("command") if isinstance(launch.get("command"), list) else []
        return action, _run_command([_safe_text(part) for part in command if _safe_text(part)], root)
    if action == "test":
        candidate = test_candidates[0] if test_candidates else {}
        command = (
            candidate.get("command")
            if isinstance(candidate, dict) and isinstance(candidate.get("command"), list)
            else []
        )
        if not command:
            raise web.HTTPConflict(text="Thomas did not find a test command for this project yet")
        return action, _run_command([_safe_text(part) for part in command if _safe_text(part)], root)
    if action == "open_entry":
        target = Path(_safe_text(project.get("entry_path")) or _safe_text(launch.get("target")))
        if not target.exists():
            raise web.HTTPConflict(text="linked entry file is no longer available")
        return action, _open_path(target)
    if action == "open_folder":
        return action, _open_path(root)
    raise web.HTTPBadRequest(text=f"unsupported project action: {action}")


def _pick_folder_via_dialog() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - platform dependent
        raise web.HTTPConflict(text="local folder picker is not available on this machine") from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        selected = filedialog.askdirectory(title="Choose a project folder for My Stuff", mustexist=True)
    except Exception as exc:  # pragma: no cover - platform dependent
        raise web.HTTPConflict(text=f"could not open the local folder picker: {exc}") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    return _safe_text(selected)
