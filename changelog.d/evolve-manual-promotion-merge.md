### Fixed

- Manual evolve promotion requires a dedicated passing non-Python verifier for non-Python deltas before promotion proceeds to dev's signed-manifest, delta-drift, supervisor, and verifier-panel checks. The merge retains dev's shared verifier helpers and acceptance-repair coverage.
- PR signature verification configures the repository SSH allowed-signers file before checking commit signatures.
