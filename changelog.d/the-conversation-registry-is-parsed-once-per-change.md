### Changed

- **Looking up which project a Build conversation belongs to no longer re-reads the whole list every time.** The list of conversations and their projects (536 of them, 1.37 MB) was read from disk and parsed on every lookup, 27.9 ms each, from 23 places in Thomas, while the server read about a gigabyte from disk every two minutes. It is now parsed once each time the file changes, and every caller still gets a copy of its own to change: 10.0 ms a lookup on the real list.
