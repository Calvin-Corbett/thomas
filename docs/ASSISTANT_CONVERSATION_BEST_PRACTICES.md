# Assistant Conversation Best Practices (2026-02-21)

This note captures the behavior standard used for Thomas conversation quality.

## Research Inputs

- OpenAI Prompt Engineering guide: <https://platform.openai.com/docs/guides/prompt-engineering>
- OpenAI Model Spec: <https://model-spec.openai.com/>
- Anthropic prompt-engineering guidance: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview>

## Core Principles

1. Keep responses direct and action-first.
2. Avoid verbose preambles and canned filler.
3. Do not reveal internal reasoning or chain-of-thought narration.
4. Keep explanations concise and evidence-based when asked "why."
5. Ask clarifying questions only when truly blocked by missing required input.
6. Match tone to user context and acknowledge frustration briefly, then execute.

## Thomas Implementation Mapping

- Prompt contract:
  - `thomas/agent/prompt_templates.py`
  - Adds explicit no-internal-reasoning + concise-rationale rules.
- Output hygiene:
  - `thomas/agent/response_tone.py`
  - Removes thought-leak tags/phrases and internal-monologue narration.
- Loop integration + telemetry:
  - `thomas/agent/loop.py`
  - Applies sanitizer before final output and records suppression metrics.
- Regression coverage:
  - `tests/test_agent_loop_conversation.py`
  - Adds tests for thought-leak stripping and continuity metrics.
