### Fixed

- **"Waiting for your card" counts only the time a card's own sign-in was up.** Your window's loop and the card loop show one Windows sign-in at a time, so a self-fix card can wait behind a window card (an undo or a revert card stays up until you answer it). That wait was counted as the self-fix card's own prompt time in the project list and in "Slowest today"; each card is now timed from the moment its own prompt could show.
