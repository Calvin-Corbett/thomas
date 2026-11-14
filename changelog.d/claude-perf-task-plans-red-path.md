### Fixed

- **The task-plans check is now shown failing, and two test files stopped undoing each
  other.** The check that keeps each agent's claim, task and plan in agreement could block
  a commit but had never been shown to fail, so the suite that insists every blocking check
  proves it can fail had been refusing it. It now has a case that hands the check a task
  whose plan names a different owner and confirms the commit is refused, including when the
  suite runs inside another agent's session. Separately, two test files loaded the commit
  tool under the same internal name, so whichever loaded second replaced the copy the other
  was testing: one test passed on its own and failed in a full run. Each now uses its own
  name.
