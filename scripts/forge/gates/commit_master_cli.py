"""Protected command-line adapter for :mod:`scripts.forge.commit_master`."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import time
from pathlib import Path
from types import ModuleType


def _core_module(core: ModuleType | None) -> ModuleType:
    return core or importlib.import_module("scripts.forge.commit_master")


def resolve_layout(args: argparse.Namespace, repo: Path, *, core: ModuleType | None = None):
    owner = _core_module(core)
    root = args.cage_root or os.environ.get("THOMAS_CAGE_ROOT") or str(repo / "runtime" / "cage")
    return owner.CageLayout(root=Path(root).expanduser())


def cmd_submit(args: argparse.Namespace, *, core: ModuleType | None = None) -> int:
    owner = _core_module(core)
    repo = Path(args.repo).resolve()
    layout = owner._resolve_layout(args, repo)
    workboard = Path(args.workboard).resolve() if getattr(args, "workboard", "") else None
    try:
        sub_dir = owner.create_submission(
            layout=layout,
            repo=repo,
            agent=args.agent,
            message=args.message,
            base=args.base,
            patch_file=args.patch_file,
            remote=args.remote,
            branch=args.branch,
            workboard=workboard,
        )
    except owner.InboxBlockedError as exc:
        ack = [
            f"python scripts/crew/workboard/message.py --ack --msg-id {msg.get('msg_id')} --by {exc.agent}"
            for msg in exc.blocking
        ]
        payload = {
            "ok": False,
            "status": "blocked_unread_messages",
            "agent": exc.agent,
            "blocking": [
                {
                    "msg_id": msg.get("msg_id"),
                    "from": msg.get("from"),
                    "kind": msg.get("kind"),
                    "summary": msg.get("summary"),
                    "reasons": msg.get("_reasons"),
                }
                for msg in exc.blocking
            ],
            "ack": ack,
            "detail": "Read and ACK these coordination messages, then resubmit.",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "submission": str(sub_dir), "id": sub_dir.name}))
    return 0


def cmd_run_once(args: argparse.Namespace, *, core: ModuleType | None = None) -> int:
    owner = _core_module(core)
    repo = Path(args.repo).resolve()
    layout = owner._resolve_layout(args, repo)
    layout.ensure()
    master = owner.CommitMaster(
        repo=repo,
        layout=layout,
        gates_root=Path(args.gates_root).resolve() if args.gates_root else None,
        sign=not args.no_sign,
        push=not args.no_push,
    )
    verdict = master.run_once()
    if verdict is None:
        print(json.dumps({"ok": True, "status": "idle", "detail": "no pending submissions"}))
        return 0
    print(json.dumps({"ok": verdict.status == "committed", **verdict.to_dict()}))
    return 0 if verdict.status == "committed" else 1


def cmd_watch(args: argparse.Namespace, *, core: ModuleType | None = None) -> int:
    owner = _core_module(core)
    repo = Path(args.repo).resolve()
    layout = owner._resolve_layout(args, repo)
    layout.ensure()
    master = owner.CommitMaster(
        repo=repo,
        layout=layout,
        gates_root=Path(args.gates_root).resolve() if args.gates_root else None,
        sign=not args.no_sign,
        push=not args.no_push,
    )
    print(f"commit-master watching {layout.inbox} (interval={args.interval}s)")
    while True:
        verdict = master.run_once()
        if verdict is not None:
            print(json.dumps(verdict.to_dict()))
        else:
            time.sleep(max(1.0, float(args.interval)))


def cmd_status(args: argparse.Namespace, *, core: ModuleType | None = None) -> int:
    owner = _core_module(core)
    repo = Path(args.repo).resolve()
    layout = owner._resolve_layout(args, repo)
    pending = [path.name for path in (layout.inbox.iterdir() if layout.inbox.exists() else []) if path.is_dir()]
    verdicts = [path.name for path in (layout.outbox.iterdir() if layout.outbox.exists() else [])]
    print(
        json.dumps({"cage_root": str(layout.root), "pending": sorted(pending), "verdicts": sorted(verdicts)}, indent=2)
    )
    return 0


def build_parser(*, core: ModuleType | None = None) -> argparse.ArgumentParser:
    owner = _core_module(core)
    parser = argparse.ArgumentParser(description="Commit-master: gated proposer/committer split for the Praxis cage.")
    parser.add_argument("--repo", default=str(owner._REPO_ROOT), help="repository root (default: this repo)")
    parser.add_argument(
        "--cage-root", default="", help="cage channel root (default: $THOMAS_CAGE_ROOT or <repo>/runtime/cage)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="[worker] drop a submission into the inbox")
    submit.add_argument("--agent", required=True)
    submit.add_argument("--message", required=True)
    submit.add_argument("--base", default="HEAD")
    submit.add_argument("--patch-file", default="")
    submit.add_argument("--remote", default="")
    submit.add_argument("--branch", default="")
    submit.add_argument(
        "--workboard", default="", help="WORKBOARD.md for inbox enforcement (default: <repo>/plans/thomas/WORKBOARD.md)"
    )
    submit.set_defaults(func=owner._cmd_submit)

    run_once = sub.add_parser("run-once", help="[master] process the oldest pending submission")
    run_once.add_argument("--gates-root", default="")
    run_once.add_argument("--no-sign", action="store_true")
    run_once.add_argument("--no-push", action="store_true")
    run_once.set_defaults(func=owner._cmd_run_once)

    watch = sub.add_parser("watch", help="[master] poll the inbox forever")
    watch.add_argument("--gates-root", default="")
    watch.add_argument("--interval", default="5")
    watch.add_argument("--no-sign", action="store_true")
    watch.add_argument("--no-push", action="store_true")
    watch.set_defaults(func=owner._cmd_watch)

    status = sub.add_parser("status", help="show pending submissions and verdicts")
    status.set_defaults(func=owner._cmd_status)
    return parser


def main(argv: list[str] | None = None, *, core: ModuleType | None = None) -> int:
    owner = _core_module(core)
    args = owner.build_parser().parse_args(argv)
    if getattr(args, "patch_file", None) == "":
        args.patch_file = None
    return int(args.func(args))
