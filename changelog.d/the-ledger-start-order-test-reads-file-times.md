### Fixed
- **You can run the reservation-ledger start-order test without depending on a wall-clock reading matching a file timestamp.** The test sets the ledger write time from the first owner's lock file and verifies both owners' file-time order before checking that the unreadable ledger stays in place.
