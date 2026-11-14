### Fixed

- Extract text, PDF and Office uploads with bounded readers instead of treating binary files as plain text. Retain attachment context for the owning conversation and ignore forged client extraction text.
- Serialize completed-media announcements with the conversation's current turn, preserve saved session metadata and artifact receipts, recognize already-saved announcements, and mark a result reported only after its reply is saved.
