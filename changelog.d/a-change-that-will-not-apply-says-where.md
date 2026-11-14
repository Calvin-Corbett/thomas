### Fixed
- When the check before your card cannot apply a change to dev, the team is now told which files and lines git refused. On 2026-10-26 a change came back with only git's "Falling back to direct application..." (one line for each file git had no 3-way base for), repeated until the 2,000 characters the team is shown ran out. Those lines are now counted in one line, after the errors.
