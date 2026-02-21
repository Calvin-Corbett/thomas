from __future__ import annotations

import argparse
import base64
import hashlib
import io
import logging
import os
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageGrab

from ._internal.config import ClientConfig
from ._internal.logging_setup import setup_logging
from ._internal.sender import SenderQueue, SendJob
from ._internal.utils import launch_region_snip, wait_for_new_clipboard_image
from ._internal.win_clipboard_read import read_clipboard_text

try:
    import pystray  # type: ignore
except Exception:  # pragma: no cover
    pystray = None  # type: ignore


logger = logging.getLogger(__name__)


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _get_image_from_clipboard() -> Optional[Image.Image]:
    try:
        grabbed = ImageGrab.grabclipboard()
        if isinstance(grabbed, Image.Image):
            return grabbed
        return None
    except Exception:
        return None


def _make_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(18, 18, 18, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
    d.text((24, 14), "T", font=font, fill=(245, 245, 245, 255))
    return img


class ThomasIntakeAgent:
    """Tray agent that watches clipboard and runs native hotkey for screenshots."""

    def __init__(self, cfg: ClientConfig):
        self.cfg = cfg
        self._stop = threading.Event()
        self._paused = threading.Event()

        self._sendq = SenderQueue()
        self._clip_event = threading.Event()
        self._listener = None
        self._hotkey_listener = None

        self._last_text_hash: Optional[str] = None
        self._last_img_hash: Optional[str] = None
        self._last_clip_img_hash_for_snip: Optional[str] = None

    def start(self) -> None:
        self._start_clipboard_listener()
        self._start_hotkey_listener()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sendq.stop()
        except Exception:
            pass
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass
        try:
            if self._hotkey_listener:
                self._hotkey_listener.stop()
        except Exception:
            pass

    def toggle_pause(self) -> None:
        if self._paused.is_set():
            self._paused.clear()
        else:
            self._paused.set()

    def toggle_send_text(self) -> None:
        self.cfg.send_text = not self.cfg.send_text
        self.cfg.save()

    def toggle_send_images(self) -> None:
        self.cfg.send_images = not self.cfg.send_images
        self.cfg.save()

    def toggle_screenshot_mode(self) -> None:
        self.cfg.screenshot_mode = "fullscreen" if self.cfg.screenshot_mode == "region" else "region"
        self.cfg.save()

    def _start_clipboard_listener(self) -> None:
        if os.name != "nt":
            logger.info("Non-Windows OS; clipboard listener uses polling fallback.")
            return
        try:
            from ._internal.win_clipboard_listener import ClipboardListener

            self._listener = ClipboardListener(on_update=self._on_clip_update)
            self._listener.start()
            logger.info("Clipboard listener active (event-driven).")
        except Exception:
            self._listener = None
            logger.info("Clipboard listener unavailable; will poll.")

    def _start_hotkey_listener(self) -> None:
        if os.name != "nt":
            logger.info("Non-Windows OS; hotkey listener disabled.")
            return
        try:
            from ._internal.win_hotkey import HotkeyListener, Hotkey, MOD_WIN, MOD_SHIFT, vk_from_char

            hk = Hotkey(modifiers=MOD_WIN | MOD_SHIFT, vk=vk_from_char("T"))
            self._hotkey_listener = HotkeyListener(hotkey=hk, on_fire=self._on_hotkey)
            self._hotkey_listener.start()
            logger.info("Hotkey listener active: Win+Shift+T")
        except Exception:
            self._hotkey_listener = None
            logger.info("Hotkey listener unavailable.")

    def _on_clip_update(self) -> None:
        self._clip_event.set()

    def _on_hotkey(self) -> None:
        # Trigger screenshot flow
        try:
            self.capture_screenshot_and_send()
        except Exception:
            logger.exception("Screenshot capture failed")

    def capture_screenshot_and_send(self) -> None:
        if self.cfg.screenshot_mode == "region" and os.name == "nt":
            # Launch snip overlay and wait for new clipboard image
            prev = self._last_clip_img_hash_for_snip
            launch_region_snip()
            img, new_hash = wait_for_new_clipboard_image(prev_hash=prev, timeout_s=12.0)
            if img is not None:
                self._last_clip_img_hash_for_snip = new_hash
                self._send_image(img, source="screenshot", meta={"mode": "region", "hotkey": "win+shift+t"})
                return

        # Fallback fullscreen
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            img = ImageGrab.grab()
        self._send_image(img, source="screenshot", meta={"mode": "fullscreen", "hotkey": "win+shift+t"})

    def _loop(self) -> None:
        logger.info("Thomas intake agent running. send_text=%s send_images=%s mode=%s", self.cfg.send_text, self.cfg.send_images, self.cfg.screenshot_mode)
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.25)
                continue

            if self._listener is not None:
                self._clip_event.wait(timeout=2.0)
                self._clip_event.clear()
            else:
                time.sleep(max(0.15, float(self.cfg.poll_interval_s)))

            try:
                self._check_clipboard_once()
            except Exception:
                logger.exception("Clipboard processing failed")

    def _check_clipboard_once(self) -> None:
        # Images first
        if self.cfg.send_images:
            img = _get_image_from_clipboard()
            if img is not None:
                png = _image_to_png_bytes(img)
                h = _hash_bytes(png)
                if h != self._last_img_hash:
                    self._last_img_hash = h
                    self._send_image(img, source="clipboard", meta={"width": img.size[0], "height": img.size[1]})
                    return

        if self.cfg.send_text:
            text = None
            if os.name == "nt":
                try:
                    text = read_clipboard_text()
                except Exception:
                    text = None
            if not text:
                # fallback to pyperclip/tk if user wants; we keep it minimal here.
                pass
            if text:
                ht = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                if ht != self._last_text_hash:
                    self._last_text_hash = ht
                    payload = {"source": "clipboard", "content_type": "text/plain", "text": text, "meta": {}}
                    self._submit(payload)

    def _send_image(self, img: Image.Image, source: str, meta: dict) -> None:
        # OCR happens in the hotkey-only script (optional). Tray agent sends image w/o OCR for speed.
        png = _image_to_png_bytes(img)
        payload = {
            "source": source,
            "content_type": "image/png",
            "image_b64": base64.b64encode(png).decode("ascii"),
            "ocr_text": None,
            "meta": {"width": img.size[0], "height": img.size[1], **(meta or {})},
        }
        self._submit(payload)

    def _submit(self, payload: dict) -> None:
        url = self.cfg.server.rstrip("/") + "/api/intake/clipboard"
        job = SendJob(url=url, json_payload=payload, headers=self.cfg.headers(), timeout_s=float(self.cfg.request_timeout_s))
        ok = self._sendq.submit(job)
        if not ok:
            logger.warning("Send queue full; dropping intake event.")

    @staticmethod
    def install_startup() -> None:
        if os.name != "nt":
            raise RuntimeError("Startup install is only supported on Windows.")
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            exe = sys.executable
            cmd = f'"{exe}" -m thomas.intake.clipboard_watcher'
            winreg.SetValueEx(key, "ThomasIntakeAgent", 0, winreg.REG_SZ, cmd)

    @staticmethod
    def uninstall_startup() -> None:
        if os.name != "nt":
            raise RuntimeError("Startup uninstall is only supported on Windows.")
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, "ThomasIntakeAgent")
            except FileNotFoundError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Thomas Intake Tray Agent (clipboard + hotkey)")
    parser.add_argument("--server", default=None, help="Thomas server base URL")
    parser.add_argument("--token", default=None, help="Bearer token (optional)")
    parser.add_argument("--no-tray", action="store_true", help="Console-only mode (no tray)")
    parser.add_argument("--install-startup", action="store_true", help="Install autorun at login (Windows)")
    parser.add_argument("--uninstall-startup", action="store_true", help="Remove autorun at login (Windows)")
    parser.add_argument("--log-level", default="INFO", help="DEBUG|INFO|WARNING|ERROR")
    args = parser.parse_args()

    setup_logging("intake_agent", level=args.log_level)

    if args.install_startup:
        ThomasIntakeAgent.install_startup()
        print("Installed startup: ThomasIntakeAgent")
        return 0
    if args.uninstall_startup:
        ThomasIntakeAgent.uninstall_startup()
        print("Removed startup: ThomasIntakeAgent")
        return 0

    cfg = ClientConfig.load()
    if args.server:
        cfg.server = args.server
    if args.token is not None:
        cfg.token = args.token
    cfg.save()

    agent = ThomasIntakeAgent(cfg)
    agent.start()

    if args.no_tray or pystray is None:
        print("Running without tray. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            agent.stop()
        return 0

    icon_img = _make_icon()

    def _open_config(icon, item):  # type: ignore[no-untyped-def]
        p = str(ClientConfig.path())
        try:
            os.startfile(p)  # type: ignore[attr-defined]
        except Exception:
            webbrowser.open(f"file:///{p}")

    def _open_state_dir(icon, item):  # type: ignore[no-untyped-def]
        d = str(ClientConfig.path().parent)
        try:
            os.startfile(d)  # type: ignore[attr-defined]
        except Exception:
            webbrowser.open(f"file:///{d}")

    def _toggle_pause(icon, item):  # type: ignore[no-untyped-def]
        agent.toggle_pause()

    def _toggle_text(icon, item):  # type: ignore[no-untyped-def]
        agent.toggle_send_text()

    def _toggle_images(icon, item):  # type: ignore[no-untyped-def]
        agent.toggle_send_images()

    def _toggle_mode(icon, item):  # type: ignore[no-untyped-def]
        agent.toggle_screenshot_mode()

    def _quit(icon, item):  # type: ignore[no-untyped-def]
        agent.stop()
        icon.stop()

    menu = pystray.Menu(  # type: ignore[attr-defined]
        pystray.MenuItem("Pause/Resume", _toggle_pause),
        pystray.MenuItem("Toggle send text", _toggle_text),
        pystray.MenuItem("Toggle send images", _toggle_images),
        pystray.MenuItem("Toggle screenshot mode (region/fullscreen)", _toggle_mode),
        pystray.MenuItem("Open config", _open_config),
        pystray.MenuItem("Open state dir", _open_state_dir),
        pystray.MenuItem("Install startup", lambda i, x: ThomasIntakeAgent.install_startup()),
        pystray.MenuItem("Uninstall startup", lambda i, x: ThomasIntakeAgent.uninstall_startup()),
        pystray.MenuItem("Quit", _quit),
    )

    icon = pystray.Icon("ThomasIntakeAgent", icon_img, "Thomas Intake Agent", menu)  # type: ignore[attr-defined]
    icon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
