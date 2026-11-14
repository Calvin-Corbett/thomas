"""Your control for the window (spec 2026-10-12, section 8.4): ask for one, close it, switch windows off, undo a change.

Runs as you, from your own checkout. It writes a request into C:\\ProgramData\\ThomasCage\\promoter\\window\\
requests, which only your account and SYSTEM can reach, and the promoter's window loop acts on it within seconds.
Nothing here opens a window: only your Windows sign-in on the pinned open_window card does, with you at this PC.

    python scripts/cage/window_control.py open [--minutes 120 | --until-off] [--max-landings 25 | --no-landing-cap] [--away]
    python scripts/cage/window_control.py close
    python scripts/cage/window_control.py off        no window opens, and an open one ends, until "on"
    python scripts/cage/window_control.py on
    python scripts/cage/window_control.py undo --sid self-thomas-0123456789ab
    python scripts/cage/window_control.py status

A window lasts the minutes you choose, or with --until-off until you close it or switch windows off (a year at most;
your decision, 2026-10-27), and lands at most the number you choose (25 unless you
choose another), or as many as come with --no-landing-cap. Locking your PC pauses it, and 15 minutes locked or idle
ends it -- unless you open it with --away, which keeps it landing while your PC is locked or you are away. --away works
only on a PC whose elevated setup turned it on (window.away in C:\\ProgramData\\ThomasPins), and its card says so before
you sign. The hard off switch is window.off in C:\\ProgramData\\ThomasPins, which only an elevated step can place or
remove.

Standard library only, and nothing from Thomas: this file is run as you, so it is kept small, and it is on the
never-in-a-window list with everything it imports.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

# As thomas/tools/cage_shell.cage_root() reads it, without importing Thomas.
CAGE_ROOT = Path(os.environ.get("THOMAS_CAGE_ROOT") or r"C:\ProgramData\ThomasCage")
# The longest window, which --until-off asks for: the card catalogue's WINDOW_CEILING_MINUTES. This file imports nothing
# from Thomas, so it repeats the number; the window's loop refuses anything past the pinned ceiling either way.
UNTIL_OFF_MINUTES = 525600


def home(cage_root: Path = CAGE_ROOT) -> Path:
    return Path(cage_root) / "promoter" / "window"


def request(folder: Path, kind: str, **fields: object) -> Path:
    """Write one request for the window's loop, whole (a temporary name, then a rename)."""
    requests = Path(folder) / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}-{kind}.json"
    tmp = requests / f".{name}.tmp"
    tmp.write_text(json.dumps({"kind": kind, "at": time.time(), **fields}), encoding="utf-8")
    os.replace(tmp, requests / name)
    return requests / name


def status_text(folder: Path) -> str:
    try:
        status = json.loads((Path(folder) / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "The window's loop has written no status: is the promoter running?"
    window = status.get("window") or {}
    cap = window.get("max_landings")
    lines = [
        f"Window open until {window.get('ends_at')} (pairing code {window.get('pairing_code')}), "
        + (
            f"{window.get('landings')} of {cap} landed."
            if cap is not None
            else f"{window.get('landings')} landed (no limit)."
        )
        + (" It KEEPS LANDING while your PC is locked or you are away." if window.get("away") else "")
        if window.get("open")
        else "No window is open.",
        f"Checker: {status.get('checker')}.",
    ]
    if status.get("after_check"):
        lines.append(f"The check after {status['after_check'].get('sid')} landed is running.")
    for row in status.get("waiting") or []:
        lines.append(f"  {row.get('sid')}: {row.get('wait') or 'being prepared'}")
    if status.get("undo"):
        lines.append(f"Undo: {status['undo']}")
    lines.extend(f"  {note}" for note in status.get("notes") or [])
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, folder: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Your control for Thomas's landing window.")
    sub = parser.add_subparsers(dest="command", required=True)
    opening = sub.add_parser("open")
    length = opening.add_mutually_exclusive_group()
    length.add_argument("--minutes", type=int, default=120, help=f"1 to {UNTIL_OFF_MINUTES}; 120 when not given")
    length.add_argument(
        "--until-off",
        action="store_true",
        help="keep it open until you close it or switch windows off (a year at most)",
    )
    cap = opening.add_mutually_exclusive_group()
    cap.add_argument(
        "--max-landings", type=int, default=None, help="land at most this many changes (25 when not given)"
    )
    cap.add_argument("--no-landing-cap", action="store_true", help="no limit on how many changes it lands")
    opening.add_argument("--away", action="store_true", help="keep landing while your PC is locked or you are away")
    sub.add_parser("close")
    sub.add_parser("off")
    sub.add_parser("on")
    undo = sub.add_parser("undo")
    undo.add_argument("--sid", required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    folder = folder or home()
    if args.command == "open":
        if args.max_landings is not None and args.max_landings < 1:
            parser.error("--max-landings takes a number of 1 or more (or use --no-landing-cap)")
        minutes = UNTIL_OFF_MINUTES if args.until_off else args.minutes
        if not 1 <= minutes <= UNTIL_OFF_MINUTES:
            parser.error(f"--minutes takes a number from 1 to {UNTIL_OFF_MINUTES} (or use --until-off)")
        chosen: dict[str, object] = {"minutes": minutes, "away": args.away}
        if args.no_landing_cap:
            chosen["max_landings"] = None
        elif args.max_landings is not None:
            chosen["max_landings"] = args.max_landings
        request(folder, "open", **chosen)
        print("Asked. The Windows sign-in for the window appears on your screen within a few seconds.")
    elif args.command == "close":
        request(folder, "close")
        print("Asked. The window closes within a few seconds.")
    elif args.command == "off":
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "off").write_text("off", encoding="utf-8")
        print("Windows are off: none opens, and an open one ends, until you run this with on.")
    elif args.command == "on":
        (folder / "off").unlink(missing_ok=True)
        print("Windows are on again. Opening one still takes your Windows sign-in.")
    elif args.command == "undo":
        request(folder, "undo", sid=args.sid)
        print("Asked. The undo is checked first; then its card appears at your Windows sign-in.")
    else:
        print(status_text(folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
