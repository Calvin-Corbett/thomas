### Fixed

- **Reload on the Chat tab works again.** The Reload button and the context-menu Reload both said "Chat is still starting - try reload again" every time since 2026-09-07, because the page called a reload that was never written. It now re-reads your history, models and the open conversation in place, keeps your other tabs open, and leaves a running turn alone.
