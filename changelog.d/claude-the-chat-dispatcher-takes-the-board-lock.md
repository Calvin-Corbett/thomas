### Fixed

- **The chat dispatcher no longer overwrites a board change that lands while it writes.** `_add_task_to_workboard` and `_send_dispatch_message` read the whole board, edited it and wrote it back with no lock, so a message, a claim or a board archive in between was silently undone. Both now hold the shared board lock; a lock that times out leaves the board untouched and the task is reported as not mirrored.
