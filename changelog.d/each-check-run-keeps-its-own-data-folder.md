### Fixed

- **Two checks of one change no longer delete each other's files.** Every check kept its reports and selection files in a folder named after the change, and removed that folder when it ended. Tests that check the same fixed change ran side by side in the shards of a real check, so the first to end deleted the other's selection file and a test failed with nothing to do with your change. Each check run now has its own folder.
