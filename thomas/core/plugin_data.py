"""Where a marketplace plugin keeps what you made with it, so removing the plugin never removes that.

A plugin's code is installed to ``<memory root>/.thomas/plugins/<id>/``. Installing, updating and uninstalling all
delete that whole folder. Paper Trading and Life Manager also saved their state inside it, so uninstalling one deleted
your tasks, proposals and saved keys along with the code, and installing it again started you from nothing.

What you made lives in ``<memory root>/.thomas/plugin-data/<id>/`` instead, which nothing deletes. Anything still in
the old place is moved across the first time it is asked for, and again just before the install folder is removed, so
a plugin you have not opened since this change keeps its data too.

Standard library only: the plugins under ``thomas/marketplace`` and the server both call this.
"""

from __future__ import annotations

import os
from pathlib import Path

_INSTALLED = Path(".thomas") / "plugins"
_DATA = Path(".thomas") / "plugin-data"
# Every installed plugin has this one, and it is the plugin's own description, not something you made.
_NOT_DATA = {"manifest.json"}


def keep_plugin_data(installed_dir: Path, data_dir: Path) -> list[str]:
    """Move the saved files out of an install folder. Returns the names moved.

    A saved file is a ``.json`` file at the top of the install folder other than the manifest: that is where state,
    saved keys and simulated positions were written. A file already in ``data_dir`` is the newer one and is left alone.
    A file that cannot be moved raises ``OSError``, so a caller about to delete the folder stops instead.
    """
    if not installed_dir.is_dir():
        return []
    moved: list[str] = []
    for saved in sorted(installed_dir.iterdir()):
        if not saved.is_file() or saved.suffix != ".json" or saved.name in _NOT_DATA:
            continue
        target = data_dir / saved.name
        if target.exists():
            continue
        data_dir.mkdir(parents=True, exist_ok=True)
        os.replace(saved, target)
        moved.append(saved.name)
    return moved


def data_dir_beside(installed_dir: Path) -> Path:
    """The data folder that belongs to an install folder: ``.thomas/plugins/<id>`` -> ``.thomas/plugin-data/<id>``."""
    return installed_dir.parent.parent / _DATA.name / installed_dir.name


def plugin_data_dir(memory_root: Path | str, plugin_id: str) -> Path:
    """The folder a plugin saves to, with anything left in the old place moved into it first."""
    root = Path(memory_root)
    data_dir = root / _DATA / plugin_id
    keep_plugin_data(root / _INSTALLED / plugin_id, data_dir)
    return data_dir
