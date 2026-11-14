### Added

- **Part 4's pass line is read from the window's own record.** `scripts/praxis/window_audit.py` counts your sign-ins and the changes each window landed, and fails the line for any window landing without its write-ahead record, a check that passed the exact tree that landed, or a safe second look of that exact change; any window landing with no check after it landed; any change dev holds twice, any landing dev does not hold or that has no verdict, and any landing the promoter stopped inside that was never settled.
