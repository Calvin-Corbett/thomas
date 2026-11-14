### Added

- **The caged Thomas can become your everyday Thomas, with your things in it.**
  - `scripts/cage/move_owner_data_to_cage.py` copies your chat history, long-term
    memory, preferences, goals, schedules, workspaces and linked-project list into
    the caged Thomas's own data. SQLite stores are copied through SQLite's backup, so
    recent writes are kept. Chats the caged Thomas already had are kept, and anything
    replaced is backed up. Locks and the run store are deliberately left behind.
  - `scripts/cage/move_secret_to_cage.py` hands a secret to the cage account through
    a named pipe that only that account can open. Your process decrypts, the cage's
    process encrypts it again, and the value never touches a file.
  - `python scripts/thomas_app.py --caged` points the Thomas shortcut at the caged
    server (port 8898). The desktop shell then starts that server only through its
    scheduled task, never as you. The plain install is the rollback.
