### Security

- **A check that could not block a commit was still blocking commits.** Three inbox
  checks were deliberately made advisory so that a coordination message arriving mid-run
  could not strand finished work. The hook configuration was updated; the commit tool,
  which starts the same check by a different route, was not — and the check's own
  documentation already described the commit path as advisory, so the behaviour and the
  explanation had been out of step. In practice an inbox could be empty at the moment a
  commit began and a message arriving during the run would end it, repeatedly. Both
  registrations now agree, and a new check compares them by the script they run rather
  than by name, so the next half-applied change fails instead of going quiet.
