### Changed

- **The Praxis keys and the port helpers now live beside the other server keys.** Nine files only needed a name such as the start-run key or the port you listen on, but each one loaded Praxis code at the top just to read it. They now read it from `app_keys.py`, and the Praxis launch file loads its Claude child runner and run journal when it first uses them. Nothing you see changes.
