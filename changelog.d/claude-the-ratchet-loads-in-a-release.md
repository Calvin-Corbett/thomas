### Fixed

- **A release can load the ratchet's code, and refuses a run with the reason.** A release leaves out `scripts/cage`, so importing the ratchet stopped at `No module named scripts.cage`, the server logged that, and `/api/ratchet` did not exist there. The two steps that use those checks now read them when a run reaches them, and a copy without them is refused before it gets that far, whichever account it runs on, in words that say why. Chat's `self.unlanded` also reads the ratchet's report when you ask, where before the whole package was imported at every start.
