# Web UI Natural Behavior Eval

Date: 2026-02-21  
Method: `docs/NATURAL_BEHAVIOR_EVAL_PROTOCOL.md`  
Environment: local Web UI (`127.0.0.1:8899`) via Playwright headed Chrome

## Prompt/Response Samples

1. Prompt: `hey, what's up?`  
Response: `Hello! Not much, just here to help you out. How can I assist you today?`

2. Prompt: `i'm overwhelmed with work and keep procrastinating. give me one thing i can do in the next 10 minutes.`  
Response: `To help you get started, how about taking a quick break? ... What do you think?`

3. Follow-up: `make it easier.`  
Response: multi-step plan with multiple bullets + closing question.

4. Follow-up: `that's not what i asked. try again in one sentence.`  
Response: `Close your eyes for 5 minutes and take deep breaths. ... What do you think?`

5. Follow-up: `what did i ask you first in this chat?`  
Response: correctly recalled first prompt.

6. Prompt: `my settings keep resetting every restart. where should i look first?`  
Response: checklist answer (config/env/logs/session checks), no leaked tool-call JSON blocks after sanitizer patch.

7. Prompt: `are you only for coding or can you help with normal life stuff too?`  
Response: `I can help with both coding and normal life stuff! How can I assist you today?`

## Rubric Scores (1-5)

- Naturalness: `3`
- Directness: `3`
- Context handling: `4`
- Action quality: `3`
- Tone calibration: `3`
- Leakage control: `4`

Average: `3.3`

## Verdict

`FAIL` (target is >= 4.0 with no category < 3)

## Critical Findings

1. Still too template-like in casual/meta replies (`How can I assist you today?` appears often).
2. Correction handling is weak: when asked for one sentence, response still appends extra framing.
3. Over-assistance in simple support turns: expands into multi-step structure instead of minimal next action.
4. Positive: chain-of-thought leakage and raw tool-call JSON leakage improved versus prior baseline.

## Post-Patch Spot Check (Same Day)

After applying response sanitization updates:

1. Correction prompt (`try again in one sentence`) now yields a single sentence in live Web UI.
2. Raw tool-call JSON artifacts (`{"name": "...", "arguments": ...}`) no longer appear in user-facing replies.
3. Pseudo command blocks (`json/sh + Copy + tool call`) are reduced versus baseline, though general checklist verbosity remains above target on some technical asks.
