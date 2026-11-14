### Fixed

- Your window keeps a blocking check after every landing through posting errors, record errors, and promoter restarts. It restores queued checks with the files landed so far in each window, reuses matching checker jobs, and records the result before allowing another landing. A restart also closes the previous window in its record. Unchecked landings remain unproven in the audit, and window-service failures hand pending changes back to their cards.
