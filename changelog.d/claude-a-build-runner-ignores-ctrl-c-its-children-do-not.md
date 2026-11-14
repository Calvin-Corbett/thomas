### Fixed

- **A Build run is no longer stopped by the Ctrl+C its own tree sends at the end of its pass.** On a console of its own, each run was still stopped with KeyboardInterrupt right after its team's final reply, so no run could finish and hand its work in. The runner now ignores a console Ctrl+C itself, while everything it starts still handles one: the runner's children behave as before and the run finishes.
