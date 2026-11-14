"""Reuse immutable Git reads inside one shared-card test, never mutable ref/index reads."""

from __future__ import annotations

import copy
import os
import re
import shutil
from pathlib import Path

_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def _object(spec: str) -> bool:
    return bool(_OID.fullmatch(spec.split(":", 1)[0]))


def _command(args):
    if not isinstance(args, (list, tuple)) or not args or Path(args[0]).stem.lower() != "git":
        return []
    index = 1
    while index < len(args):
        if args[index] == "-c" and index + 1 < len(args):
            name = args[index + 1].partition("=")[0].lower()
            if name not in {"user.name", "user.email", "core.autocrlf"}:
                return []
            index += 2
        else:
            return args[index:]
    return []


def _immutable(command, stdin) -> bool:
    if not command:
        return False
    pinned_attributes = command[0].startswith("--attr-source=")
    if pinned_attributes:
        if not _OID.fullmatch(command[0].split("=", 1)[1]):
            return False
        command = command[1:]
        if not command:
            return False
    name, *args = command
    if name == "cat-file":
        if args in (["--batch-check"], ["--batch-check=%(objectname)"]):
            if isinstance(stdin, bytes):
                stdin = stdin.decode("utf-8", errors="replace")
            return bool(stdin) and all(_object(line) for line in stdin.splitlines())
        return len(args) == 2 and args[0] == "blob" and _object(args[1])
    if name == "show":
        return len(args) == 1 and ":" in args[0] and _object(args[0])
    if name == "rev-parse":
        return len(args) == 3 and args[:2] == ["--verify", "--quiet"] and ":" in args[2] and _object(args[2])
    allowed = {
        "ls-tree": {"-r", "-z", "--name-only"},
        "diff-tree": {"-r", "-z", "--no-renames", "--raw", "--name-status", "--no-commit-id", "--name-only"},
        "diff": {
            "--no-textconv",
            "--no-ext-diff",
            "--no-color",
            "--numstat",
            "--binary",
            "--full-index",
            "--text",
            "--no-renames",
        },
    }
    if name not in allowed:
        return False
    # Only explicit paths after -- may follow the pinned object operands.
    operands = args[: args.index("--")] if "--" in args else args
    positional = []
    for arg in operands:
        if arg.startswith("-"):
            if arg not in allowed[name]:
                return False
        else:
            positional.append(arg)
    if name == "diff" and (not pinned_attributes or not {"--no-textconv", "--no-ext-diff"}.issubset(args)):
        return False
    count = 1 if name == "ls-tree" else 2
    return len(positional) == count and all(_OID.fullmatch(arg) for arg in positional)


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def settings_key(repo: Path, env):
    home = Path(env.get("HOME", str(Path.home())))
    git_dir = repo / ".git"
    packed = git_dir / "packed-refs"
    if (
        not git_dir.is_dir()
        or any((git_dir / path).exists() for path in ("refs/replace", "info/grafts", "shallow"))
        or (packed.is_file() and b"refs/replace/" in packed.read_bytes())
    ):
        return None
    global_dir = Path(env.get("XDG_CONFIG_HOME", str(home / ".config"))) / "git"
    paths = [
        git_dir / "config",
        Path(env.get("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))),
        global_dir / "config",
        git_dir / "config.worktree",
        git_dir / "info/attributes",
        global_dir / "attributes",
        global_dir / "ignore",
    ]
    settings = tuple(path.read_bytes() if path.is_file() else b"" for path in paths)
    external = re.compile(rb"\[\s*include|attributesfile|excludesfile|orderfile|\[\s*filter\b", re.IGNORECASE)
    # Global config bytes are above; template paths affect init, not these reads or patches.
    inherited = tuple(
        sorted(
            (k, v)
            for k, v in env.items()
            if k.startswith("GIT_") and k not in {"GIT_CONFIG_GLOBAL", "GIT_TEMPLATE_DIR"}
        )
    )
    if (
        env.get("GIT_CONFIG_NOSYSTEM") != "1"
        or any(external.search(content) for content in settings[:4])
        or any(k.startswith("GIT_CONFIG_KEY_") or k == "GIT_CONFIG_PARAMETERS" for k, _ in inherited)
    ):
        return None
    return settings, inherited


class GitReads:
    def __init__(self, real_run):
        self.real_run = real_run
        self.cache = {}
        git = shutil.which("git")
        direct = Path(git).parent.parent / "mingw64" / "bin" / "git.exe" if git else None
        self.executable = str(direct) if os.name == "nt" and direct and direct.is_file() else None

    def __call__(self, args, *pos, **kwargs):
        command = _command(args)
        key = None
        if not pos and kwargs.get("capture_output") and _immutable(command, kwargs.get("input")):
            repo = Path(kwargs.get("cwd", "."))
            git_dir = repo / ".git"
            packed = git_dir / "packed-refs"
            rewritten = (
                any((git_dir / path).exists() for path in ("refs/replace", "info/grafts", "shallow"))
                or (packed.is_file() and b"refs/replace/" in packed.read_bytes())
                or not git_dir.is_dir()
            )
            if rewritten:
                return self.real_run(args, *pos, **kwargs)
            env = kwargs.get("env", os.environ)
            settings = settings_key(repo, env)
            if settings is None or any(
                re.match(r"(?:include(?:if)?[.\s]|core\.attributesfile=)", str(arg), re.I) for arg in args[1:]
            ):
                return self.real_run(args, *pos, **kwargs)
            key = (_freeze(args), _freeze(kwargs), settings)
            if key in self.cache:
                return copy.deepcopy(self.cache[key])
        actual = [self.executable, *args[1:]] if command and self.executable else args
        result = self.real_run(actual, *pos, **kwargs)
        output = result.stdout
        missing = b" missing" if isinstance(output, bytes) else " missing"
        negative_batch = (
            "cat-file" in command
            and any(arg.startswith("--batch-check") for arg in command)
            and output
            and any(line.endswith(missing) for line in output.splitlines())
        )
        if key is not None and result.returncode == 0 and not negative_batch:
            self.cache[key] = copy.deepcopy(result)
        return result
