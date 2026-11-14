### Fixed

- Build helpers now check their assigned output inside their private workspace before integration. Concurrent helpers retain separate verification roots, and a failed check leaves its candidate unapplied. The lead still verifies the combined project.
- Bound the team deadline regression waits and join its owned task on every exit, so a slow filesystem produces a test failure instead of an indefinite hang.
- Isolate synthetic completion-gate coding cases in temporary projects, retaining the structured failure assertions without inspecting unrelated files in the checkout running pytest.
