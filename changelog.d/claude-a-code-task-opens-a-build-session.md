### Fixed

- **A code task now opens a Build session you can actually watch.** Chat dispatch ran the task in a bare `~/.thomas/workspaces/<exec-id>` folder while Build lists conversations under project roots, so Build sat empty for the whole life of a real run even though every tool call was being recorded. A coding task now mints its own project, starts a conversation in it and binds that conversation, which is the same three steps the Build-initiated path already took.
- **Minting the project no longer blocks the server.** It shells out to git, and dispatch is a coroutine, so doing it inline stalled every other request for the duration. It now runs off the event loop, as the Build route already did.
- **A Build session that cannot be opened no longer takes the task down.** If the project cannot be minted the work still runs, in the plain workspace it used before, and the reason travels with it instead of being swallowed.

### Changed

- **The chat delegation tests are six focused modules instead of one 1676-line file.** That file was already past the 1200-line hard limit, and the monolith guard only fires on a file you touch, so it sat in violation until a one-line change needed to go in. The worker run cases now live in `test_chat_delegation_worker_*`, the shared fixture and stubs in `tests/chat_delegation_support.py`, and every one of the original tests still runs.
