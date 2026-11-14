### Security

- **Checks that did not run where the work actually happens.** The tool agents commit
  through creates commits by a route that never triggers the project's check system, so it
  kept its own separate list of checks, and nothing had ever compared the two. Eight checks
  were missing from the list agents actually run, including both formatters and the
  anti-tamper check for the check scripts themselves, which means the check that notices a
  safety script has been altered was absent from the route used to alter them. Six now run
  there, verified under the same conditions a real commit creates. A seventh judges the
  repository as a whole rather than the commit being made, and the project had already
  moved it to the readiness check that runs before work is published, so it stays there and
  a new check confirms that coverage is real. The eighth, the snapshot meant to protect
  uncommitted work when a commit is refused, is deliberately held back: review found that
  restoring from it in a shared checkout can apply another agent's unfinished work over
  yours, so spreading it to every commit would spread that risk rather than the protection.
  That decision is recorded with its evidence and an expiry date, and a check fails when the
  date passes so it cannot quietly become permanent. A new check compares the lists and fails
  when one has something the others do not account for, and the check that watches for
  untested safety checks now reads the new list too. Session start also told every agent
  that thirty-five checks were watching their commit, on a route where none were; it now
  counts what will really run and says which route it applies to.
