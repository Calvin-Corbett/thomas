### Security

- **The file-size guard's waiver file now needs your approval to change, not just to
  commit.** `docs/monolith_guard_baseline.json` was on the protected list for commits,
  but nothing stopped an agent writing it while Thomas was running, and the guard reads
  that file live. On 2026-09-19 an agent did exactly that, waiving every violation in a
  copy of Thomas. The file joins the runtime-protected set, so a write is refused unless
  you approve it at the OS prompt, the same as `agent_safety.toml`.
