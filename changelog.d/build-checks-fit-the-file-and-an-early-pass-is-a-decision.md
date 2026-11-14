### Fixed

- A Build pass that ends early (an unmet contract, the iteration cap, a full context window, three identical tool failures, a provider error) no longer ends the whole Build: the engine verifies what changed, then continues, asks you, or stops and says why. Each changed file now gets the check that fits it (Python tests to pytest, `node:test` files to `node --test`, everything else to the static checks), and a test file with no allowed runner is reported as unchecked instead of failed.
