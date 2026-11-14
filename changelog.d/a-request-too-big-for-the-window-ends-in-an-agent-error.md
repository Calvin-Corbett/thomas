### Fixed
- You now receive an agent error with the required token count and message budget when your instructions and latest request cannot fit the model window; the run stops before sending the oversized request to the model instead of raising a traceback.
