"""Native local-folder picker used by the project-link route."""

from __future__ import annotations

import logging

from aiohttp import web

log = logging.getLogger(__name__)


def pick_folder_via_dialog() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise web.HTTPConflict(text="local folder picker is not available on this machine") from exc

    root = None
    selected = ""
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except (tk.TclError, RuntimeError):
            pass
        selected = filedialog.askdirectory(title="Choose a project folder for Thomas", mustexist=True)
    except (OSError, RuntimeError, tk.TclError) as exc:  # pragma: no cover - platform dependent
        log.exception("Local folder picker failed")
        raise web.HTTPConflict(text="could not open the local folder picker") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except (RuntimeError, tk.TclError):
                pass
    return str(selected or "").strip()
