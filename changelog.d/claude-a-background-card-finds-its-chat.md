### Fixed

- **A card from background work shows in the chat that asked for it.** A worker
  looked for its chat under `session_id`, but the run's record names the chat
  `conversation_id`. The lookup found nothing, so the card was filed under the
  run's own id, which no page shows: an approval card waited ten minutes unseen on
  2026-09-22. The running Thomas already had this fix in its working copy; it is
  now committed with a test.
