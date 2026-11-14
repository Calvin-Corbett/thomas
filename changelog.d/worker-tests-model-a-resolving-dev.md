### Fixed

- The workboard worker test fakes now answer the exact `git show-ref --verify refs/heads/dev` probe with a sha line, as required since 9ac14311; the refusal test asserts the non-ancestor reason and fails if its fake stops resolving dev.
