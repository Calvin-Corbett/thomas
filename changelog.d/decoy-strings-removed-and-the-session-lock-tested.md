### Fixed

- Two strings of Python that never ran are gone from your server; they were kept only so tests reading those files would find the lines they searched for. Those tests now run the code instead: they build the server app and check its per-session lock registry. Your chat behaves the same: a second message to a chat that is still answering waits its turn.
