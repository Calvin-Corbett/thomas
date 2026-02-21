# Natural Behavior Eval Protocol (Web UI)

Date: 2026-02-21

## Goal

Measure whether Thomas behaves like a normal assistant in realistic conversation, without prompt-leading it to "act human."

## Non-Negotiable Rules

1. Run in Web UI only (`http://127.0.0.1:8899`) using real chat flow.
2. Use blind, natural prompts. Do not include style instructions like "be human" or "think out loud."
3. Use multi-turn tests (follow-up, correction, memory checks), not one-shot only.
4. Score behavior with a fixed rubric and fail thresholds.

## Prompt Set (Baseline)

Run each in a fresh chat unless marked follow-up:

1. `hey, what's up?`
2. `i'm overwhelmed with work and keep procrastinating. give me one thing i can do in the next 10 minutes.`
3. Follow-up in same chat: `make it easier.`
4. Follow-up in same chat: `that's not what i asked. try again in one sentence.`
5. Follow-up in same chat: `what did i ask you first in this chat?`
6. `my settings keep resetting every restart. where should i look first?`
7. `are you only for coding or can you help with normal life stuff too?`

## Scoring Rubric (1-5 each)

1. Naturalness: sounds conversational, not robotic/template-heavy.
2. Directness: answers request directly without dumping process boilerplate.
3. Context handling: follows follow-ups/corrections and remembers prior turns.
4. Action quality: gives useful next steps proportional to user request.
5. Tone calibration: matches user state (stress/frustration) without sounding canned.
6. Leakage control: no internal monologue, chain-of-thought, or fake tool JSON blocks.

## Pass/Fail Gate

- Hard fail if any response includes:
  - chain-of-thought narration (`let me think`, `here is my thought process`, step-by-step reasoning dump for simple asks)
  - raw tool-call artifacts (`json/copy/{\"name\": ..., \"arguments\": ...}`)
- Hard fail if correction turns are ignored.
- Average rubric score must be `>= 4.0` and no single category below `3`.

## Evidence Capture

Store for each run:

1. Prompt text
2. Full assistant response (verbatim)
3. Rubric scores + short rationale
4. Final pass/fail decision

Use Playwright snapshots/eval output as primary artifacts.

## Sources

- OpenAI eval design and graders:
  - https://platform.openai.com/docs/guides/evals
  - https://platform.openai.com/docs/guides/graders
- OpenAI Model Spec (conversation behavior principles):
  - https://model-spec.openai.com/
- Anthropic eval guidance:
  - https://docs.anthropic.com/en/docs/test-and-evaluate/eval-tool
- MT-Bench / Chatbot Arena (multi-turn + human preference methodology):
  - https://arxiv.org/abs/2306.05685
- SWE-bench Mutation (use realistic prompts, avoid benchmark overfitting artifacts):
  - https://arxiv.org/abs/2410.10762
