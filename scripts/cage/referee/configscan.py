"""Classify the keys of a repository's own config: neutralise what can run a command, allow the harmless, refuse the rest.

``classify(name)`` takes a key name as git lists it (``git config --list --name-only``: section and key lower-case,
subsection exactly as written, possibly containing dots or quotes) and answers one of three things.

* ``("override", value)``: the key can make git run a command or change what runs. The runner passes
  ``-c <name>=<value>`` for it, which beats the repository's own value. (A filter or driver command becomes empty,
  ``required`` becomes false, a hooks path becomes the referee's empty folder.)
* ``("allow", "")``: a known harmless family, no override needed.
* ``("refuse", reason)``: unknown, or one that pulls in unseen files or moves the work tree. Nothing runs.

Aliases are allowed: git never lets an alias shadow a built-in, and the referee always names a built-in.
"""

from __future__ import annotations

import os

CORE_ALLOWED = {
    "repositoryformatversion",
    "filemode",
    "bare",
    "logallrefupdates",
    "symlinks",
    "ignorecase",
    "precomposeunicode",
    "autocrlf",
    "safecrlf",
    "eol",
    "longpaths",
}
CORE_EMPTY = {"pager", "editor", "sshcommand", "askpass"}  # programs git may start: set to nothing
ALLOWED_SECTIONS = {"remote", "branch", "user", "lfs", "gc", "pack", "index", "submodule", "url", "alias"}
FILTER_EMPTY = {"clean", "smudge", "process"}
DIFF_EMPTY = {"textconv", "command"}


def split_name(name: str) -> tuple[str, str, str]:
    """``(section, subsection, key)``; the subsection is everything between the first and the last dot."""
    section, _, rest = name.partition(".")
    middle, _, key = rest.rpartition(".")
    return section.lower(), middle, key.lower()


def classify(name: str, hooks_dir: str) -> tuple[str, str]:
    section, sub, key = split_name(name)
    if section in ("include", "includeif"):
        return "refuse", "it pulls in files the referee has not seen"
    if section == "core":
        if sub:
            return "refuse", "an unknown core key"
        if key == "worktree":
            return "refuse", "it moves the work tree"
        if key == "hookspath":
            return "override", hooks_dir
        if key == "fsmonitor":
            return "override", "false"
        if key == "attributesfile":
            return "override", os.devnull
        if key in CORE_EMPTY:
            return "override", ""
        if key in CORE_ALLOWED:
            return "allow", ""
    elif section == "filter" and sub:
        if key in FILTER_EMPTY:
            return "override", ""
        if key == "required":
            return "override", "false"
    elif section == "diff":
        if key == "external" and not sub:
            return "override", ""
        if sub and key in DIFF_EMPTY:
            return "override", ""
        if sub and key == "cachetextconv":
            return "override", "false"
    elif section == "merge" and sub and key == "driver" or section == "credential" and key == "helper":
        return "override", ""
    elif section == "gpg":
        return ("override", "") if key == "program" or key.endswith("command") else ("allow", "")
    elif section in ("commit", "tag") and key == "gpgsign" and not sub:
        return "override", "false"
    elif section in ALLOWED_SECTIONS:
        return "allow", ""
    return "refuse", "an unknown key"


def scan(names: list[str], hooks_dir: str) -> tuple[list[str], list[str]]:
    """``-c`` override arguments for the keys present, and the refusals (each names its key and why)."""
    overrides: dict[str, str] = {}
    refusals: list[str] = []
    for name in names:
        # ``git -c name=value`` splits at the first ``=`` and cannot carry a newline: it cannot say such a key
        if any(c in name for c in "=" + chr(10) + chr(0)):
            refusals.append(f"config key {name!r}: its name holds a character git -c cannot express")
            continue
        verdict, value = classify(name, hooks_dir)
        if verdict == "override":
            overrides[name] = value
        elif verdict == "refuse":
            refusals.append(f"config key {name}: {value}")
    return [arg for k, v in overrides.items() for arg in ("-c", f"{k}={v}")], refusals
