from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def _first_executable(candidates: Sequence[str]) -> str | None:
    for item in candidates:
        name = _safe_string(item)
        if not name:
            continue
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def _version_line_for_command(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except Exception as exc:
        return f"version check failed: {exc}"
    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    if not lines:
        lines = [line.strip() for line in (completed.stderr or "").splitlines() if line.strip()]
    if lines:
        return lines[0][:220]
    return f"exit code {completed.returncode}"


ActionCommandBuilder = Callable[[str, Mapping[str, Any], "ConnectorDefinition"], list[str]]


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    label: str
    description: str
    payload_fields: tuple[str, ...]
    command_builder: ActionCommandBuilder

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "payload_fields": list(self.payload_fields),
        }


@dataclass(frozen=True)
class ConnectorDefinition:
    id: str
    label: str
    category: str
    license: str
    website: str
    executables: tuple[str, ...]
    version_args: tuple[str, ...]
    install_hint: str
    actions: tuple[ActionDefinition, ...]

    def action_by_id(self, action_id: str) -> ActionDefinition | None:
        key = _safe_string(action_id).lower()
        for action in self.actions:
            if _safe_string(action.id).lower() == key:
                return action
        return None

    def resolve_executable(self) -> str | None:
        return _first_executable(self.executables)

    def detect(self) -> dict[str, Any]:
        resolved = self.resolve_executable()
        installed = bool(resolved)
        version = ""
        if resolved:
            version = _version_line_for_command([resolved, *self.version_args])
        return {
            "id": self.id,
            "installed": installed,
            "executable": resolved or "",
            "version": version,
            "actions": [item.id for item in self.actions],
            "install_hint": self.install_hint,
        }

    def build_command(self, action_id: str, payload: Mapping[str, Any]) -> list[str]:
        action = self.action_by_id(action_id)
        if action is None:
            raise ValueError(f"unknown action '{action_id}' for connector '{self.id}'")
        resolved = self.resolve_executable()
        if not resolved:
            raise RuntimeError(
                f"connector '{self.id}' is not installed (expected one of: {', '.join(self.executables)})"
            )
        return action.command_builder(resolved, payload, self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "license": self.license,
            "website": self.website,
            "executables": list(self.executables),
            "version_args": list(self.version_args),
            "install_hint": self.install_hint,
            "actions": [action.to_dict() for action in self.actions],
        }


class ConnectorCatalog:
    def __init__(self, connectors: Sequence[ConnectorDefinition]):
        items = list(connectors)
        by_id = {_safe_string(item.id).lower(): item for item in items if _safe_string(item.id)}
        if len(by_id) != len(items):
            raise ValueError("connector ids must be unique")
        self._items = tuple(items)
        self._by_id = by_id

    def list(self) -> list[ConnectorDefinition]:
        return list(self._items)

    def get(self, connector_id: str) -> ConnectorDefinition | None:
        return self._by_id.get(_safe_string(connector_id).lower())

    def detect_all(self) -> list[dict[str, Any]]:
        return [item.detect() for item in self._items]


def _build_version_command(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = payload
    return [executable, *connector.version_args]


def _build_ffmpeg_transcode(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    input_path = _safe_string(payload.get("input_path"))
    output_path = _safe_string(payload.get("output_path"))
    if not input_path or not output_path:
        raise ValueError("input_path and output_path are required for ffmpeg transcode")
    vcodec = _safe_string(payload.get("vcodec")) or "libx264"
    acodec = _safe_string(payload.get("acodec")) or "aac"
    return [
        executable,
        "-y",
        "-i",
        input_path,
        "-c:v",
        vcodec,
        "-c:a",
        acodec,
        output_path,
    ]


def _build_ffmpeg_concat(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    list_file = _safe_string(payload.get("list_file"))
    output_path = _safe_string(payload.get("output_path"))
    if not list_file or not output_path:
        raise ValueError("list_file and output_path are required for ffmpeg concat")
    return [
        executable,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file,
        "-c",
        "copy",
        output_path,
    ]


def _build_blender_render(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    blend_file = _safe_string(payload.get("blend_file"))
    if not blend_file:
        return [executable, *connector.version_args]
    output_pattern = _safe_string(payload.get("output_pattern")) or "//render_#####"
    image_format = _safe_string(payload.get("format")).upper() or "PNG"
    frame = _safe_string(payload.get("frame")) or "1"
    return [
        executable,
        "-b",
        blend_file,
        "-o",
        output_pattern,
        "-F",
        image_format,
        "-f",
        frame,
    ]


def _build_unreal_python(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    project_path = _safe_string(payload.get("project_path"))
    script_path = _safe_string(payload.get("python_script"))
    if not project_path or not script_path:
        raise ValueError("project_path and python_script are required for unreal run_python")
    extra = _safe_string(payload.get("extra_args"))
    command = [
        executable,
        project_path,
        "-run=pythonscript",
        f"-script={script_path}",
        "-unattended",
        "-nosplash",
        "-nop4",
    ]
    if extra:
        command.extend(extra.split())
    return command


def _build_unity_open(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    project_path = _safe_string(payload.get("project_path"))
    if not project_path:
        return [executable, "-version"]
    return [executable, "-projectPath", project_path]


def _build_unity_build(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    project_path = _safe_string(payload.get("project_path"))
    if not project_path:
        raise ValueError("project_path is required for unity build_player")
    _stripped = project_path.rstrip("/\\")
    output_path = _safe_string(payload.get("output_path")) or f"{_stripped}/Builds/Game.exe"
    method = _safe_string(payload.get("execute_method"))
    build_target = _safe_string(payload.get("build_target")) or "Windows64"
    command = [
        executable,
        "-batchmode",
        "-quit",
        "-projectPath",
        project_path,
        "-buildTarget",
        build_target,
        "-customBuildPath",
        output_path,
    ]
    if method:
        command.extend(["-executeMethod", method])
    return command


def _build_godot_open(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    project_path = _safe_string(payload.get("project_path"))
    if not project_path:
        return [executable, *connector.version_args]
    return [executable, "--path", project_path]


def _build_godot_export(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    project_path = _safe_string(payload.get("project_path"))
    if not project_path:
        raise ValueError("project_path is required for godot export_release")
    preset = _safe_string(payload.get("preset")) or "Windows Desktop"
    _stripped = project_path.rstrip("/\\")
    output_path = _safe_string(payload.get("output_path")) or f"{_stripped}/build/game.exe"
    return [
        executable,
        "--headless",
        "--path",
        project_path,
        "--export-release",
        preset,
        output_path,
    ]


def _build_notion_sync(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    page_id = _safe_string(payload.get("page_id"))
    if not page_id:
        raise ValueError("page_id is required for notion sync_page")
    token = _safe_string(payload.get("token"))
    token_env = _safe_string(payload.get("token_env")) or "NOTION_TOKEN"
    base_url = _safe_string(payload.get("base_url"))
    output = _safe_string(payload.get("output"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "notion_pull_page",
        "--page-id",
        page_id,
        "--token-env",
        token_env,
    ]
    if token:
        command.extend(["--token", token])
    if base_url:
        command.extend(["--base-url", base_url])
    if output:
        command.extend(["--output", output])
    return command


def _build_figma_pull(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    file_key = _safe_string(payload.get("file_key"))
    if not file_key:
        raise ValueError("file_key is required for figma pull_file")
    token = _safe_string(payload.get("token"))
    token_env = _safe_string(payload.get("token_env")) or "FIGMA_TOKEN"
    node_id = _safe_string(payload.get("node_id"))
    base_url = _safe_string(payload.get("base_url"))
    output = _safe_string(payload.get("output"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "figma_pull_file",
        "--file-key",
        file_key,
        "--token-env",
        token_env,
    ]
    if token:
        command.extend(["--token", token])
    if node_id:
        command.extend(["--node-id", node_id])
    if base_url:
        command.extend(["--base-url", base_url])
    if output:
        command.extend(["--output", output])
    return command


def _build_github_issue_sync(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    repo = _safe_string(payload.get("repo"))
    issue_number = _safe_string(payload.get("issue_number"))
    if not repo or not issue_number:
        raise ValueError("repo and issue_number are required for github issue_to_task")
    token = _safe_string(payload.get("token"))
    token_env = _safe_string(payload.get("token_env")) or "GITHUB_TOKEN"
    base_url = _safe_string(payload.get("base_url"))
    output = _safe_string(payload.get("output"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "github_issue_to_task",
        "--repo",
        repo,
        "--issue-number",
        issue_number,
        "--token-env",
        token_env,
    ]
    if token:
        command.extend(["--token", token])
    if base_url:
        command.extend(["--base-url", base_url])
    if output:
        command.extend(["--output", output])
    return command


def _build_github_pr_scan(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    repo = _safe_string(payload.get("repo"))
    pr_number = _safe_string(payload.get("pr_number"))
    if not repo or not pr_number:
        raise ValueError("repo and pr_number are required for github pr_risk_scan")
    token = _safe_string(payload.get("token"))
    token_env = _safe_string(payload.get("token_env")) or "GITHUB_TOKEN"
    base_url = _safe_string(payload.get("base_url"))
    output = _safe_string(payload.get("output"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "github_pr_risk_scan",
        "--repo",
        repo,
        "--pr-number",
        pr_number,
        "--token-env",
        token_env,
    ]
    if token:
        command.extend(["--token", token])
    if base_url:
        command.extend(["--base-url", base_url])
    if output:
        command.extend(["--output", output])
    return command


def _build_comfyui_queue(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    server_url = _safe_string(payload.get("server_url")) or "http://127.0.0.1:8188"
    workflow_json = _safe_string(payload.get("workflow_json"))
    workflow_file = _safe_string(payload.get("workflow_file"))
    if not workflow_json and not workflow_file:
        raise ValueError("workflow_json or workflow_file is required for comfyui queue_prompt")
    client_id = _safe_string(payload.get("client_id"))
    output = _safe_string(payload.get("output"))
    timeout_s = _safe_string(payload.get("timeout_s"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "comfyui_queue_prompt",
        "--server-url",
        server_url,
    ]
    if workflow_json:
        command.extend(["--workflow-json", workflow_json])
    if workflow_file:
        command.extend(["--workflow-file", workflow_file])
    if client_id:
        command.extend(["--client-id", client_id])
    if timeout_s:
        command.extend(["--timeout-s", timeout_s])
    if output:
        command.extend(["--output", output])
    return command


def _build_comfyui_history(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    server_url = _safe_string(payload.get("server_url")) or "http://127.0.0.1:8188"
    prompt_id = _safe_string(payload.get("prompt_id"))
    if not prompt_id:
        raise ValueError("prompt_id is required for comfyui get_history")
    output = _safe_string(payload.get("output"))
    timeout_s = _safe_string(payload.get("timeout_s"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "comfyui_get_history",
        "--server-url",
        server_url,
        "--prompt-id",
        prompt_id,
    ]
    if timeout_s:
        command.extend(["--timeout-s", timeout_s])
    if output:
        command.extend(["--output", output])
    return command


def _build_otio_validate(executable: str, payload: Mapping[str, Any], connector: ConnectorDefinition) -> list[str]:
    _ = connector
    input_path = _safe_string(payload.get("input_path"))
    if not input_path:
        raise ValueError("input_path is required for opentimelineio validate_timeline")
    output = _safe_string(payload.get("output"))
    command = [
        executable,
        "-m",
        "thomas.asset_studio.connector_shims",
        "otio_validate_timeline",
        "--input-path",
        input_path,
    ]
    if output:
        command.extend(["--output", output])
    return command


def _version_only_action() -> tuple[ActionDefinition, ...]:
    return (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run connector version command and capture output.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
    )


def default_connector_catalog() -> ConnectorCatalog:
    ffmpeg_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run ffmpeg version command.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="transcode",
            label="Transcode",
            description="Transcode media using ffmpeg.",
            payload_fields=("input_path", "output_path", "vcodec", "acodec"),
            command_builder=_build_ffmpeg_transcode,
        ),
        ActionDefinition(
            id="concat",
            label="Concat",
            description="Concatenate inputs listed in ffmpeg concat list file.",
            payload_fields=("list_file", "output_path"),
            command_builder=_build_ffmpeg_concat,
        ),
    )
    blender_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run blender version command.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="render_blend",
            label="Render Blend",
            description="Run a non-interactive Blender render job.",
            payload_fields=("blend_file", "output_pattern", "format", "frame"),
            command_builder=_build_blender_render,
        ),
    )
    unreal_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Unreal editor command in headless mode for version/help output.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="run_python",
            label="Run Python Script",
            description="Execute a python script against an Unreal project.",
            payload_fields=("project_path", "python_script", "extra_args"),
            command_builder=_build_unreal_python,
        ),
    )
    unity_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Unity version command.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="open_project",
            label="Open Project",
            description="Open a Unity project path.",
            payload_fields=("project_path",),
            command_builder=_build_unity_open,
        ),
        ActionDefinition(
            id="build_player",
            label="Build Player",
            description="Run Unity batch build with optional execute method.",
            payload_fields=("project_path", "output_path", "build_target", "execute_method"),
            command_builder=_build_unity_build,
        ),
    )
    godot_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Godot version command.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="open_project",
            label="Open Project",
            description="Open a Godot project path.",
            payload_fields=("project_path",),
            command_builder=_build_godot_open,
        ),
        ActionDefinition(
            id="export_release",
            label="Export Release",
            description="Run a Godot headless export.",
            payload_fields=("project_path", "preset", "output_path"),
            command_builder=_build_godot_export,
        ),
    )
    notion_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Python version command for Notion connector shim.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="sync_page",
            label="Sync Page",
            description="Fetch a Notion page and emit normalized metadata.",
            payload_fields=("page_id", "token_env", "token", "base_url", "output"),
            command_builder=_build_notion_sync,
        ),
    )
    figma_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Python version command for Figma connector shim.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="pull_file",
            label="Pull File",
            description="Fetch Figma file metadata for automation workflows.",
            payload_fields=("file_key", "node_id", "token_env", "token", "base_url", "output"),
            command_builder=_build_figma_pull,
        ),
    )
    github_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Python version command for GitHub connector shim.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="issue_to_task",
            label="Issue To Task",
            description="Fetch a GitHub issue and normalize it into a task payload.",
            payload_fields=("repo", "issue_number", "token_env", "token", "base_url", "output"),
            command_builder=_build_github_issue_sync,
        ),
        ActionDefinition(
            id="pr_risk_scan",
            label="PR Risk Scan",
            description="Fetch PR metadata/files and compute a deterministic risk summary.",
            payload_fields=("repo", "pr_number", "token_env", "token", "base_url", "output"),
            command_builder=_build_github_pr_scan,
        ),
    )
    comfyui_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Python version command for ComfyUI connector shim.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="queue_prompt",
            label="Queue Prompt",
            description="Queue a ComfyUI prompt/workflow for image generation.",
            payload_fields=("server_url", "workflow_json", "workflow_file", "client_id", "timeout_s", "output"),
            command_builder=_build_comfyui_queue,
        ),
        ActionDefinition(
            id="get_history",
            label="Get History",
            description="Fetch ComfyUI prompt execution history by prompt id.",
            payload_fields=("server_url", "prompt_id", "timeout_s", "output"),
            command_builder=_build_comfyui_history,
        ),
    )
    opentimelineio_actions = (
        ActionDefinition(
            id="version_check",
            label="Version Check",
            description="Run Python version command for OpenTimelineIO connector shim.",
            payload_fields=(),
            command_builder=_build_version_command,
        ),
        ActionDefinition(
            id="validate_timeline",
            label="Validate Timeline",
            description="Validate an OTIO timeline file and return structural metadata.",
            payload_fields=("input_path", "output"),
            command_builder=_build_otio_validate,
        ),
    )
    connectors = (
        ConnectorDefinition(
            id="ffmpeg",
            label="FFmpeg",
            category="media",
            license="LGPL/GPL",
            website="https://ffmpeg.org/",
            executables=("ffmpeg", "ffmpeg.exe"),
            version_args=("-version",),
            install_hint="Install FFmpeg and ensure ffmpeg is on PATH.",
            actions=ffmpeg_actions,
        ),
        ConnectorDefinition(
            id="blender",
            label="Blender",
            category="3d",
            license="GPL",
            website="https://www.blender.org/",
            executables=("blender", "blender.exe"),
            version_args=("--version",),
            install_hint="Install Blender and ensure blender is on PATH.",
            actions=blender_actions,
        ),
        ConnectorDefinition(
            id="unreal",
            label="Unreal Engine",
            category="engine",
            license="Unreal Engine EULA",
            website="https://www.unrealengine.com/",
            executables=("UnrealEditor-Cmd.exe", "UnrealEditor.exe"),
            version_args=("-help",),
            install_hint="Install Unreal Engine and add UnrealEditor-Cmd.exe to PATH (or configure absolute path).",
            actions=unreal_actions,
        ),
        ConnectorDefinition(
            id="unity",
            label="Unity",
            category="engine",
            license="Unity Terms of Service",
            website="https://unity.com/",
            executables=("Unity.exe", "unity", "unity.exe"),
            version_args=("-version",),
            install_hint="Install Unity and ensure Unity.exe is on PATH.",
            actions=unity_actions,
        ),
        ConnectorDefinition(
            id="godot",
            label="Godot",
            category="engine",
            license="MIT",
            website="https://godotengine.org/",
            executables=("godot4", "godot4.exe", "godot", "godot.exe"),
            version_args=("--version",),
            install_hint="Install Godot and ensure godot4 is on PATH.",
            actions=godot_actions,
        ),
        ConnectorDefinition(
            id="notion",
            label="Notion",
            category="docs",
            license="Notion API Terms",
            website="https://developers.notion.com/",
            executables=("python", "python.exe"),
            version_args=("--version",),
            install_hint="Set NOTION_TOKEN and use sync_page with a page_id.",
            actions=notion_actions,
        ),
        ConnectorDefinition(
            id="figma",
            label="Figma",
            category="design",
            license="Figma API Terms",
            website="https://www.figma.com/developers/api",
            executables=("python", "python.exe"),
            version_args=("--version",),
            install_hint="Set FIGMA_TOKEN and use pull_file with file_key.",
            actions=figma_actions,
        ),
        ConnectorDefinition(
            id="github",
            label="GitHub",
            category="devops",
            license="GitHub API Terms",
            website="https://docs.github.com/en/rest",
            executables=("python", "python.exe"),
            version_args=("--version",),
            install_hint="Set GITHUB_TOKEN and use issue_to_task/pr_risk_scan actions.",
            actions=github_actions,
        ),
        ConnectorDefinition(
            id="kdenlive",
            label="Kdenlive",
            category="video",
            license="GPL-3.0",
            website="https://kdenlive.org/",
            executables=("kdenlive", "kdenlive.exe"),
            version_args=("--version",),
            install_hint="Install Kdenlive and ensure kdenlive is on PATH.",
            actions=_version_only_action(),
        ),
        ConnectorDefinition(
            id="comfyui",
            label="ComfyUI",
            category="ai_image",
            license="GPL-3.0",
            website="https://github.com/comfyanonymous/ComfyUI",
            executables=("python", "python.exe"),
            version_args=("--version",),
            install_hint="Run local ComfyUI and use queue_prompt/get_history with server_url.",
            actions=comfyui_actions,
        ),
        ConnectorDefinition(
            id="opentimelineio",
            label="OpenTimelineIO",
            category="timeline",
            license="Apache-2.0",
            website="https://github.com/PixarAnimationStudios/OpenTimelineIO",
            executables=("python", "python.exe"),
            version_args=("--version",),
            install_hint="Install OpenTimelineIO in your Python env and use validate_timeline.",
            actions=opentimelineio_actions,
        ),
        ConnectorDefinition(
            id="audacity",
            label="Audacity",
            category="audio",
            license="GPL-2.0+",
            website="https://www.audacityteam.org/",
            executables=("audacity", "audacity.exe"),
            version_args=("--version",),
            install_hint="Install Audacity and enable mod-script-pipe for automation.",
            actions=_version_only_action(),
        ),
        ConnectorDefinition(
            id="krita",
            label="Krita",
            category="image",
            license="GPL",
            website="https://krita.org/",
            executables=("krita", "krita.exe"),
            version_args=("--version",),
            install_hint="Install Krita and ensure krita is on PATH.",
            actions=_version_only_action(),
        ),
        ConnectorDefinition(
            id="inkscape",
            label="Inkscape",
            category="vector",
            license="GPL",
            website="https://inkscape.org/",
            executables=("inkscape", "inkscape.exe"),
            version_args=("--version",),
            install_hint="Install Inkscape and ensure inkscape is on PATH.",
            actions=_version_only_action(),
        ),
        ConnectorDefinition(
            id="shotcut",
            label="Shotcut",
            category="video",
            license="GPL-3.0",
            website="https://shotcut.org/",
            executables=("shotcut", "shotcut.exe"),
            version_args=("--version",),
            install_hint="Install Shotcut and ensure shotcut is on PATH.",
            actions=_version_only_action(),
        ),
        ConnectorDefinition(
            id="lmms",
            label="LMMS",
            category="audio",
            license="GPL-2.0",
            website="https://lmms.io/",
            executables=("lmms", "lmms.exe"),
            version_args=("--version",),
            install_hint="Install LMMS and ensure lmms is on PATH.",
            actions=_version_only_action(),
        ),
    )
    return ConnectorCatalog(connectors)
