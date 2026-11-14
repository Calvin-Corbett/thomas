### Fixed
- A finished project with a very large conversation no longer crashes its hand-in. Thomas reads each earlier run's record only as far as any decision reads it, so a 9 MB conversation is no longer held whole, and a conversation that cannot be read at all, or runs out of memory, holds the change for its next try and says so on your project list instead of stranding it.
