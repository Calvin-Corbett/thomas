from __future__ import annotations

import subprocess
import time

from PIL import Image, ImageGrab


def launch_region_snip() -> None:
    """Launch Windows snipping overlay (region selection) via ms-screenclip:."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "ms-screenclip:"], shell=False)
    except ImportError:
        pass


def try_grab_clipboard_image() -> Image.Image | None:
    try:
        grabbed = ImageGrab.grabclipboard()
        if isinstance(grabbed, Image.Image):
            return grabbed
        return None
    except ImportError:
        return None


def wait_for_new_clipboard_image(
    prev_hash: str | None, timeout_s: float = 10.0, poll_s: float = 0.15
) -> tuple[Image.Image | None, str | None]:
    import hashlib
    import io

    end = time.time() + timeout_s
    while time.time() < end:
        img = try_grab_clipboard_image()
        if img is not None:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b = buf.getvalue()
            h = hashlib.sha256(b).hexdigest()
            if h != prev_hash:
                return img, h
        time.sleep(poll_s)
    return None, None
