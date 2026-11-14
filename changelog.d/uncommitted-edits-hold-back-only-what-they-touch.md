### Fixed

- A file someone is still editing in the checkout no longer stops every landing from loading. Until now any uncommitted server Python, anywhere, stopped the reload watcher and said nothing, and with several sessions editing at once that was nearly always, so a landing that should have swapped a plugin row in place (0b3d4286d) sat unloaded and the corner only said "newer code is available". Now a row swaps unless one of its own files is being edited, and the full-restart banner says which uncommitted files are holding a restart and how many.
