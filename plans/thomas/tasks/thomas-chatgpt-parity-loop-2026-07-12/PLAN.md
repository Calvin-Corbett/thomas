# PLAN for thomas-chatgpt-parity-loop-2026-07-12

- Owner: codex-thomas-chatgpt-parity
- Status: in_progress
- Updated At: 2026-07-13T02:50:00+00:00
- Scope: plans/thomas/chatgpt_parity/CAPABILITY_RUBRIC.json,plans/thomas/chatgpt_parity/RUBRIC.md,plans/thomas/chatgpt_parity/latest_evidence.jsonl,plans/thomas/chatgpt_parity/latest_scorecard.json,plans/thomas/chatgpt_parity/GAP_LEDGER.md,tests/stress/chatgpt_parity_harness.py,tests/stress/chatgpt_parity_probes.py,tests/stress/chatgpt_parity_loop.py,tests/test_chatgpt_parity_loop.py,plans/thomas/tasks/thomas-chatgpt-parity-loop-2026-07-12/PLAN.md

## Summary

Build and repeatedly run a fail-closed, evidence-backed comparison between Thomas and the current user-facing ChatGPT capability set. Full completion requires every capability family to reach adversarial tier 4; the current local checkpoint is 51.75/100 with 0/14 families at tier 4 and 16 critical failures.

## Approach

- Keep the target dated and sourced from official OpenAI capability and release documentation.
- Score 14 capability families sequentially from static presence through adversarial live proof; missing evidence fails closed.
- Run the real local Thomas server with auto-push disabled and persist JSONL evidence, a scorecard, and a ranked gap ledger.
- Fix the highest-ranked first failed tier, add deterministic and live regression coverage, then rerun only the affected family before periodic full baselines.
- First repaired slice: register resilient web tools, execute explicit read-only search inline, suppress provider-style text tool calls, fetch source evidence, and prove a dated cited answer without delegation.
- Continue with adversarial citation integrity for web research, then the next ranked family; do not claim parity until all 14 families reach tier 4.
