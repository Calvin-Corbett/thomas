### Fixed

- **The shell a Build run gets finds python, pytest and ruff.** In the cage, Build teams got a shell and still could not run one test: "python: command not found". The runner runs on Thomas's own environment, but nothing put it on PATH for the agent's shell, so one team made 124 shell calls looking for a Python. The runner now adds its own environment's scripts folder to PATH, last, so a project that brings its own Python still uses that one.
