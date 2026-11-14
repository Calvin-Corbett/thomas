"""What the canary does on an alarm: tell you, hold, and put the revert on your card; and lift what it set.

Only existing switches: the express window's ``off`` file (every change then goes to a card), an active-folder claim on
the watched folders (``commit.py`` and plain commits to them refuse), and a ``self-*`` hand-in in the promoter's inbox
in the format the caged server writes (thomas/server/green_handoff.py). The revert skips the check before your card,
which may be what broke; the promoter still runs its own checks and asks you on one card.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.pipeline_canary.canary import WATCHED

AGENT = "pipeline-canary"
OFF_TEXT = "off: the pipeline canary turned the window off after an alarm"
CLAIM_TTL_S = 3 * 24 * 3600
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
[void]$text.Item(0).AppendChild($xml.CreateTextNode($env:CANARY_TITLE))
[void]$text.Item(1).AppendChild($xml.CreateTextNode($env:CANARY_BODY))
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""
log = logging.getLogger(__name__)


def cage_root() -> Path:
    return Path(os.environ.get("THOMAS_CAGE_ROOT") or r"C:\ProgramData\ThomasCage")


def toast(title: str, body: str) -> None:
    """A Windows notification, through Windows PowerShell."""
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
        env={**os.environ, "CANARY_TITLE": title, "CANARY_BODY": body},
        capture_output=True,
        timeout=60,
        check=True,
        creationflags=_NO_WINDOW,
    )


def _git(repo: Path, *args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> bytes:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        env=env,
        check=False,
        creationflags=_NO_WINDOW,
    )
    if done.returncode:
        raise ValueError(done.stderr.decode("utf-8", "replace").strip()[-300:] or f"git {args[0]} failed")
    return done.stdout


def _seconds(found: dict[str, Any]) -> str:
    seconds = found.get("seconds")
    return f"{seconds:.1f} s" if isinstance(seconds, (int, float)) else str(found.get("error") or "no answer")


class RealActions:
    """The canary's actions on this machine; every one logs and never raises."""

    def __init__(
        self,
        repo: Path,
        cage: Path | None = None,
        *,
        notify: Callable[[str, str], None] = toast,
        log_file: Path | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.cage = Path(cage) if cage is not None else cage_root()
        self._notify = notify
        self._log_file = log_file

    def tell(self, title: str, body: str) -> None:
        if self._log_file is not None:
            try:
                with Path(self._log_file).open("a", encoding="utf-8") as handle:
                    handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} told you: {title} -- {body}\n")
            except OSError:
                log.exception("the canary could not write its log")
        try:
            self._notify(title, body)
        except (OSError, subprocess.SubprocessError, ValueError):  # a failed notification never stops the canary
            log.exception("the canary could not show its notification")

    def alarm(self, alarm: dict[str, Any]) -> dict[str, Any]:
        holds = {"window": self._hold_window(), "claim": self._claim(), "revert": self._revert(alarm)}
        suspects = list(alarm.get("suspects") or [])
        why = "; ".join(alarm.get("reasons") or [])
        before = _seconds(alarm.get("good") or {})
        if holds["revert"]:
            then = f"Its revert of {suspects[0][:8]} is waiting on your card."
        else:
            then = f"Suspects: {', '.join(s[:8] for s in suspects) or 'none found'}. Nothing was reverted."
        held = "The express window is off and the check machinery is held. " if holds["window"] else ""
        self.tell(
            "Thomas canary alarm: the check before your card broke",
            f"After dev {str(alarm.get('head', ''))[:8]} landed, {why} (it took {before} before). {held}{then}",
        )
        return holds

    def clear(self, holds: dict[str, Any]) -> None:
        if holds.get("window"):
            off = self.cage / "promoter" / "window" / "off"
            try:
                if off.is_file() and off.read_text(encoding="utf-8").startswith(OFF_TEXT):
                    off.unlink()
            except OSError:
                log.exception("the canary could not lift its window hold")
        if holds.get("claim"):
            try:
                from scripts import active_folders

                active_folders._release_claim(None, AGENT)
            except (ImportError, OSError, ValueError, RuntimeError):  # the claim's lock times out as an OSError
                log.exception("the canary could not release its claim")
        again = " Open the express window again when you want it." if holds.get("window") else ""
        self.tell("Thomas canary: the check before your card is back to normal", f"Its holds are lifted.{again}")

    def _hold_window(self) -> bool:
        off = self.cage / "promoter" / "window" / "off"
        try:
            if off.exists():
                return False  # you turned it off: yours to turn on, never the canary's
            off.parent.mkdir(parents=True, exist_ok=True)
            off.write_text(f"{OFF_TEXT} ({time.strftime('%Y-%m-%d %H:%M:%S')})", encoding="utf-8")
            return True
        except OSError:
            log.exception("the canary could not turn the window off")
            return False

    def _claim(self) -> bool:
        try:
            from scripts import active_folders

            claim, _conflicts = active_folders._create_claim(
                AGENT,
                [f"{path}/" for path in WATCHED],
                CLAIM_TTL_S,
                "the pipeline canary holds the check machinery after an alarm",
                True,
                True,
            )
            return claim is not None
        except (ImportError, OSError, ValueError, RuntimeError):  # the claim's lock times out as an OSError
            log.exception("the canary could not claim the watched folders")
            return False

    def _revert(self, alarm: dict[str, Any]) -> str:
        """The revert of the one suspect, handed to the promoter; "" when there is not exactly one or it won't apply."""
        suspects = list(alarm.get("suspects") or [])
        tip = str(alarm.get("head") or "")
        if len(suspects) != 1 or not tip:
            return ""
        bad = suspects[0]
        try:
            patch = _git(
                self.repo, "diff", "--no-color", "--no-ext-diff", "--no-renames", "--full-index", bad, f"{bad}^"
            )
            files = _git(self.repo, "diff", "--name-only", "--no-renames", f"{bad}^", bad).decode().split()
            if not patch.strip() or not self._applies(tip, patch):
                return ""
            return self._hand_in(alarm, bad, tip, patch, files)
        except (OSError, ValueError):
            log.exception("the canary could not prepare the revert of %s", bad)
            return ""

    def _applies(self, tip: str, patch: bytes) -> bool:
        with tempfile.TemporaryDirectory(prefix="canary-index-") as folder:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "index")}
            try:
                _git(self.repo, "read-tree", tip, env=env)
                _git(self.repo, "apply", "--cached", "--check", "-", env=env, stdin=patch)
            except ValueError:
                return False
        return True

    def _hand_in(self, alarm: dict[str, Any], bad: str, tip: str, patch: bytes, files: list[str]) -> str:
        sid = f"self-canary-revert-{bad[:8]}-{int(time.time())}"
        inbox = self.cage / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        staging = inbox / f".tmp-{sid}-{os.getpid()}"
        staging.mkdir()
        why = "; ".join(alarm.get("reasons") or [])
        summary = (
            f"The pipeline canary measured the check before your card on dev {tip[:8]}: {why}. "
            f"On the commit before it took {_seconds(alarm.get('good') or {})}. {bad[:8]} is the one landing since "
            "then that changed the check machinery, and this reverts it."
        )
        manifest = {
            "id": sid,
            "kind": "self_change",
            "agent": AGENT,
            "base": tip,
            "message": f"Revert {bad[:8]}: the check before your card broke after it landed"[:200],
            "patch": "change.patch",
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "execution_id": "",
            "checked": "not checked: the pipeline canary's revert of a change that broke the check",
            "chat": "",
            "summary": summary,
            "files": files,
            "blue": str(self.repo),
            "submitted_at": time.time(),
        }
        try:
            (staging / "change.patch").write_bytes(patch)
            (staging / "submission.json").write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
            staging.rename(inbox / sid)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return sid


__all__ = ["AGENT", "CLAIM_TTL_S", "OFF_TEXT", "RealActions", "cage_root", "toast"]
