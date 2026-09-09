"""Repository-defined slash commands for the Thomas REPL.

Commands are markdown files discovered at runtime from the working repo:

- ``.thomas/commands/<name>.md`` (primary source)
- ``.claude/commands/<name>.md`` (compatible fallback, mirroring the Claude
  Code convention so existing muscle memory transfers)

On a name collision ``.thomas`` wins over ``.claude``, and built-in REPL
commands always win over repo-defined ones (enforced by the resolver in
``thomas.cli.repl_slash``).

File format: optional YAML-style frontmatter (``description`` and
``argument-hint`` keys) followed by the prompt template body. The template
supports ``$ARGUMENTS`` (all arguments as one string) and ``$1``..``$9``
positional substitution. If arguments are supplied but the template contains
no placeholder, the arguments are appended to the rendered prompt.

Malformed definition files degrade to a warning in the scan result — they
never raise out of discovery.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Precedence order: earlier directories win name collisions.
COMMAND_DIR_SOURCES: tuple[tuple[str, str], ...] = (
    (".thomas", ".thomas/commands"),
    (".claude", ".claude/commands"),
)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_PLACEHOLDER_RE = re.compile(r"\$(ARGUMENTS|[1-9])(?!\d)")
_MAX_COMMAND_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class RepoCommand:
    """A repository-defined slash command loaded from a markdown file."""

    name: str
    template: str
    description: str = ""
    argument_hint: str = ""
    source: str = ""
    origin: str = ""

    @property
    def command(self) -> str:
        """The slash token for this command, e.g. ``/deploy``."""
        return f"/{self.name}"

    @property
    def usage(self) -> str:
        """Usage string for help listings, e.g. ``/deploy <env>``."""
        return f"{self.command} {self.argument_hint}".strip()


@dataclass(frozen=True)
class RepoCommandScan:
    """Result of scanning the repo for command definition files."""

    commands: tuple[RepoCommand, ...] = ()
    warnings: tuple[str, ...] = ()


# Cache keyed by resolved root -> (directory signature, scan result).
_SCAN_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], RepoCommandScan]] = {}


def _command_files(root: Path) -> list[tuple[str, Path]]:
    """Return (origin, path) pairs for every candidate definition file."""
    found: list[tuple[str, Path]] = []
    for origin, rel_dir in COMMAND_DIR_SOURCES:
        directory = root / rel_dir
        try:
            if not directory.is_dir():
                continue
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            log.debug("Cannot list repo command dir %s: %s", directory, exc)
            continue
        for path in entries:
            try:
                if path.suffix.lower() == ".md" and path.is_file():
                    found.append((origin, path))
            except OSError as exc:
                log.debug("Cannot stat repo command file %s: %s", path, exc)
    return found


def _signature(files: list[tuple[str, Path]]) -> tuple[tuple[str, int, int], ...]:
    """A cheap change signature: (path, mtime_ns, size) per definition file."""
    rows: list[tuple[str, int, int]] = []
    for _origin, path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(rows)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str, str]:
    """Split optional ``---`` frontmatter from *text*.

    Returns ``(meta, body, error)``; *error* is non-empty when the
    frontmatter block is malformed.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, ""
    end_index = 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index == 0:
        return {}, "", "unterminated frontmatter block (missing closing '---')"
    meta: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            return {}, "", f"invalid frontmatter line (expected 'key: value'): {stripped!r}"
        key, _, value = stripped.partition(":")
        normalized_key = key.strip().lower().replace("_", "-")
        meta[normalized_key] = value.strip().strip("'\"")
    body = "\n".join(lines[end_index + 1 :])
    return meta, body, ""


def _load_command_file(origin: str, path: Path) -> tuple[RepoCommand | None, str]:
    """Parse one definition file into ``(command, warning)``."""
    label = f"{origin}/commands/{path.name}"
    name = path.stem.strip().lower()
    if not _NAME_RE.match(name):
        return None, f"{label}: invalid command name {path.stem!r} (use letters, digits, '.', '_', '-')"
    try:
        if path.stat().st_size > _MAX_COMMAND_FILE_BYTES:
            return None, f"{label}: file too large (max {_MAX_COMMAND_FILE_BYTES // 1024} KiB)"
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{label}: unreadable ({type(exc).__name__}: {exc})"
    meta, body, error = _parse_frontmatter(text)
    if error:
        return None, f"{label}: {error}"
    template = body.strip()
    if not template:
        return None, f"{label}: empty prompt template"
    return (
        RepoCommand(
            name=name,
            template=template,
            description=str(meta.get("description", "")).strip(),
            argument_hint=str(meta.get("argument-hint", "")).strip(),
            source=str(path),
            origin=origin,
        ),
        "",
    )


def discover_repo_commands(root: Path | None = None) -> RepoCommandScan:
    """Scan the working repo for command definitions.

    Live-reads with a cheap mtime/size cache, so newly added files are
    discoverable without a REPL restart. Never raises: malformed or
    unreadable files are reported via ``RepoCommandScan.warnings``.
    """
    try:
        base = (root or Path.cwd()).resolve()
    except OSError as exc:
        log.debug("Cannot resolve repo command root: %s", exc)
        return RepoCommandScan()
    files = _command_files(base)
    signature = _signature(files)
    cache_key = str(base)
    cached = _SCAN_CACHE.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    commands: dict[str, RepoCommand] = {}
    warnings: list[str] = []
    for origin, path in files:
        command, warning = _load_command_file(origin, path)
        if command is None:
            warnings.append(warning)
            continue
        existing = commands.get(command.name)
        if existing is not None:
            # Earlier sources win (.thomas over .claude); same-source dupes
            # cannot happen because names come from unique file stems.
            log.debug(
                "Repo command %s from %s shadowed by %s",
                command.command,
                command.source,
                existing.source,
            )
            continue
        commands[command.name] = command

    scan = RepoCommandScan(
        commands=tuple(sorted(commands.values(), key=lambda c: c.name)),
        warnings=tuple(warnings),
    )
    _SCAN_CACHE[cache_key] = (signature, scan)
    return scan


def find_repo_command(token: str, root: Path | None = None) -> RepoCommand | None:
    """Return the repo command exactly matching *token* (``/name`` or ``name``)."""
    name = str(token or "").strip().lower().lstrip("/")
    if not name:
        return None
    for command in discover_repo_commands(root).commands:
        if command.name == name:
            return command
    return None


def split_repo_command_args(args: str) -> list[str]:
    """Split an argument string into positional parameters ($1..$9).

    Quotes group words ("hello world" is one parameter); backslashes are kept
    literal so Windows paths survive splitting.
    """
    text = str(args or "").strip()
    if not text:
        return []
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    lexer.escapedquotes = ""
    try:
        return list(lexer)
    except ValueError:
        return text.split()


def render_repo_command(command: RepoCommand, args: str) -> str:
    """Render *command*'s template with the given argument string.

    ``$ARGUMENTS`` expands to the full argument string; ``$1``..``$9`` expand
    to positional parameters (empty string when missing). When arguments are
    supplied but the template has no placeholder, they are appended.
    """
    all_args = str(args or "").strip()
    positional = split_repo_command_args(all_args)

    def _substitute(match: re.Match[str]) -> str:
        token = match.group(1)
        if token == "ARGUMENTS":
            return all_args
        index = int(token) - 1
        return positional[index] if index < len(positional) else ""

    rendered, substitutions = _PLACEHOLDER_RE.subn(_substitute, command.template)
    if all_args and substitutions == 0:
        rendered = f"{rendered}\n\n{all_args}"
    return rendered.strip()


async def dispatch_repo_command(repl: object, command: RepoCommand, args: str) -> None:
    """Render *command* and dispatch it as a normal typed user message.

    Mirrors the ``/skill`` handler: show the rendered prompt as the user
    turn, then hand it to the same agent-turn path plain chat text takes.
    """
    rendered = render_repo_command(command, args)
    console = getattr(repl, "_console", None)
    if console is not None:
        from rich.panel import Panel
        from rich.text import Text

        console.print(f"[dim]Running repo command: {command.command} ({command.origin})[/dim]")
        console.print(Panel(Text(rendered[:500]), title="USER", border_style="bright_blue", expand=True))
    await repl._run_agent_turn(rendered)
