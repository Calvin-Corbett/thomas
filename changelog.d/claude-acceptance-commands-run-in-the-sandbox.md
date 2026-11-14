### Changed

- **A check an agent wrote now runs in the cage when you have the cage on.** The acceptance contract's commands and the subtask checks started their own process as the server's account whatever your cage setting said. They now go through the sandbox: caged when the cage is on and answering, here when it is off, and refused with a plain message (never a pass) when the cage is required and not answering.
