### Fixed

- **Only a refused connection skips the second status probe of the image service.** The earlier change skipped the second probe after any connection error or timeout. A busy ComfyUI that answers one path slowly or resets one request can still answer the other, and `boot()` trusts the status to say whether one is already running, so a timeout or a reset now still gets its second probe. A refused connection, where nothing listens on the port, is the only case that skips it, and `close()` with no process of its own still returns at once.
