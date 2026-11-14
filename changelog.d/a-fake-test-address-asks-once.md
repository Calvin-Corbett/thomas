### Changed
- A self-fix whose tests use a made-up address (such as `https://fixture.invalid`, `http://127.0.0.1:8888` or `https://ollama.example.com`) no longer asks you a second time, at the Windows sign-in, about "new network reach". Only addresses that can never be on the internet count as made up: this machine, and the names reserved for examples and tests (`.example`, `.invalid`, `.test`, `.localhost`, `example.com`, `example.net`, `example.org`). Any other address on the same line, or one hidden behind a fake one such as `example.com@elsewhere`, still asks.

### Fixed
- An added line whose own text starts with `++` is now checked for network reach too. Before, it looked like a file header in the diff and was skipped. A URL written in capitals (`HTTPS://`) is now caught as well.
