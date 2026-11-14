#!/usr/bin/env python3
"""Hand an outside agent's multi-commit change from a scratch clone into Thomas's own pipeline.

    python scripts/crew/hand_in_outside.py --clone <clone> --base <sha> --tip <sha> [--title "..."] [--drop]

Without ``--drop`` it only prints what it would hand in. With ``--drop`` it writes one ``self-outside-...`` folder into
the promoter's inbox, which the promoter checks, shows you as a card, and lands only when you sign. The default inbox is
the real one (``$THOMAS_CAGE_ROOT``, else ``C:\\ProgramData\\ThomasCage``); a test always passes ``--inbox``.
See docs/superpowers/plans/2026-11-03-handing-an-outside-agents-work-to-thomas.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew import hand_in_outside_build as build  # noqa: E402
from scripts.crew import hand_in_outside_checks as checks  # noqa: E402
from scripts.pipeline_canary.act import cage_root  # noqa: E402

POLL_S = 5.0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clone", required=True, help="the scratch clone the work was made in")
    ap.add_argument("--base", required=True, help="the commit your work starts from")
    ap.add_argument("--tip", required=True, help="the last commit of your work")
    ap.add_argument("--title", help="one line for the card (default: the first commit's subject)")
    ap.add_argument("--agent", default="outside-agent", help="who is handing it in, e.g. claude-code or codex")
    ap.add_argument("--checkout", default=str(ROOT), help="the checkout whose dev branch the change must apply to")
    ap.add_argument("--branch", default="dev", help="the branch the promoter lands on (default: dev)")
    ap.add_argument("--inbox", help="the inbox folder (default: the real promoter inbox)")
    ap.add_argument("--allow-protected", action="store_true", help="hand it in although it touches a guarded file")
    ap.add_argument("--allow-findings", action="store_true", help="hand it in although ruff or the growth rule object")
    ap.add_argument(
        "--accept-card-wording", action="store_true",
        help="allow --drop although the promoter ("
        + build.PROMOTER_FILE
        + ") will write "
        + " and ".join(build.FALSE_WORDING)
        + " into the commit, which is not true of an outside agent's change",
    )  # fmt: skip
    ap.add_argument("--drop", action="store_true", help="write the hand-in (default: print what would be handed in)")
    ap.add_argument("--watch", action="store_true", help="after --drop, wait for the verdict and print it")
    ap.add_argument("--give-up-after", type=float, help="seconds to watch before giving up (default: never)")
    ap.add_argument("--poll", type=float, default=POLL_S, help=f"seconds between looks at the outbox ({POLL_S:g})")
    return ap


def _plan(
    args: argparse.Namespace, lint: Callable[[build.Change], tuple[bool, str, list[str]]]
) -> tuple[Path, str, dict, bytes]:
    """Everything a hand-in needs, or a Refusal. Returns (inbox, sid, manifest, patch) and prints the report."""
    clone, checkout = Path(args.clone), Path(args.checkout)
    base, tip = build.resolve(clone, args.base, "--base"), build.resolve(clone, args.tip, "--tip")
    change = build.read_change(clone, base, tip)
    dev = checks.dev_tip(checkout, args.branch)
    if not dev:
        raise build.Refusal(f"The checkout {checkout} has no {args.branch} branch or HEAD to hand the change to.")
    unsafe, unsafe_note = checks.promoter_refusal(change.patch, checkout)
    if unsafe:
        raise build.Refusal(f"The promoter would refuse this change before any card: {unsafe}.")
    stops = checks.applies_to(checkout, dev, change.patch)
    if stops:
        raise build.Refusal(
            f"The change does not apply to {args.branch} ({dev[:8]}) in {checkout}: {stops}\n"
            f"Rebase your work on {args.branch} in your clone and hand it in again."
        )
    guarded = checks.protected_paths(checkout, dev, change.files)
    lines = [
        f"{len(change.commits)} commit(s), {len(change.files)} file(s), {len(change.patch)} byte patch, applies to {dev[:8]}"
    ]
    if guarded:
        lines.append("A card will be needed for: " + ", ".join(guarded))
        if not args.allow_protected:
            raise build.Refusal(
                "This change touches a file Thomas guards: " + ", ".join(guarded) + ".\n"
                "A hand-in with a guarded file needs its own card for you to approve or leave out. "
                "Run again with --allow-protected to hand it in knowing that."
            )
    growth, growth_note = checks.growth_findings(change)
    ran, why, ruff = lint(change)
    findings = [*growth, *ruff]
    notes = [n for n in (unsafe_note, growth_note, "" if ran else f"ruff was not run: {why}") if n]
    if findings and not args.allow_findings:
        raise build.Refusal(
            "Before your card, these would have sent a Thomas change back:\n- "
            + "\n- ".join(findings)
            + "\nFix them, or run again with --allow-findings."
        )
    checked = "not checked by Thomas's check before your card: handed in by an outside agent. " + (
        "ruff and the growth rule found nothing."
        if ran and not findings
        else ("Findings handed in anyway: " + "; ".join(findings) if findings else "; ".join(notes))
    )
    title = (args.title or change.commits[0][1])[:200]
    now = time.time()
    sid = build.submission_id(tip, now)
    manifest = build.manifest_for(
        change, sid=sid, dev_tip=dev, checkout=checkout, title=title, agent=args.agent, checked=checked, now=now
    )
    print(f"Title: {title}\nId: {sid}\n" + "\n".join(lines))
    for short, subject in change.commits:
        print(f"  {short} {subject}")
    for note in notes:
        print("Note: " + note)
    print("Checked: " + checked)
    approved, window = build.card_text(manifest)
    print("The commit message the promoter will write once you approve the card:\n" + approved)
    if window:
        print("If a window you opened lands it instead:\n" + window)
    inbox = Path(args.inbox) if args.inbox else cage_root() / "inbox"
    return inbox, sid, manifest, change.patch


def _watch(outbox: Path, sid: str, give_up_after: float | None, poll: float, sleep: Callable[[float], None]) -> int:
    started, told = time.monotonic(), False
    while True:
        verdict = outbox / f"{sid}.verdict.json"
        if verdict.is_file():
            try:
                record = json.loads(verdict.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = None  # being replaced: look again
            if isinstance(record, dict):
                print(json.dumps(record, indent=2))
                return 0 if record.get("status") == "landed" else 1
        if not told and (outbox / f"{sid}.pending.json").is_file():
            print("A card is waiting for you.")
            told = True
        if give_up_after is not None and time.monotonic() - started >= give_up_after:
            print(f"No verdict after {give_up_after:g} seconds. Still watch: {verdict}")
            return 3
        sleep(max(1.0, poll))


def main(
    argv: list[str] | None = None, *, lint=checks.ruff_findings, sleep: Callable[[float], None] = time.sleep
) -> int:
    args = _parser().parse_args(argv)
    if args.watch and not args.drop:
        print("--watch follows a hand-in that --drop just wrote; add --drop.")
        return 2
    try:
        inbox, sid, manifest, patch = _plan(args, lint)
        if not args.drop:
            print(f"Dry run: nothing was written. Add --drop to hand it in to {inbox}.")
            return 0
        if not args.accept_card_wording:
            raise build.Refusal(
                f"The promoter ({build.PROMOTER_FILE}) writes {build.FALSE_WORDING[0]} and, for a window you opened, "
                f"{build.FALSE_WORDING[1]} into the commit of every change it lands. Neither is true of an outside "
                "agent's change: it was not made in green and Thomas's checker did not look at it. The message above "
                "is exactly what would be written. Run again with --accept-card-wording to hand it in knowing that."
            )
        if os.environ.get("PYTEST_CURRENT_TEST") and not args.inbox:
            raise build.Refusal("A test must pass --inbox: it may not write the real one.")
        folder = build.drop(inbox, manifest, patch)
    except (build.Refusal, ValueError, OSError) as exc:
        print(f"Not handed in. {exc}")
        return 2
    outbox = inbox.parent / "outbox"
    print(
        f"Handed in: {folder}\nWatch, in this order:\n  {outbox / (sid + '.pending.json')}\n  {outbox / (sid + '.verdict.json')}"
    )
    return _watch(outbox, sid, args.give_up_after, args.poll, sleep) if args.watch else 0


if __name__ == "__main__":
    raise SystemExit(main())
