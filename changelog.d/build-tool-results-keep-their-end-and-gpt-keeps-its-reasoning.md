### Fixed

- A long tool result now keeps its start and its end instead of only its start, so a test run's verdict and error reach the model; the whole output is saved under the project's `.thomas/tool-output/` folder (never tracked by git) and `fs.read_file` can read the rest by line range. GPT now keeps its reasoning across the tool steps of one turn instead of re-deriving its plan at every step.
