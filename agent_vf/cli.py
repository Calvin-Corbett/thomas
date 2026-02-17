from __future__ import annotations
import argparse

from agent_vf.cli_runtime import build_agent
from agent_vf.server import serve
from agent_vf.llm_client import LLMError

def cmd_chat(args):
    agent = build_agent(root=args.root)
    try:
        print(agent.chat(args.text))
    except LLMError as e:
        print('LLM_ERROR: Unable to reach your configured LLM endpoint.')
        print('Set AGENT_LLM_BASE_URL, AGENT_LLM_MODEL, and (if needed) AGENT_LLM_API_KEY.')
        print(f'Details: {e}')
        raise SystemExit(2)
    finally:
        agent.close()
def cmd_serve(args):
    serve(host=args.host, port=args.port, root=args.root)

def cmd_memory_nightly(args):
    agent = build_agent(root=args.root)
    try:
        print(agent.memory.nightly())
    finally:
        agent.close()

def cmd_memory_eval(args):
    from agent_memory.eval.suite import run_all
    agent = build_agent(root=args.root)
    try:
        results = run_all(agent.memory)
        ok = True
        for r in results:
            print(f"{r.name}: {'PASS' if r.passed else 'FAIL'} - {r.details}")
            ok = ok and r.passed
        print("ALL_PASS" if ok else "SOME_FAIL")
    finally:
        agent.close()

def build_parser():
    p = argparse.ArgumentParser(prog="agent_vf")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("chat")
    s.add_argument("--root", default="./runtime")
    s.add_argument("--text", required=True)
    s.set_defaults(func=cmd_chat)

    s = sub.add_parser("serve")
    s.add_argument("--root", default="./runtime")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8899)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("memory-nightly")
    s.add_argument("--root", default="./runtime")
    s.set_defaults(func=cmd_memory_nightly)

    s = sub.add_parser("memory-eval")
    s.add_argument("--root", default="./runtime")
    s.set_defaults(func=cmd_memory_eval)

    return p

def main():
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
