from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_memory.app import AgentMemoryApp
from agent_memory.eval.suite import run_all
from agent_memory.rerank.tier2 import Tier2Config, Tier2Reranker
from agent_memory.runtime import init_runtime


def _require_non_empty(value, flag_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required argument: {flag_name}")
    return text


def cmd_init(args):
    _ = init_runtime(Path(args.root))
    print("ok")


def cmd_log(args):
    app = AgentMemoryApp(Path(args.root))
    try:
        eid = app.log_event(thread=args.thread, etype=args.etype, text=args.text)
        print(eid)
    finally:
        app.close()


def cmd_query(args):
    app = AgentMemoryApp(Path(args.root))
    try:
        out = app.query(thread=args.thread, mode=args.mode, text=args.text)
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(out["packed"])
    finally:
        app.close()


def cmd_pin(args):
    if args.action == "add":
        _require_non_empty(args.key, "--key")
        _require_non_empty(args.text, "--text")
    elif args.action == "rm":
        _require_non_empty(args.key, "--key")

    app = AgentMemoryApp(Path(args.root))
    try:
        if args.action == "add":
            app.rt.meta.pin_set(args.key, args.text)
        elif args.action == "rm":
            app.rt.meta.pin_rm(args.key)
        else:
            rows = app.rt.meta.pin_list()
            for k, t, ts in rows:
                print(f"{k}\t{ts}\t{t}")
    finally:
        app.close()


def cmd_lex(args):
    if args.action == "add":
        _require_non_empty(args.phrase, "--phrase")
        _require_non_empty(args.meaning, "--meaning")

    app = AgentMemoryApp(Path(args.root))
    try:
        if args.action == "add":
            app.rt.meta.lex_add(args.phrase, args.meaning)
        else:
            rows = app.rt.meta.lex_list()
            for p, m, ts in rows:
                print(f"{p}\t{ts}\t{m}")
    finally:
        app.close()


def cmd_nightly(args):
    app = AgentMemoryApp(Path(args.root))
    try:
        build = app.nightly()
        print(build)
    finally:
        app.close()


def cmd_compact(args):
    app = AgentMemoryApp(Path(args.root))
    try:
        app.compact()
        print("ok")
    finally:
        app.close()


def cmd_train(args):
    try:
        from agent_memory.rerank.train import TrainConfig, train_linear_from_traces
    except Exception as exc:  # pragma: no cover - exercised by CLI error paths
        raise RuntimeError("Training requires optional dependencies. Install with: pip install .[train]") from exc

    app = AgentMemoryApp(Path(args.root))
    try:
        t2 = Tier2Reranker(Tier2Config(enabled=True), root_dir=app.rt.paths.root)
        w = train_linear_from_traces(app.rt.meta, t2, TrainConfig(max_traces=args.max_traces))
        print(json.dumps({"trained": bool(w), "weights": w}, indent=2))
    finally:
        app.close()


def cmd_eval(args):
    app = AgentMemoryApp(Path(args.root))
    try:
        results = run_all(app)
        passed = True
        for r in results:
            print(f"{r.name}: {'PASS' if r.passed else 'FAIL'} - {r.details}")
            passed = passed and r.passed
        print("ALL_PASS" if passed else "SOME_FAIL")
    finally:
        app.close()


def build_parser():
    p = argparse.ArgumentParser(prog="agent_memory")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("log")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.add_argument("--thread", required=True)
    s.add_argument("--etype", required=True)
    s.add_argument("--text", required=True)
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("query")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.add_argument("--thread", required=True)
    s.add_argument("--mode", default="fast", choices=["fast", "deep", "learning", "auto", "no_memory"])
    s.add_argument("--text", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("pin")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.add_argument("action", choices=["add", "rm", "ls"])
    s.add_argument("--key")
    s.add_argument("--text")
    s.set_defaults(func=cmd_pin)

    s = sub.add_parser("lex")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.add_argument("action", choices=["add", "ls"])
    s.add_argument("--phrase")
    s.add_argument("--meaning")
    s.set_defaults(func=cmd_lex)

    s = sub.add_parser("nightly")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.set_defaults(func=cmd_nightly)

    s = sub.add_parser("compact")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.set_defaults(func=cmd_compact)

    s = sub.add_parser("train")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.add_argument("--max-traces", type=int, default=4000)
    s.set_defaults(func=cmd_train)

    s = sub.add_parser("eval")
    s.add_argument("--root", default="./runtime", help="runtime folder")
    s.set_defaults(func=cmd_eval)

    return p


def main():
    p = build_parser()
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
