"""Turn a thomas.toml that will not parse into one line that names the file.

tomllib's own message says only "Invalid statement (at line 1, column 1)". A typo
in the file used to end in a Python traceback that never named it, and
``thomas doctor`` -- the command every recovery message points to -- died on the
same line before it could say anything.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from thomas.core.boot_checks import check_config_file, config_file_path
from thomas.core.config import AppConfig, load_config

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - python 3.10 ships tomli as a dependency
    import tomli as tomllib

# Commands that still have to run when the config is broken, because reporting
# the breakage is their job.
RUNS_ON_DEFAULTS = frozenset({"doctor"})


def load_config_or_message(path: Path | None, **kwargs: Any) -> tuple[AppConfig, str]:
    """Load the config.

    On a parse error return the built-in defaults and ``"<file>: <reason> (at line N, column M)"``.
    """
    try:
        return load_config(path, **kwargs), ""
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        _check, status, detail = check_config_file(config_file_path(Path.cwd(), path))
        if status != "fail":
            raise
        # An empty file parses to no settings at all, which is exactly the defaults.
        return load_config(Path(os.devnull), **kwargs), detail


def load_config_or_exit(ctx: Any, path: Path | None, **kwargs: Any) -> AppConfig:
    """Load the config for the CLI group and put it, and any parse error, on ``ctx.obj``.

    ``thomas doctor`` runs on the defaults and reports the error itself; every other command
    stops here with one line naming the file (exit 2).
    """
    config, error = load_config_or_message(path, **kwargs)
    if error and ctx.invoked_subcommand not in RUNS_ON_DEFAULTS:
        print(f"Error: {error}. Fix that file, or move it aside to run on built-in defaults.", file=sys.stderr)
        ctx.exit(2)
    ctx.obj["config"] = config
    ctx.obj["config_error"] = error
    return config
