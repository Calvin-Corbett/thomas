### Changed
- Automatic project planning now books distinct evidence-backed suggestions on the next queue check instead of limiting suggestions to two per hourly scan.
- The project queue fills available machine and model capacity without a four-project ceiling, while retaining memory, disk, shared-ledger, unreadable-project, and start-failure checks. Admission counts all active Code runs, not only Thomas projects, and does not spend retries when those runs fill Build's slots.
- The Improve Thomas queue shows running and starting counts and why another project cannot start.
