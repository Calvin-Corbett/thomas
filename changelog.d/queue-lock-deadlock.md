### Fixed
- Queue selection checks capacity before the locked queue update, then revalidates the due row and newly marked starts without reacquiring the capacity ledger lock.
