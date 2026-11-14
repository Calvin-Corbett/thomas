### Changed

- **Thomas now records how long a run takes to produce its first words, thought or tool call.** You said it took minutes before he said anything, and there was no way to tell whether that was the startup or the model. The first output of each run is written once to the step log (`run_first_output`, with its seconds and kind), so the next slow first reply names its cause.
