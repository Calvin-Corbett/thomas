# Better-Than-Codex Rubric — AI Chat Workspace (MEASURED)

**Baseline:** Codex (GPT-5.x coding-agent CLI) · **Candidate:** Thomas (dev tip, #82 `dc111657` / #83 `2712373b` / #84 `cacfb52b`) · **Date:** 2026-06-15

## Scorecard

| # | Dimension | Codex baseline | Thomas now (measured / evidence) | Winner |
|---|-----------|----------------|----------------------------------|--------|
| a | Every reply model-authored / no canned instant replies | Streams model output but interleaves canned status chrome | **0 canned acks** — `background_ack_only` short-circuit deleted; `_handle_actionable` emits only model output; forbidden phrases asserted by `test_reasoning_identity` (8/8) | **Thomas** |
| b | No regex deciding task-vs-chat | N/A (always a coding agent) | **Partial/Tie** — model decides via `send_task` in the live path, BUT legacy `should_dispatch` still in tree and **misclassifies 71.7% (86/120)** genuine tasks as casual | **Tie** |
| c | Task card names the real task | No task-card UI | **100% clean titles (120/120)**, 0 leading filler, avg 8.30 words, clean across all 6 personas | **Thomas** |
| d | Chatbot-only + repo/workspace-aware | Repo-acting agent, not a chatbot | Identity locked (`THOMAS_CHATBOT_SYSTEM_PROMPT` constant + guard test); codex provider gets `tools=None` | **Tie** (different shapes) |
| e | Honest delivery (game built isolated + one-click Play) | Builds in working repo; run manually | **Verified e2e** — built in `~/.thomas/workspaces/<id>/`, served loopback+traversal-safe at `/deliverable/{id}`, "▶ Play" button | **Thomas** |
| f | No leaked chain-of-thought | Verbose traces by design | Clean result only — `_build_result_summary` uses final line, capped 300 chars (#82) | **Thomas** |
| g | Onboarding / non-technical accessibility | CLI-first, dev-assumed | GUI chat; verified clean across grandma/kid/retiree | **Thomas** |
| h | Workspace isolation / blast radius | Acts on user's checkout | Sandboxed per-task workspace, loopback-only | **Thomas** |
| i | Raw coding-agent depth | Purpose-built, mature | Chatbot deliberately incapable; delegates to worker | **Codex** |
| j | Guarding-test coverage of the UX contract | Implicit | 4 dims = code + guard test; **45/45** across 5 test files | **Thomas** |

## Verdict
- **Thomas beats Codex on 6/10** (a, c, e, f, g, h) — the dimensions the product is defined around, all numbers- or test-backed.
- **Tie on 2** (b no-regex-routing, d chatbot-only) — met in the live code path, but different shapes + the regex gap.
- **Codex wins 1** (i raw coding depth) — Thomas's chatbot is *deliberately* incapable; capability lives in the worker.

## Remaining gaps (specific, honest)
1. **The regex classifier still exists.** It no longer fakes replies, but `should_dispatch` drops **71.7% of real tasks** to chat when exercised in `mode='auto'`. Retiring it is the single highest-value cleanup (turns dimension b from tie → win).
2. **No live persona testing at scale.** Guarantees are source + unit-test verified, NOT observed under a live 10k-message GPT-5.5 run. Win column = *contract-verified*, not *load-proven*.
3. **Titler model path unexercised.** 100%-clean is the deterministic fallback (`derive_task_title`); `generate_task_title` (model-backed) was not measured.
4. **Two cosmetic titler nits** (still counted clean): 6/120 keep a trailing "?"; 2/120 context-first prompts under-specify.

## What "measured" means
Unit-level matrix (120 prompts = 6 personas × 20 realistic in-voice tasks) through the real `derive_task_title` and `should_dispatch` via the repo venv, + source spot-checks + the 45/45 guard-test suite. NOT a 10k live GPT-5.5 benchmark, NOT organic in-browser persona sessions, NOT the model-backed titler. Treat wins as contract-verified, not load-proven.
