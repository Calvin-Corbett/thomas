### Added

- **A Thomas project starts without Chat.** Only Chat's `send_task` could start
  one, so on 2026-09-24, with Chat's own model rate-limited, no new Thomas
  project could start although Build ran fine on Claude. `POST
  /api/self/projects` with `{request, settings, chat_session_id?}` now starts
  one: Build's task manager and team in a private copy of Thomas, handed in to
  your sign-in card as before. The settings are Build's own (model, model_id,
  reasoning_effort, autonomy_level, file_access, memory, guardrails,
  token_economy, build_roles), checked the way Build's send route checks them,
  and any other key is refused. The request reaches Build in the same words
  Chat's does, with the same `TITLE:` line, changelog.d rule, size rule and the
  files the other running projects have changed. With `chat_session_id`, the
  approval card and its verdict also show in that chat. A refusal says why, with
  status 400 or 409.
- **`GET /api/self/projects` says where each Thomas project stands**: its
  conversation, its copy, running, repair round N, paused, stopped, awaiting
  your verdict, landed, declined or refused, the promoter's last verdict in its
  own words, and the files it changes. It only reads: it never stages a copy
  under a running team or acts on a verdict.
- Both answer only on this machine, and only to the Thomas UI itself: a caller
  from another machine, or a page from any other origin, is refused, and neither
  sends CORS headers.
