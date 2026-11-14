"""Extract named artifact paths without duplicating a qualified file reference."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Collection
from pathlib import Path, PurePosixPath

_PATH_TOKEN_RE = re.compile(r"(?<![\w.])((?:/|\./|~/)?(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+)(?::\d+)?")
_BARE_DATA_FILE_RE = re.compile(r"(?<![\w/.-])([\w-]+\.(?:json|csv|ya?ml|toml))\b", re.I)
_BACKTICK_FILE_RE = re.compile(r"`([\w.-]+\.([A-Za-z0-9]+))`")
_APPLE_BUNDLE_EXTENSIONS = frozenset({".xcodeproj", ".xcworkspace", ".xcassets"})
# Only unqualified backticked references to these library/framework names are ambiguous.
_JS_LIBRARY_FILES = frozenset({
    "three.js", "node.js", "next.js", "vue.js", "socket.io", "jquery.js", "react.js", "angular.js",
    "svelte.js", "ember.js", "alpine.js", "leaflet.js", "plotly.js", "moment.js", "preact.js",
    "backbone.js", "p5.js", "pixi.js", "babylon.js", "phaser.js", "matter.js", "cannon.js",
    "tone.js", "lodash.js", "d3.js", "chart.js", "axios.js", "anime.js", "rxjs.js", "gsap.js",
    "underscore.js", "knockout.js", "mithril.js", "lit.js", "solid.js", "nuxt.js", "gatsby.js",
    "express.js", "fastify.js", "jquery-ui.js", "semantic-ui.js",
})  # fmt: skip
# A sentence that says the files it names are not outputs: "files that were never outputs of your task", "do not
# create docs/scratch.md". A note listing files that were not outputs made three teams create them (2026-09-27).
_DISOWNS = re.compile(
    r"\b(?:never|not|no longer)\s+(?:an?\s+|the\s+)?outputs?\b|\b(?:never|do not|don't|must not)\s+create\b", re.I
)
# A path on this machine, C:\Users\someone\.codex\auth.json, written with either separator.
_SEGMENT = r"[^\s\\/`'\"()<>|,;]+"
_DRIVE_PATH_RE = re.compile(rf"(?<!\w)[A-Za-z]:[\\/](?:{_SEGMENT}[\\/])*({_SEGMENT}\.[A-Za-z0-9]{{1,8}})")
# Extensions a file a task makes can have, beside the source and data kinds the contract passes in. A path ending in
# one is never read as a version, so "dist/site-1.7z" and "print/part-2.3mf" stay outputs.
_FILE_EXTENSIONS = frozenset({
    # web, styles and templates
    ".htm", ".xhtml", ".css", ".scss", ".sass", ".less", ".cjs", ".mts", ".cts", ".astro", ".wasm", ".map", ".ejs",
    ".hbs", ".pug", ".njk", ".jinja", ".j2", ".twig", ".erb", ".liquid", ".mustache", ".tmpl", ".webmanifest",
    # more source, scripts and notebooks
    ".pyi", ".pyx", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".bash", ".zsh", ".fish", ".lua", ".pl", ".pm", ".r",
    ".dart", ".m", ".mm", ".ex", ".exs", ".erl", ".hs", ".ml", ".fs", ".clj", ".groovy", ".gradle", ".kts", ".zig",
    ".nim", ".jl", ".vb", ".f90", ".asm", ".sol", ".proto", ".graphql", ".gql", ".ipynb", ".glsl", ".wgsl", ".hlsl",
    ".frag", ".vert", ".shader", ".gd", ".tscn", ".tf", ".cmake", ".mk", ".spec", ".iss", ".nsi",
    # data and configuration
    ".jsonl", ".ndjson", ".json5", ".jsonc", ".geojson", ".tsv", ".xml", ".ini", ".cfg", ".conf", ".env",
    ".properties", ".entitlements", ".storyboard", ".plist", ".lock", ".service", ".desktop", ".lnk", ".pem", ".crt", ".key", ".sqlite", ".db",
    ".parquet", ".arrow", ".feather", ".npy", ".npz", ".pkl", ".pickle", ".h5", ".hdf5", ".log", ".patch", ".diff",
    ".example", ".sample", ".template", ".dist", ".local", ".bak", ".orig",
    # documents
    ".md", ".mdx", ".txt", ".rst", ".adoc", ".org", ".tex", ".bib", ".rtf", ".pdf", ".doc", ".docx", ".odt", ".xls",
    ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".epub", ".srt", ".vtt", ".ics",
    # images, designs and fonts
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".webp", ".avif", ".ico", ".icns", ".psd",
    ".ai", ".eps", ".fig", ".sketch", ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # audio and video
    ".wav", ".mp3", ".ogg", ".oga", ".flac", ".aac", ".m4a", ".opus", ".mid", ".midi", ".mp4", ".m4v", ".webm",
    ".mov", ".avi", ".mkv", ".3gp", ".3g2", ".264", ".265",
    # 3D, model weights and binaries
    ".obj", ".gltf", ".glb", ".stl", ".3mf", ".3ds", ".fbx", ".blend", ".dae", ".ply", ".usd", ".usdz", ".gguf", ".onnx",
    ".safetensors", ".pt", ".pth", ".ckpt", ".tflite", ".bin", ".exe", ".dll", ".so", ".dylib", ".jar", ".apk",
    ".whl", ".msi",
    # archives
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst",
})  # fmt: skip
# The ending of a version or a model size: ".7b", ".5", ".v2".
_VERSION_ENDING_RE = re.compile(r"\.(?:v\d+|\d+[a-z]?)", re.I)


def named_paths(text: str, workspace: Path | None = None) -> list[str]:
    """Keep explicit paths; resolve an unqualified prose mention to that name.

    Before files exist, 'write dashboard/quotes.json; the page reads quotes.json'
    names one output. Explicit ./quotes.json or `quotes.json` still names a
    separate root file, and two qualified paths are never collapsed.

    A path with a drive letter names a file on this machine, outside the workspace the contract checks: it is never
    returned, and a prose mention of its file name means that file (2026-09-27: "never touch the Codex auth.json
    itself" made `auth.json` an output).
    """
    on_this_machine = list(_DRIVE_PATH_RE.finditer(text))
    paths = [
        match.group(1)
        for match in _PATH_TOKEN_RE.finditer(text)
        if not any(drive.start() <= match.start(1) < drive.end() for drive in on_this_machine)
    ]
    qualified_names = {PurePosixPath(path).name for path in paths} | {drive.group(1) for drive in on_this_machine}
    paths.extend(match.group(1) for match in _BARE_DATA_FILE_RE.finditer(text) if match.group(1) not in qualified_names)
    for match in _BACKTICK_FILE_RE.finditer(text):
        name, extension = match.groups()
        if len(extension) > 8 and not has_a_file_extension(name):
            continue
        if name.lower() in _JS_LIBRARY_FILES and (workspace is None or not (workspace / name).is_file()):
            continue
        paths.append(name)
    return paths


def without_disowned(text: str) -> str:
    """*text* without the sentences and clauses that say the files they name are not outputs."""
    return " ".join(part for part in re.split(r"(?<=[.!?;])\s+", text) if not _DISOWNS.search(part))


def is_apple_bundle_path(token: str) -> bool:
    """Apple project, workspace, and asset-catalog paths name folders rather than output files."""
    return PurePosixPath(token).suffix.lower() in _APPLE_BUNDLE_EXTENSIONS


def has_a_file_extension(token: str, also: Collection[str] = ()) -> bool:
    """True when *token* ends in an extension known to be a file's: one of ``_FILE_EXTENSIONS`` or of *also*."""
    suffix = PurePosixPath(token).suffix.lower()
    return bool(suffix) and (suffix in _FILE_EXTENSIONS or suffix in also)


def ends_in_a_version(token: str, also: Collection[str] = ()) -> bool:
    """True when *token* ends in a version or a model size rather than an extension.

    The lanes ask named "damo-vilab/text-to-video-ms-1.7b" and the contract demanded a file ending ".7b"; the run
    looped on a requirement nobody set (2026-09-06). That is ".7b" or ".5" after a digit ("Qwen/Qwen2.5",
    "releases/v2.5") or ".v2" anywhere ("config/settings.v2"). Anything else stays a file: a known extension, an
    unknown one ("schema.prisma", "go.mod"), and a number after a name ("man/thomas.1", "lib/libssl.so.3").
    """
    if has_a_file_extension(token, also):
        return False
    path = PurePosixPath(token)
    if not _VERSION_ENDING_RE.fullmatch(path.suffix):
        return False
    stem = path.name[: -len(path.suffix)]
    return path.suffix[1:2].lower() == "v" or (bool(stem) and stem[-1].isdigit())


def committed_at_head(path: Path, workspace: Path) -> bool:
    """True when *path* is a file in the workspace's last commit: a file the task refers to, never one it creates.

    A path the task names that is missing from disk used to be read as an output the task will create. The contract
    is built again each turn, so a file the task was asked to delete, and did, became a required output on the next
    turn (2026-09-27: "`scripts/generate_gap_assets.py` exists and is non-empty", for a request to delete it).
    Anything git cannot answer counts as not committed, which keeps the old reading.
    """
    try:
        relative = path.resolve().relative_to(workspace.resolve()).as_posix()
    except (OSError, ValueError):
        return False
    try:
        found = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "-e", f"HEAD:./{relative}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return found.returncode == 0


def _committed_ending_with(raw: str, workspace: Path) -> Path | None:
    """The one committed file whose path ends with *raw*, folder for folder; None when none or several do.

    A task names a file by its last folders: "a status call that moved to js/chat_model_accounts.js" meant
    thomas/server/web/js/chat_model_accounts.js, five folders down, where the name search below stops at three. It
    became a new file the task had to create at the root, and a team wrote a stand-in there (2026-09-27).
    """
    try:
        listed = subprocess.run(
            ["git", "-C", str(workspace), "ls-files", "-z", "--", f"*/{raw.strip('/')}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = [name for name in listed.stdout.decode("utf-8", "replace").split("\0") if name]
    return workspace / found[0] if listed.returncode == 0 and len(found) == 1 else None


def resolve_named_path(token: str, workspace: Path) -> Path | None:
    raw = token.strip()
    if raw.startswith("~/"):
        return Path(os.path.expanduser(raw))
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    direct = workspace / raw
    if direct.exists():
        return direct
    ending = _committed_ending_with(raw, workspace) if "/" in raw.strip("/") else None
    if ending is not None:
        return ending
    name = Path(raw).name
    try:
        for depth_glob in ("*", "*/*", "*/*/*"):
            for found in workspace.glob(depth_glob):
                if found.name == name and found.is_file():
                    return found
    except OSError:
        return direct
    return direct
