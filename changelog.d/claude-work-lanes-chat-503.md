### Fixed

- **Chat answered 503 because a commit of mine carried half of somebody else's
  change.** `chat_v2.py` imported `begin_codex_turn` and `end_codex_turn` from
  `thomas.core.llm_streaming`, where neither has ever existed. The half of that
  work defining them was still uncommitted when `74de225a` swept the call sites in
  from the shared index, so importing the module raised `ImportError`, `POST
  /api/chat` and `/api/v2/chat` answered `503 chat_v2_registration_failed`, and
  `/api/health` reported chat as degraded. The call sites are removed rather than
  reimplemented — guessing at the sticky-routing semantics of another agent's
  feature would be worse than its absence, and codex can land that change whole.
  This is the shared index doing its damage from the other direction: not taking
  work from an agent, but *committing* work an agent had not finished.

- **And the same commit made `chat_v2.py` import a module that is not in git.**
  `thomas/server/chat_attachment_context.py` is untracked, so a clean clone could
  not import the chat routes at all — the `begin_codex_turn` failure was simply
  raised first and masked it. That layer is backed out too, restoring the plain
  `prompt_with_documents` call it had wrapped. Backed out rather than completed for
  the same reason: publishing another agent's unfinished feature is what caused
  this, and doing it again to repair it would be worse.
