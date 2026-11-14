### Fixed
- Planner-picked pytest repairs that change only a changelog note now re-run the named test; when it passes, the project closes without a sign-in card and tells you in one line that the test already passes.
- The planner remembers that exact passing test node across scans, so old failure evidence does not book it again.
