### Fixed

- Since 2026-09-24, Thomas's memory and your library were not sent to the model; now they are, on the first turn of each run. They were looked up for every message you sent and then dropped, and the acceptance contract, which travels the same way, reaches the model again too.
