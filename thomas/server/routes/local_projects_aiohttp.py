"""Local project registry and launcher routes for Thomas command-center shortcuts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_CONFIG

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

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
        return "🚀"
    if lower_kind == "node_app":
        return "📦"
    return "🧩"


def _default_board_position(index: int) -> dict[str, int]:
    col = max(0, index) % _BOARD_COLUMNS
    row = max(0, index) // _BOARD_COLUMNS
    return {
        "x": _BOARD_PADDING_LEFT + col * (_BOARD_TILE_WIDTH + _BOARD_GAP_X),
        "y": _BOARD_PADDING_TOP + row * (_BOARD_TILE_HEIGHT + _BOARD_GAP_Y),
    }


def _normalize_board_position(raw: Any, *, index: int = 0) -> dict[str, int]:
    if isinstance(raw, dict):
        x = _safe_int(raw.get("x"), -1)
        y = _safe_int(raw.get("y"), -1)
        if x >= 0 and y >= 0:
            return {"x": x, "y": y}
    return _default_board_position(index)


def _registry_path(app: web.Application) -> Path:
    config: AppConfig = app[APP_CONFIG]
    return Path(config.memory.root_path) / _REGISTRY_RELATIVE_PATH


def _sort_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        projects,
        key=lambda row: (
            _safe_text(row.get("updated_at") or row.get("created_at")),
            _safe_text(row.get("name")),
            _safe_text(row.get("id")),
        ),
        reverse=True,
    )


def _read_registry(app: web.Application) -> list[dict[str, Any]]:
    path = _registry_path(app)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("Local project registry unreadable at %s: %s", path, exc)
        return []
    rows = payload.get("projects") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        root_path = _safe_text(row.get("root_path"))
        if not root_path:
            continue
        out.append(dict(row))
    return _sort_projects(out)


def _write_registry(app: web.Application, projects: list[dict[str, Any]]) -> None:
    path = _registry_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _REGISTRY_VERSION,
        "updated_at": _utc_now_iso(),
        "projects": _sort_projects(projects)[:_MAX_PROJECTS],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_project_root(path_raw: Any) -> Path:
    raw = _safe_text(path_raw).strip('"').strip("'")
    if not raw:
        raise web.HTTPBadRequest(text="path is required")
    try:
        candidate = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise web.HTTPBadRequest(text=f"invalid path: {exc}") from exc
    if not candidate.exists():
        raise web.HTTPBadRequest(text="folder does not exist")
    if not candidate.is_dir():
        raise web.HTTPBadRequest(text="path must point to a folder")
    if candidate == Path(candidate.anchor):
        raise web.HTTPBadRequest(text="path must point to a project folder, not a drive root")
    return candidate


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _count_files(root: Path, *, limit: int = 1600) -> int:
    total = 0
    try:
        for total, _ in enumerate(root.rglob("*"), start=1):
            if total >= limit:
                return total
    except OSError:
        return total
    return total


def _top_level_entries(root: Path, *, limit: int = 8) -> list[str]:
    entries: list[str] = []
    try:
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            entries.append(child.name)
            if len(entries) >= limit:
                break
    except OSError:
        return []
    return entries


def _read_readme_excerpt(root: Path) -> str:
    for name in ("README.md", "README.txt", "readme.md", "Readme.md"):
        path = root / name
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [line.strip(" #\t") for line in content.splitlines() if line.strip()]
        for line in lines:
            if len(line) >= 18:
                return line[:280]
    return ""


def _merged_dependencies(package_json: dict[str, Any]) -> set[str]:
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        raw = package_json.get(key)
        if not isinstance(raw, dict):
            continue
        for dep_name in raw:
            if isinstance(dep_name, str) and dep_name.strip():
                deps.add(dep_name.strip().lower())
    return deps


def _detect_package_manager(root: Path, package_json: dict[str, Any]) -> str:
    package_manager = _safe_text(package_json.get("packageManager")).lower()
    if package_manager.startswith("pnpm@"):
        return "pnpm"
    if package_manager.startswith("yarn@"):
        return "yarn"
    if package_manager.startswith("npm@"):
        return "npm"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _detect_framework(root: Path, package_json: dict[str, Any]) -> str:
    dependencies = _merged_dependencies(package_json)
    scripts = package_json.get("scripts")
    script_blob = ""
    if isinstance(scripts, dict):
        script_blob = " ".join(_safe_text(value).lower() for value in scripts.values())
    if "@tauri-apps/api" in dependencies or "@tauri-apps/cli" in dependencies or "tauri" in script_blob:
        return "Tauri"
    if "electron" in dependencies or "electron-builder" in dependencies or "electron" in script_blob:
        return "Electron"
    if "next" in dependencies:
        return "Next.js"
    if "vite" in dependencies:
        return "Vite"
    if "react" in dependencies:
        return "React"
    if "vue" in dependencies:
        return "Vue"
    if "svelte" in dependencies or "@sveltejs/kit" in dependencies:
        return "Svelte"
    if "nuxt" in dependencies:
        return "Nuxt"
    if package_json:
        return "Node App"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return "Python"
    if _detect_entry_html(root) is not None:
        return "Static HTML"
    return "Folder"


def _detect_entry_html(root: Path) -> Path | None:
    candidates = [
        root / "index.html",
        root / "public" / "index.html",
        root / "dist" / "index.html",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _pick_launch_script(package_json: dict[str, Any], framework: str) -> str:
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return ""
    script_names = [name for name, value in scripts.items() if isinstance(name, str) and _safe_text(value)]
    if not script_names:
        return ""
    script_blob = " ".join(_safe_text(value).lower() for value in scripts.values())
    if framework in {"Electron", "Tauri"}:
        for candidate in ("dev", "start", "desktop", "tauri", "electron"):
            if candidate in scripts:
                return candidate
    if "electron" in script_blob or "tauri" in script_blob:
        for candidate in ("dev", "start", "desktop", "tauri", "electron"):
            if candidate in scripts:
                return candidate
    for candidate in ("dev", "start", "serve"):
        if candidate in scripts:
            return candidate
    return script_names[0] if len(script_names) == 1 else ""


def _command_for_script(package_manager: str, script_name: str) -> list[str]:
    if package_manager == "yarn":
        return ["yarn", script_name]
    if package_manager == "pnpm":
        return ["pnpm", "run", script_name]
    if script_name == "start":
        return ["npm", "start"]
    return ["npm", "run", script_name]


def _command_display(command: list[str]) -> str:
    return " ".join(part for part in command if _safe_text(part))


def _build_launch_profile(root: Path) -> dict[str, Any]:
    package_json = _read_json_file(root / "package.json")
    framework = _detect_framework(root, package_json)
    entry_html = _detect_entry_html(root)
    package_manager = _detect_package_manager(root, package_json) if package_json else ""
    launch_script = _pick_launch_script(package_json, framework) if package_json else ""

    launch: dict[str, Any] = {
        "kind": "none",
        "label": "Open Folder",
        "command": [],
        "command_display": "",
        "target": "",
        "executable_available": False,
    }
    summary = "Linked workspace shortcut inside Thomas."
    kind = "folder"

    python_entry = None
    for candidate in ("main.py", "app.py", "run.py", "manage.py"):
        path_entry = root / candidate
        if path_entry.exists() and path_entry.is_file():
            python_entry = path_entry
            break

    if package_json:
        kind = "node_app"
        summary = "Thomas can inspect and stage this app directly from My Stuff."
        if launch_script:
            command = _command_for_script(package_manager, launch_script)
            executable = command[0] if command else ""
            launch = {
                "kind": "command",
                "label": "Launch Desktop App" if framework in {"Electron", "Tauri"} else "Launch App",
                "command": command,
                "command_display": _command_display(command),
                "target": str(root),
                "executable_available": bool(executable and shutil.which(executable)),
            }
            if launch_script == "dev" and framework not in {"Electron", "Tauri"}:
                launch["label"] = "Launch Dev App"
            elif launch_script == "serve":
                launch["label"] = "Serve App"
            elif launch_script not in {"dev", "start", "serve"}:
                launch["label"] = f"Run {launch_script}"
            summary = (
                f"Thomas can run `{launch['command_display']}` in this project folder."
                if launch["command_display"]
                else summary
            )
        elif entry_html is not None:
            kind = "static_site"
            launch = {
                "kind": "file",
                "label": "Open App",
                "command": [],
                "command_display": "",
                "target": str(entry_html),
                "executable_available": True,
            }
            summary = "Static HTML app that Thomas can open directly."
    elif entry_html is not None:
        kind = "static_site"
        framework = "Static HTML"
        launch = {
            "kind": "file",
            "label": "Open App",
            "command": [],
            "command_display": "",
            "target": str(entry_html),
            "executable_available": True,
        }
        summary = "Static HTML app that Thomas can open directly."
    elif framework == "Python":
        kind = "python_project"
        summary = "Python project staged inside Thomas. Review the project read, then prepare or launch it from the detail page."
        if python_entry is not None:
            command = [sys.executable, python_entry.name]
            launch = {
                "kind": "command",
                "label": "Launch Python App",
                "command": command,
                "command_display": _command_display(command),
                "target": str(root),
                "executable_available": bool(shutil.which(sys.executable) or Path(sys.executable).exists()),
            }
            summary = f"Thomas can try `{launch['command_display']}` from this project folder."

    return {
        "kind": kind,
        "framework": framework,
        "package_manager": package_manager,
        "entry_path": str(entry_html) if entry_html else "",
        "summary": summary,
        "launch": launch,
    }


def _detect_project_type(kind: str, framework: str, root_name: str) -> str:
    lower_framework = _safe_text(framework).lower()
    name = _safe_text(root_name).lower()
    if "game" in name or "flappy" in name or "pong" in name:
        return "game"
    if lower_framework in {"electron", "tauri"}:
        return "desktop_app"
    if lower_framework in {"next.js", "react", "vite", "vue", "svelte", "nuxt", "static html"}:
        return "web_app"
    if kind == "python_project":
        return "python_app"
    if kind == "node_app":
        return "node_app"
    return "workspace"


def _build_prepare_profile(root: Path, profile: dict[str, Any]) -> dict[str, Any]:
    kind = _safe_text(profile.get("kind")).lower()
    framework = _safe_text(profile.get("framework"))
    package_manager = _safe_text(profile.get("package_manager")).lower()

    if kind == "node_app":
        node_modules = root / "node_modules"
        if node_modules.exists() and node_modules.is_dir():
            return {
                "needed": False,
                "label": "Project prepared",
                "command": [],
                "command_display": "",
                "reason": "Dependencies already look installed.",
                "executable_available": True,
            }
        executable = package_manager or "npm"
        command = [executable, "install"] if executable != "yarn" else ["yarn", "install"]
        return {
            "needed": True,
            "label": "Prepare Project",
            "command": command,
            "command_display": _command_display(command),
            "reason": f"{framework or 'Node'} dependencies are not installed yet.",
            "executable_available": bool(shutil.which(executable)),
        }

    if kind == "python_project":
        has_env = any((root / name).exists() for name in (".venv", "venv", "env"))
        if has_env:
            return {
                "needed": False,
                "label": "Project prepared",
                "command": [],
                "command_display": "",
                "reason": "A local Python environment already exists.",
                "executable_available": True,
            }
        if (root / "requirements.txt").exists():
            command = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
            reason = "Install the Python requirements before Thomas tries to run the project."
        elif (root / "pyproject.toml").exists():
            command = [sys.executable, "-m", "pip", "install", "-e", "."]
            reason = "Install the editable project package before Thomas tries to run it."
        else:
            command = []
            reason = "Python project detected, but Thomas could not infer a safe environment setup command."
        return {
            "needed": bool(command),
            "label": "Prepare Project",
            "command": command,
            "command_display": _command_display(command),
            "reason": reason,
            "executable_available": bool(Path(sys.executable).exists()),
        }

    return {
        "needed": False,
        "label": "Ready",
        "command": [],
        "command_display": "",
        "reason": "",
        "executable_available": False,
    }


def _build_test_candidates(root: Path, profile: dict[str, Any]) -> list[dict[str, Any]]:
    package_json = _read_json_file(root / "package.json")
    candidates: list[dict[str, Any]] = []
    scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
    package_manager = _safe_text(profile.get("package_manager")).lower()
    if isinstance(scripts, dict):
        for script_name in ("test", "check", "lint"):
            if script_name in scripts:
                command = _command_for_script(package_manager or "npm", script_name)
                executable = command[0] if command else ""
                candidates.append(
                    {
                        "id": f"test-{script_name}",
                        "label": "Run Tests" if script_name == "test" else f"Run {script_name.title()}",
                        "command": command,
                        "command_display": _command_display(command),
                        "executable_available": bool(executable and shutil.which(executable)),
                    }
                )
                break
    if (root / "pytest.ini").exists() or (root / "tests").exists():
        candidates.append(
            {
                "id": "test-pytest",
                "label": "Run Pytest",
                "command": [sys.executable, "-m", "pytest"],
                "command_display": f"{Path(sys.executable).name} -m pytest",
                "executable_available": bool(Path(sys.executable).exists()),
            }
        )
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = _safe_text(candidate.get("command_display"))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique[:2]


def _build_scope_summary(root: Path, profile: dict[str, Any], project_type: str) -> str:
    readme_excerpt = _read_readme_excerpt(root)
    if readme_excerpt:
        return readme_excerpt
    framework = _safe_text(profile.get("framework")) or "project"
    root_name = root.name.replace("_", " ").replace("-", " ").strip()
    if project_type == "game":
        return f"{root_name or root.name} looks like an interactive game project that Thomas can stage, inspect, and launch from My Stuff."
    if project_type == "web_app":
        return f"{root_name or root.name} looks like a {framework} app that Thomas can inspect, summarize, and keep launch-ready from My Stuff."
    if project_type == "desktop_app":
        return f"{root_name or root.name} looks like a {framework} desktop app that Thomas can stage and launch from My Stuff."
    if project_type == "python_app":
        return f"{root_name or root.name} looks like a Python app or workspace that Thomas can inspect and prepare from My Stuff."
    return f"{root_name or root.name} is staged in My Stuff so Thomas can keep the project close, summarize it, and help you move faster."


def _build_readiness(profile: dict[str, Any], prepare: dict[str, Any]) -> dict[str, Any]:
    launch = profile.get("launch") if isinstance(profile.get("launch"), dict) else {}
    kind = _safe_text(profile.get("kind")).lower()
    if _safe_text(profile.get("status")).lower() == "missing":
        return {
            "state": "missing",
            "label": "Missing",
            "summary": "The source folder is no longer available on this machine.",
            "needs_preparation": False,
        }
    if prepare.get("needed"):
        command_display = _safe_text(prepare.get("command_display"))
        if not prepare.get("executable_available") and command_display:
            return {
                "state": "environment_issue",
                "label": "Needs Environment Setup",
                "summary": f"Thomas found a preparation step, but `{command_display.split()[0]}` is not installed on this machine yet.",
                "needs_preparation": True,
            }
        return {
            "state": "preparation_required",
            "label": "Prepare Project",
            "summary": _safe_text(prepare.get("reason"))
            or "Dependencies or environment setup are still needed before launch.",
            "needs_preparation": True,
        }
    if _safe_text(launch.get("kind")).lower() == "command":
        if not launch.get("executable_available"):
            return {
                "state": "environment_issue",
                "label": "Needs Environment Setup",
                "summary": "Thomas found a launch command, but the required executable is not installed on this machine yet.",
                "needs_preparation": False,
            }
        return {
            "state": "launch_ready",
            "label": "Launch Ready",
            "summary": "Thomas found a runnable command for this project.",
            "needs_preparation": False,
        }
    if _safe_text(launch.get("kind")).lower() == "file":
        return {
            "state": "open_ready",
            "label": "Open Ready",
            "summary": "Thomas can open this app directly inside the desktop environment.",
            "needs_preparation": False,
        }
    if kind == "python_project":
        return {
            "state": "review_needed",
            "label": "Review Needed",
            "summary": "Thomas found a Python project, but the best launch path still needs a quick review.",
            "needs_preparation": False,
        }
    return {
        "state": "linked",
        "label": "Linked",
        "summary": "Thomas has staged the repo and can keep it one click away from My Stuff.",
        "needs_preparation": False,
    }


def _build_findings_preview(
    root: Path,
    profile: dict[str, Any],
    prepare: dict[str, Any],
    test_candidates: list[dict[str, Any]],
    scope_summary: str,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    readme_excerpt = _read_readme_excerpt(root)
    launch = profile.get("launch") if isinstance(profile.get("launch"), dict) else {}
    if scope_summary:
        findings.append({"level": "info", "title": "Thomas read", "detail": scope_summary})
    if prepare.get("needed"):
        findings.append(
            {
                "level": "warn",
                "title": "Preparation needed",
                "detail": _safe_text(prepare.get("reason"))
                or "This project still needs dependency or environment setup before it is launch-ready.",
            }
        )
    elif _safe_text(launch.get("kind")).lower() == "command" and launch.get("executable_available"):
        findings.append(
            {
                "level": "good",
                "title": "Runnable command found",
                "detail": f"Thomas found `{_safe_text(launch.get('command_display'))}` as a likely way to launch this project.",
            }
        )
    elif _safe_text(launch.get("kind")).lower() == "file":
        findings.append(
            {
                "level": "good",
                "title": "Direct open available",
                "detail": "Thomas found an entry file it can open without a terminal step.",
            }
        )
    else:
        findings.append(
            {
                "level": "warn",
                "title": "No launch shortcut yet",
                "detail": "Thomas linked the repo, but it still needs a clearer launch path before it feels like an app.",
            }
        )
    if not readme_excerpt:
        findings.append(
            {
                "level": "info",
                "title": "Scope inferred from files",
                "detail": "This repo does not expose a clear README summary, so Thomas is inferring scope from filenames and project structure.",
            }
        )
    if not test_candidates:
        findings.append(
            {
                "level": "warn",
                "title": "No obvious test command",
                "detail": "Thomas did not find a safe first-pass test command yet.",
            }
        )
    else:
        findings.append(
            {
                "level": "info",
                "title": "Test path detected",
                "detail": f"Thomas found `{_safe_text(test_candidates[0].get('command_display'))}` as a likely verification step.",
            }
        )
    return findings[:5]


def _build_launch_candidates(
    profile: dict[str, Any], prepare: dict[str, Any], test_candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    launch = profile.get("launch") if isinstance(profile.get("launch"), dict) else {}
    candidates: list[dict[str, Any]] = []
    if prepare.get("needed"):
        candidates.append(
            {
                "action": "prepare",
                "label": _safe_text(prepare.get("label")) or "Prepare Project",
                "command_display": _safe_text(prepare.get("command_display")),
                "available": bool(prepare.get("executable_available") and prepare.get("command")),
                "reason": _safe_text(prepare.get("reason")),
            }
        )
    launch_kind = _safe_text(launch.get("kind")).lower()
    if launch_kind == "command":
        candidates.append(
            {
                "action": "launch",
                "label": _safe_text(launch.get("label")) or "Launch App",
                "command_display": _safe_text(launch.get("command_display")),
                "available": bool(launch.get("executable_available")) and not prepare.get("needed"),
                "reason": "Runs the detected project command inside the original repo folder.",
            }
        )
    elif launch_kind == "file":
        candidates.append(
            {
                "action": "open_entry",
                "label": _safe_text(launch.get("label")) or "Open App",
                "command_display": _safe_text(launch.get("target")),
                "available": True,
                "reason": "Opens the detected entry file directly.",
            }
        )
    if test_candidates:
        test_candidate = test_candidates[0]
        candidates.append(
            {
                "action": "test",
                "label": _safe_text(test_candidate.get("label")) or "Run Tests",
                "command_display": _safe_text(test_candidate.get("command_display")),
                "available": bool(test_candidate.get("executable_available")) and not prepare.get("needed"),
                "reason": "Runs the safest first-pass verification command Thomas could infer.",
            }
        )
    candidates.append(
        {
            "action": "open_folder",
            "label": "Open Folder",
            "command_display": "",
            "available": True,
            "reason": "Opens the original repo folder in the local desktop shell.",
        }
    )
    return candidates


def _build_actions(
    profile: dict[str, Any], prepare: dict[str, Any], test_candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    available = ["open_folder"]
    primary_action = "open_folder"
    primary_label = "Open Folder"
    launch = profile.get("launch") if isinstance(profile.get("launch"), dict) else {}
    if prepare.get("needed"):
        available.insert(0, "prepare")
        primary_action = "prepare"
        primary_label = _safe_text(prepare.get("label")) or "Prepare Project"
    elif (
        _safe_text(launch.get("kind")).lower() == "command"
        and bool(launch.get("command"))
        and launch.get("executable_available")
    ):
        available.insert(0, "launch")
        primary_action = "launch"
        primary_label = _safe_text(launch.get("label")) or "Launch App"
    elif _safe_text(launch.get("kind")).lower() == "file" and _safe_text(launch.get("target")):
        available.insert(0, "open_entry")
        primary_action = "open_entry"
        primary_label = _safe_text(launch.get("label")) or "Open App"
    if test_candidates:
        available.append("test")
    return {
        "primary": primary_action,
        "primary_label": primary_label,
        "available": available,
    }


def _build_project_dossier(
    root: Path,
    *,
    existing: dict[str, Any] | None = None,
    name: str | None = None,
    touch: bool,
    index: int = 0,
    import_method: str = "path",
) -> dict[str, Any]:
    existing = existing or {}
    project_id = _safe_text(existing.get("id")) or _project_id_for_path(root)
    board_position = _normalize_board_position(existing.get("board_position"), index=index)
    board_icon = {
        "emoji": _safe_text(
            existing.get("board_icon", {}).get("emoji") if isinstance(existing.get("board_icon"), dict) else ""
        )
        or _emoji_for_project(_safe_text(existing.get("kind")), _safe_text(existing.get("framework")), root.name),
        "accent": _safe_text(
            existing.get("board_icon", {}).get("accent") if isinstance(existing.get("board_icon"), dict) else ""
        )
        or _accent_for_id(project_id),
    }
    now = _utc_now_iso()

    if not root.exists() or not root.is_dir():
        created_at = _safe_text(existing.get("created_at")) or now
        updated_at = now if touch else (_safe_text(existing.get("updated_at")) or now)
        return {
            "id": project_id,
            "name": name or _safe_text(existing.get("name")) or root.name,
            "root_name": root.name,
            "root_path": str(root),
            "status": "missing",
            "kind": _safe_text(existing.get("kind")) or "folder",
            "project_type": _safe_text(existing.get("project_type")) or "workspace",
            "framework": _safe_text(existing.get("framework")) or "Folder",
            "package_manager": _safe_text(existing.get("package_manager")),
            "entry_path": "",
            "summary": "Folder is no longer available on this machine.",
            "scope_summary": _safe_text(existing.get("scope_summary"))
            or "Thomas lost access to the source folder for this project.",
            "launch": {
                "kind": "none",
                "label": "Unavailable",
                "command": [],
                "command_display": "",
                "target": "",
                "executable_available": False,
            },
            "launch_candidates": [
                {
                    "action": "open_folder",
                    "label": "Unavailable",
                    "command_display": "",
                    "available": False,
                    "reason": "The source folder is missing.",
                }
            ],
            "test_candidates": [],
            "prepare": {
                "needed": False,
                "label": "Unavailable",
                "command": [],
                "command_display": "",
                "reason": "The source folder is missing.",
                "executable_available": False,
            },
            "readiness": {
                "state": "missing",
                "label": "Missing",
                "summary": "The source folder is no longer available on this machine.",
                "needs_preparation": False,
            },
            "analysis": {
                "status": "missing",
                "updated_at": updated_at,
                "file_count": 0,
                "top_level": [],
                "readme_excerpt": "",
                "import_method": _safe_text(
                    existing.get("analysis", {}).get("import_method")
                    if isinstance(existing.get("analysis"), dict)
                    else ""
                )
                or import_method,
            },
            "findings_preview": [
                {
                    "level": "warn",
                    "title": "Source folder missing",
                    "detail": "Thomas still has the shortcut, but the original repo folder is no longer available on this machine.",
                }
            ],
            "actions": {
                "primary": "",
                "primary_label": "Unavailable",
                "available": ["remove"],
            },
            "import_state": "missing",
            "board_position": board_position,
            "board_icon": board_icon,
            "created_at": created_at,
            "updated_at": updated_at,
            "launch_count": max(0, _safe_int(existing.get("launch_count"))),
            "last_launched_at": _safe_text(existing.get("last_launched_at")),
            "last_prepared_at": _safe_text(existing.get("last_prepared_at")),
            "source": {
                "ownership": "direct_folder",
                "import_method": _safe_text(
                    existing.get("source", {}).get("import_method") if isinstance(existing.get("source"), dict) else ""
                )
                or import_method,
            },
        }

    profile = _build_launch_profile(root)
    project_type = _detect_project_type(
        _safe_text(profile.get("kind")), _safe_text(profile.get("framework")), root.name
    )
    scope_summary = _build_scope_summary(root, profile, project_type)
    prepare = _build_prepare_profile(root, profile)
    test_candidates = _build_test_candidates(root, profile)
    readiness = _build_readiness(profile, prepare)
    findings_preview = _build_findings_preview(root, profile, prepare, test_candidates, scope_summary)
    launch_candidates = _build_launch_candidates(profile, prepare, test_candidates)
    created_at = _safe_text(existing.get("created_at")) or now
    updated_at = now if touch else (_safe_text(existing.get("updated_at")) or now)
    top_level = _top_level_entries(root)
    readme_excerpt = _read_readme_excerpt(root)
    board_icon = {
        "emoji": _safe_text(
            existing.get("board_icon", {}).get("emoji") if isinstance(existing.get("board_icon"), dict) else ""
        )
        or _emoji_for_project(_safe_text(profile.get("kind")), _safe_text(profile.get("framework")), root.name),
        "accent": _safe_text(
            existing.get("board_icon", {}).get("accent") if isinstance(existing.get("board_icon"), dict) else ""
        )
        or _accent_for_id(project_id),
    }

    return {
        "id": project_id,
        "name": name or _safe_text(existing.get("name")) or root.name,
        "root_name": root.name,
        "root_path": str(root),
        "status": "ready",
        "kind": profile["kind"],
        "project_type": project_type,
        "framework": profile["framework"],
        "package_manager": profile["package_manager"],
        "entry_path": profile["entry_path"],
        "summary": profile["summary"],
        "scope_summary": scope_summary,
        "launch": profile["launch"],
        "launch_candidates": launch_candidates,
        "test_candidates": test_candidates,
        "prepare": prepare,
        "readiness": readiness,
        "analysis": {
            "status": "ready",
            "updated_at": updated_at,
            "file_count": _count_files(root),
            "top_level": top_level,
            "readme_excerpt": readme_excerpt,
            "import_method": import_method,
        },
        "findings_preview": findings_preview,
        "actions": _build_actions(profile, prepare, test_candidates),
        "import_state": "ready",
        "board_position": board_position,
        "board_icon": board_icon,
        "created_at": created_at,
        "updated_at": updated_at,
        "launch_count": max(0, _safe_int(existing.get("launch_count"))),
        "last_launched_at": _safe_text(existing.get("last_launched_at")),
        "last_prepared_at": _safe_text(existing.get("last_prepared_at")),
        "source": {
            "ownership": "direct_folder",
            "import_method": import_method,
        },
    }


def _refresh_projects(app: web.Application) -> list[dict[str, Any]]:
    stored = _read_registry(app)
    refreshed: list[dict[str, Any]] = []
    changed = False
    for index, row in enumerate(stored):
        root = Path(_safe_text(row.get("root_path")))
        import_method = (
            _safe_text(row.get("source", {}).get("import_method") if isinstance(row.get("source"), dict) else "")
            or "path"
        )
        materialized = _build_project_dossier(root, existing=row, touch=False, index=index, import_method=import_method)
        refreshed.append(materialized)
        if materialized != row:
            changed = True
    refreshed = _sort_projects(refreshed)
    if changed:
        _write_registry(app, refreshed)
    return refreshed


def _find_project(projects: list[dict[str, Any]], project_id: str) -> tuple[int, dict[str, Any]]:
    for index, row in enumerate(projects):
        if _safe_text(row.get("id")) == project_id:
            return index, row
    raise web.HTTPNotFound(text="project not found")


def _open_path(target: Path) -> dict[str, Any]:
    if hasattr(os, "startfile"):
        os.startfile(str(target))  # type: ignore[attr-defined]
        return {"kind": "opened_path", "target": str(target)}
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)], close_fds=True)
        return {"kind": "opened_path", "target": str(target)}
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(target)], close_fds=True)
        return {"kind": "opened_path", "target": str(target)}
    opened = webbrowser.open(target.as_uri())
    if not opened:
        raise web.HTTPConflict(text="could not open target path")
    return {"kind": "opened_path", "target": str(target)}


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    if not command:
        raise web.HTTPConflict(text="launch command is not configured")
    display_command = [_safe_text(part) for part in command if _safe_text(part)]
    if not display_command:
        raise web.HTTPConflict(text="launch command is not configured")
    executable = display_command[0]
    resolved_executable = shutil.which(executable) or executable
    executable_ok = Path(executable).exists() or bool(shutil.which(executable))
    if not executable_ok:
        raise web.HTTPConflict(text=f"`{executable}` is not installed on this machine")
    actual_command = list(display_command)
    kwargs: dict[str, Any] = {"cwd": str(cwd)}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        detached_flag = getattr(subprocess, "DETACHED_PROCESS", 0)
        kwargs["creationflags"] = creationflags | detached_flag
        kwargs["close_fds"] = True
        lowered = _safe_text(resolved_executable).lower()
        if lowered.endswith(".cmd") or lowered.endswith(".bat"):
            actual_command = ["cmd.exe", "/c", *display_command]
    else:
        kwargs["close_fds"] = True
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(actual_command, **kwargs)
    except FileNotFoundError as exc:
        raise web.HTTPConflict(text=f"launch executable not found: {executable}") from exc
    except OSError as exc:
        raise web.HTTPConflict(text=f"could not launch project: {exc}") from exc
    return {
        "kind": "command_started",
        "command": display_command,
        "launched_command": actual_command,
        "command_display": _command_display(display_command),
        "cwd": str(cwd),
        "pid": int(getattr(proc, "pid", 0) or 0),
    }


def _perform_project_action(project: dict[str, Any], requested_action: str) -> tuple[str, dict[str, Any]]:
    if _safe_text(project.get("status")).lower() != "ready":
        raise web.HTTPConflict(text="project folder is not currently available")

    action = (
        _safe_text(requested_action).lower()
        or _safe_text(project.get("actions", {}).get("primary")).lower()
        or "open_folder"
    )
    root = Path(_safe_text(project.get("root_path")))
    launch = project.get("launch") if isinstance(project.get("launch"), dict) else {}
    prepare = project.get("prepare") if isinstance(project.get("prepare"), dict) else {}
    test_candidates = project.get("test_candidates") if isinstance(project.get("test_candidates"), list) else []

    if action == "prepare":
        command = prepare.get("command") if isinstance(prepare.get("command"), list) else []
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


def register_local_project_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    require_loopback: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    async def api_local_projects_list(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        projects = _refresh_projects(request.app)
        return web.json_response({"ok": True, "count": len(projects), "projects": projects})

    async def api_local_projects_import(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        root = _resolve_project_root(payload.get("path") or payload.get("root_path"))
        name = _safe_text(payload.get("name") or payload.get("display_name"))
        import_method = _safe_text(payload.get("import_method") or "path") or "path"

        projects = _read_registry(request.app)
        root_key = _project_root_key(root)
        existing_index = -1
        existing_row: dict[str, Any] | None = None
        for index, row in enumerate(projects):
            row_root = _safe_text(row.get("root_path"))
            if row_root and _project_root_key(Path(row_root)) == root_key:
                existing_index = index
                existing_row = row
                break

        project = _build_project_dossier(
            root,
            existing=existing_row,
            name=name or None,
            touch=True,
            index=existing_index if existing_index >= 0 else len(projects),
            import_method=import_method,
        )
        if existing_index >= 0:
            projects[existing_index] = project
        else:
            projects.append(project)
        projects = _sort_projects(projects)[:_MAX_PROJECTS]
        _write_registry(request.app, projects)
        return web.json_response(
            {
                "ok": True,
                "updated": existing_index >= 0,
                "count": len(projects),
                "project": project,
            }
        )

    async def api_local_projects_pick_folder(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        path_value = _pick_folder_via_dialog()
        if not path_value:
            return web.json_response({"ok": True, "cancelled": True, "path": ""})
        return web.json_response({"ok": True, "cancelled": False, "path": str(_resolve_project_root(path_value))})

    async def api_local_project_detail(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _refresh_projects(request.app)
        _, project = _find_project(projects, project_id)
        return web.json_response({"ok": True, "project": project})

    async def api_local_project_layout(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        x = _safe_int(payload.get("x"), -1)
        y = _safe_int(payload.get("y"), -1)
        if x < 0 or y < 0:
            raise web.HTTPBadRequest(text="x and y are required integer coordinates")
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        project["board_position"] = {"x": x, "y": y}
        project["updated_at"] = _utc_now_iso()
        projects[index] = project
        _write_registry(request.app, projects)
        return web.json_response({"ok": True, "project": project})

    async def api_local_project_action(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload: Any = {}
        if request.can_read_body:
            payload = await read_json(request)
            if payload is None:
                payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        action = _safe_text(payload.get("action")).lower() or "launch"

        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        final_action, result = _perform_project_action(project, action)
        now = _utc_now_iso()
        project["updated_at"] = now
        if final_action in {"launch", "open_entry", "open_folder", "test"}:
            project["launch_count"] = max(0, _safe_int(project.get("launch_count"))) + 1
            project["last_launched_at"] = now
        if final_action == "prepare":
            project["last_prepared_at"] = now
        projects[index] = project
        _write_registry(request.app, projects)
        return web.json_response({"ok": True, "action": final_action, "project": project, "result": result})

    async def api_local_projects_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _read_registry(request.app)
        index, project = _find_project(projects, project_id)
        projects.pop(index)
        _write_registry(request.app, projects)
        return web.json_response(
            {
                "ok": True,
                "removed_id": project_id,
                "removed_name": _safe_text(project.get("name")),
                "count": len(projects),
            }
        )

    app.router.add_get("/api/local/projects", api_local_projects_list)
    app.router.add_post("/api/local/projects/import", api_local_projects_import)
    app.router.add_post("/api/local/projects/link", api_local_projects_import)
    app.router.add_post("/api/local/projects/pick-folder", api_local_projects_pick_folder)
    app.router.add_get("/api/local/projects/{project_id}", api_local_project_detail)
    app.router.add_patch("/api/local/projects/{project_id}/layout", api_local_project_layout)
    app.router.add_post("/api/local/projects/{project_id}/action", api_local_project_action)
    app.router.add_post("/api/local/projects/{project_id}/launch", api_local_project_action)
    app.router.add_delete("/api/local/projects/{project_id}", api_local_projects_delete)
