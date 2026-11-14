"""Build approval cards from the real bytes, and refuse if the catalogue was edited.

The catalogue (``scripts/cage/card_catalogue.py``) owns every word a Windows PIN
prompt may carry. This is the server's half:

* It checks the catalogue against its pin -- a SHA-256 in
  ``C:\\ProgramData\\ThomasPins``, writable only by Administrators -- and refuses
  every PIN flow when they differ. Changing a card's wording takes a UAC prompt.
* It loads the catalogue by path, from the very file it checked, so a module of
  the same name earlier on the import path cannot stand in for it.
* It computes a card's details from the actual content -- the diff, its hash --
  so nothing on the Windows dialog comes from the model. The model's own words
  travel with the card for the chat, labelled as his, and never reach the dialog.

Honest scope: this closes a TRICKED Thomas (the model fooled, the code intact).
Against a HACKED one, code in this process can reach around any check written
here; the commit-master and the caged server are what close that
(docs/superpowers/specs/2026-09-22-trusted-self-change-design.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import secrets
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from thomas.tools import cage_shell

_REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE_PATH = _REPO_ROOT / "scripts" / "cage" / "card_catalogue.py"
PIN_NAME = "catalogue.sha256"
_MODULE_NAME = "thomas_trusted_card_catalogue"

STATUS_OK = "ok"
STATUS_UNPINNED = "unpinned"
STATUS_TAMPERED = "tampered"

_lock = threading.Lock()
_loaded: tuple[ModuleType, str] | None = None


class CatalogueTampered(RuntimeError):
    """The card wording on disk is not the wording that was pinned."""


def catalogue_digest(path: Path = CATALOGUE_PATH) -> str:
    """SHA-256 of the file with CRLF normalised, as the pin script computes it."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def catalogue_status(path: Path = CATALOGUE_PATH, pin_root: Path | None = None) -> str:
    """ok, unpinned (never pinned on this machine) or tampered.

    A pin that exists but cannot be read, or is not a digest, is tampered: only an
    administrator can put a file there, so its presence is the decision, and an
    unreadable pin must not be the difference between a wall and nothing.
    """
    pin = Path(pin_root if pin_root is not None else cage_shell.DEFAULT_PIN_ROOT) / PIN_NAME
    if not pin.exists():
        return STATUS_UNPINNED
    try:
        pinned = pin.read_text(encoding="utf-8-sig").strip().lower()
        actual = catalogue_digest(path)
    except (OSError, ValueError):
        return STATUS_TAMPERED
    if not re.fullmatch(r"[0-9a-f]{64}", pinned):
        return STATUS_TAMPERED
    return STATUS_OK if pinned == actual else STATUS_TAMPERED


def load_catalogue() -> ModuleType:
    """The catalogue module, loaded once from CATALOGUE_PATH itself."""
    global _loaded
    with _lock:
        if _loaded is None:
            digest = catalogue_digest()
            spec = importlib.util.spec_from_file_location(_MODULE_NAME, CATALOGUE_PATH)
            if spec is None or spec.loader is None:
                raise CatalogueTampered(f"cannot load the card catalogue at {CATALOGUE_PATH}")
            module = importlib.util.module_from_spec(spec)
            # Registered before it runs: its dataclasses look themselves up there.
            sys.modules[_MODULE_NAME] = module
            spec.loader.exec_module(module)
            _loaded = (module, digest)
        return _loaded[0]


def require_trusted_catalogue(pin_root: Path | None = None) -> None:
    """Raise unless the catalogue is the pinned one and unchanged since loading."""
    status = catalogue_status(pin_root=pin_root)
    if status == STATUS_TAMPERED:
        raise CatalogueTampered(
            "the approval cards on disk do not match their pin; every PIN approval is refused until "
            "they are put back or re-pinned with scripts/cage/pin_catalogue.ps1"
        )
    if _loaded is not None and catalogue_digest() != _loaded[1]:
        raise CatalogueTampered("the approval cards changed on disk after Thomas loaded them")


@lru_cache(maxsize=4)
def _enforcement_paths(repo_root: Path) -> frozenset[str]:
    return load_catalogue().load_enforcement_paths(repo_root)


@dataclass(frozen=True)
class TrustedCard:
    kind: str
    details: dict[str, str]
    content_hash: str
    nonce: str
    code: str
    title: str
    body: str
    danger: str | None = None
    excerpt: str = ""
    # The model's own words: shown on the chat card, labelled as his, and never
    # passed to the Windows dialog.
    why: str = field(default="", compare=False)

    def dialog(self) -> tuple[str, str]:
        """(action, reason) for the Windows prompt. No model text, ever."""
        reason = f"Pairing code {self.code}. It must match the card in Thomas's chat."
        if self.danger:
            reason += f"\n\nThis touches {self.danger}. It gets its own approval every time."
        return f"{self.title}\n\n{self.body}", reason


def protected_write_card(
    rel_path: str,
    before: str | None,
    after: str,
    *,
    why: str = "",
    existed: bool = False,
    repo_root: Path = _REPO_ROOT,
) -> TrustedCard:
    """The card for writing *after* over *before* at *rel_path*.

    ``existed`` says the file was there but could not be read as text, so the card
    does not call it new.
    """
    cat = load_catalogue()
    lines = cat.diff_lines(before, after)
    if before is None and existed:
        stat = f"replaces a file that could not be read as text, with {len(after.splitlines())} line(s)"
    else:
        stat = cat.diffstat(before, after)
    details = {"path": str(rel_path).replace("\\", "/"), "diffstat": stat}
    title, body = cat.render("protected_write", details)
    digest = cat.content_hash(after)
    nonce = secrets.token_hex(8)
    added = "\n".join(line for line in lines if line.startswith("+") and not line.startswith("+++"))
    return TrustedCard(
        kind="protected_write",
        details=details,
        content_hash=digest,
        nonce=nonce,
        code=cat.pairing_code("protected_write", details, digest, nonce),
        title=title,
        body=body,
        danger=cat.danger_class(details["path"], added_diff=added, enforcement_paths=_enforcement_paths(repo_root)),
        excerpt=cat.diff_excerpt(before, after),
        why=why,
    )


__all__ = [
    "CATALOGUE_PATH",
    "PIN_NAME",
    "STATUS_OK",
    "STATUS_TAMPERED",
    "STATUS_UNPINNED",
    "CatalogueTampered",
    "TrustedCard",
    "catalogue_digest",
    "catalogue_status",
    "load_catalogue",
    "protected_write_card",
    "require_trusted_catalogue",
]
