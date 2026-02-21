# Model Onboarding Log

Every model-surface change must append an entry here.

Required per entry:
- Date
- Profiles changed
- Research note path(s) under `library/entries/research-notes/`
- Validation command + result (`thomas models validate --strict`)
- Risk notes / follow-ups

---

## 2026-02-17 - Protocol and CI hardening baseline

- Profiles changed: none (process hardening only)
- Research notes:
  - `library/entries/research-notes/1771337423-what-did-you-find.md`
- Validation:
  - Command: `thomas models validate --strict`
  - Result: required by CI gate on model-surface changes
- Notes:
  - Added surface parity checks for server/web/CLI event contracts.
  - Added model onboarding gate to block untracked model-surface edits.

## 2026-02-19 - Access and tool-policy stabilization

- Profiles changed: local/openai behavior contracts (tool exposure + remote access policy handling)
- Research notes:
  - `library/entries/research-notes/1771456503-voice-no-man-just-go-in-there-and-look-in-there-and-tell-me-what-they-are-dude.md`
- Validation:
  - Command: `python scripts/doc.py --skip-gates`
  - Result: pass (`51 passed`)
- Notes:
  - Tightened remote vs local tool policy behavior in `AgentLoop`.
  - Re-aligned remote API token enforcement for run/audit endpoints.
  - Added Doc runner script for repeatable gate/test sweeps.
