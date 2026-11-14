### Fixed
- Restore the saved Chat model on browser refresh and finish Chat initialization before accepting a turn.
- Keep streamed replies, cancellation, task details, and late session creation attached to the conversation that started them.
- Preserve the next unsent draft's attachments while queued follow-up messages run with their own files.
- Refresh saved conversations without overwriting newer activity. Stop reaches delegated work and stays bound to the original reply; failed cancellation remains retryable.

- Newly created conversations become the saved selection restored after refresh.
- Keep the browser bar's selected model consistent across loaded and late-loading tabs.
- Retain each queued turn's selected model, files and original conversation; wait for that model to become available and resume once without consuming a newer draft.
- Restore the Create menu for attachments and media, retain original media replies across navigation, and present failed-task files as unverified downloads without previewing them as successful results.
- Extract uploaded documents into readable attachment context and keep delayed extraction bound to the original draft.
- Create Build projects with an in-page form, retain navigation ownership during delayed discovery, preserve interactive previews at activity-feed rollover, and disclose when saved change history is disabled.
