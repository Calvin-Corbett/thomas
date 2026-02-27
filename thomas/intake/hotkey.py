from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import time
from dataclasses import dataclass

from PIL import Image, ImageGrab, ImageOps

from ._internal.config import ClientConfig
from ._internal.logging_setup import setup_logging
from ._internal.sender import SenderQueue, SendJob
from ._internal.utils import launch_region_snip, wait_for_new_clipboard_image

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore

logger = logging.getLogger(__name__)


def _image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    try:
        g = ImageOps.grayscale(img)
        return g
    except ImportError:
        return img


def _try_ocr(img: Image.Image, lang: str, tesseract_cmd: str = "") -> str:
    if pytesseract is None:
        return ""
    try:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        _ = pytesseract.get_tesseract_version()
    except Exception:  # REVIEWED: broad catch
        return ""
    try:
        pre = _preprocess_for_ocr(img)
        return (pytesseract.image_to_string(pre, lang=lang) or "").strip()
    except Exception:  # REVIEWED: broad catch
        logger.exception("OCR failed")
        return ""


@dataclass
class HotkeyConfig:
    endpoint: str = "/api/intake/clipboard"
    mode: str = "region"  # region|fullscreen
    snip_timeout_s: float = 12.0


class HotkeyOnly:
    """Hotkey-only intake runner.

    Note: the tray agent already registers Win+Shift+T natively. This tool is for people who want hotkey without tray.
    It triggers on *Win+Shift+T* by using Windows native hotkey registration.
    """

    def __init__(self, cfg: ClientConfig, hk: HotkeyConfig):
        self.cfg = cfg
        self.hk = hk
        self._sendq = SenderQueue()
        self._last_clip_img_hash: str | None = None
        self._listener = None

    def stop(self) -> None:
        try:
            self._sendq.stop()
        except Exception:  # REVIEWED: broad catch
            pass
        try:
            if self._listener:
                self._listener.stop()
        except Exception:  # REVIEWED: broad catch
            pass

    def _fire(self) -> None:
        try:
            self.capture_and_send()
        except Exception:  # REVIEWED: broad catch
            logger.exception("hotkey capture failed")

    def capture_and_send(self) -> None:
        img = None
        if self.hk.mode == "region" and os.name == "nt":
            prev = self._last_clip_img_hash
            launch_region_snip()
            img, new_hash = wait_for_new_clipboard_image(prev_hash=prev, timeout_s=self.hk.snip_timeout_s)
            if img is not None and new_hash:
                self._last_clip_img_hash = new_hash

        if img is None:
            try:
                img = ImageGrab.grab(all_screens=True)
            except Exception:  # REVIEWED: broad catch
                img = ImageGrab.grab()

        ocr_text = _try_ocr(img, lang=self.cfg.ocr_lang, tesseract_cmd=self.cfg.tesseract_cmd)
        png = _image_to_png_bytes(img)

        payload = {
            "source": "screenshot",
            "content_type": "image/png",
            "image_b64": base64.b64encode(png).decode("ascii"),
            "ocr_text": ocr_text or None,
            "meta": {"width": img.size[0], "height": img.size[1], "mode": self.hk.mode, "hotkey": "win+shift+t"},
        }

        url = self.cfg.server.rstrip("/") + self.hk.endpoint
        job = SendJob(
            url=url, json_payload=payload, headers=self.cfg.headers(), timeout_s=float(self.cfg.request_timeout_s)
        )
        ok = self._sendq.submit(job)
        if not ok:
            logger.warning("Send queue full; dropping screenshot")

    def run_forever(self) -> None:
        if os.name != "nt":
            raise RuntimeError(
                "Hotkey-only runner uses Windows RegisterHotKey. Use the tray agent or implement a cross-platform hotkey lib."
            )

        from ._internal.win_hotkey import MOD_SHIFT, MOD_WIN, Hotkey, HotkeyListener, vk_from_char

        hk = Hotkey(modifiers=MOD_WIN | MOD_SHIFT, vk=vk_from_char("T"))
        self._listener = HotkeyListener(hotkey=hk, on_fire=self._fire)
        self._listener.start()

        print("Listening for hotkey: Win+Shift+T (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.stop()
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Thomas hotkey-only screenshot intake (Win+Shift+T)")
    parser.add_argument("--server", default=None, help="Thomas server base URL")
    parser.add_argument("--token", default=None, help="Bearer token (optional)")
    parser.add_argument("--mode", default="region", choices=["region", "fullscreen"], help="Capture mode")
    parser.add_argument("--ocr-lang", default=None, help="Tesseract language code (default: eng)")
    parser.add_argument("--tesseract-cmd", default=None, help="Optional path to tesseract.exe")
    parser.add_argument("--log-level", default="INFO", help="DEBUG|INFO|WARNING|ERROR")
    args = parser.parse_args()

    setup_logging("intake_hotkey", level=args.log_level)

    cfg = ClientConfig.load()
    if args.server:
        cfg.server = args.server
    if args.token is not None:
        cfg.token = args.token
    if args.ocr_lang:
        cfg.ocr_lang = args.ocr_lang
    if args.tesseract_cmd is not None:
        cfg.tesseract_cmd = args.tesseract_cmd
    cfg.save()

    runner = HotkeyOnly(cfg, hk=HotkeyConfig(mode=args.mode))
    runner.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
