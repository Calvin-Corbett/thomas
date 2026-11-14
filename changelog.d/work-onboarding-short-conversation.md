### Fixed

- Work onboarding no longer rejects a configured workflow solely because the conversation has fewer than four user answers and four Thomas follow-ups (work-ui issue fingerprint `6be2e1db1088`).
- The ready transition accepts selection and configuration on the same recorded user turn, matching the job-creation gate. It still rejects missing, non-integer, boolean, non-positive, and future selection markers and requires a confirmed goal, workflow map, explicit selection, and configured workflow.
- Added HTTP-route regression coverage for short conversations and same-turn configuration, with store checks for invalid selection markers and unfinished configuration.
