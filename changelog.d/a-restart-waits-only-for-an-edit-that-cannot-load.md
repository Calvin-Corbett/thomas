### Fixed

- **Thomas restarts himself again when other work is left uncommitted.** A restart for landed code used to wait while any server file in the checkout had an edit nobody had committed. From 2026-11-07 to 11-09 that was always true (40 files left by other sessions), so he did not restart himself once and you had to press Restart. Every start already loads those files, so the wait protected nothing. Now a restart waits only for a file Python cannot read yet, and the banner names that file. You said: "Now I can't even restart himself."
