### Fixed

- The first landing that should have swapped a plugin row in place (94d3dec26, the chat feedback row) was refused with "'RuntimePlugins' object has no attribute '_lock'": the swap took a lock the real row runtime never had, which only the test's stand-in carried. The swap now keeps a lock of its own, and the test's stand-in no longer carries one.
