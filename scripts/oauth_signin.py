#!/usr/bin/env python3
"""One-time ChatGPT (OAuth) sign-in for the `openai_codex` provider.

Run this once to authenticate Thomas's default model (openai_codex) with your
ChatGPT subscription — no API key, no metered billing. This is the engine that
lets the model actually use Thomas's tools/skills (function-calling), which the
old Codex-CLI bridge could not do.

Usage:
    python scripts/oauth_signin.py

It prints a URL — open it, sign in (your Google-linked ChatGPT account works),
and when the browser lands on a localhost page (or shows a code), paste the FULL
redirected URL (or the code) back here. The token is stored encrypted; refresh
is automatic afterward.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thomas.server.openai_codex_oauth import (  # noqa: E402
    _default_secret_store,
    exchange_code_for_tokens,
    public_token_status,
    read_openai_codex_token,
    write_openai_codex_token,
)
from thomas.server.openai_codex_oauth_flow import (  # noqa: E402
    normalize_openai_codex_profile,
    parse_oauth_callback,
    start_oauth_flow,
)


def main() -> int:
    profile = normalize_openai_codex_profile(None)
    start = start_oauth_flow(profile=profile)

    print("\n=== Thomas — sign in to ChatGPT (openai_codex) ===\n")
    print("1) Open this URL in your browser and sign in:\n")
    print("   " + start.auth_url + "\n")
    print("2) After approving, your browser will redirect to a localhost URL")
    print("   (it may show 'can't reach the page' — that's fine).")
    print("   Copy the FULL address bar URL (it contains ?code=...&state=...)")
    print("   and paste it below, then press Enter.\n")

    pasted = input("Paste redirect URL (or just the code): ").strip()
    code, state = parse_oauth_callback(pasted)
    if not code:
        # User may have pasted only the bare code.
        code = pasted
    if not code:
        print("\n[error] No authorization code found. Aborting.")
        return 1
    if state and start.state and state != start.state:
        print("\n[error] State mismatch — possible CSRF / stale flow. Re-run and try again.")
        return 1

    try:
        raw = asyncio.run(
            exchange_code_for_tokens(
                code=code,
                code_verifier=start.code_verifier,
                redirect_uri=start.redirect_uri,
            )
        )
    # exchange_code_for_tokens funnels every transport/HTTP/JSON fault into
    # OpenAICodexOAuthError (a RuntimeError subclass); asyncio.run contributes
    # RuntimeError, and a mangled paste can surface OSError/ValueError. Surface
    # the auth error plainly instead of a traceback -- a human is at this prompt.
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"\n[error] Token exchange failed: {exc}")
        return 1

    store = _default_secret_store()
    write_openai_codex_token(store, profile, raw)

    status = public_token_status(read_openai_codex_token(store, profile))
    print("\n[ok] Signed in. Token stored (encrypted). Status:", status)
    print("\nNow restart Thomas and try a tool-using prompt, e.g.:")
    print('   "read README.md and give me a 3-line summary"')
    print("If the task card shows a tool running, the model is using Thomas's tools. 🎉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
