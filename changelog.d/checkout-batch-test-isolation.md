### Fixed

- `already_in_running_copy` reads checkout-filtered blobs for files present on disk through one `git cat-file --batch --filters` process instead of one process per path. Binary and CRLF bytes are compared without text decoding; absent files are not submitted to the blob reader.
- Frame filtered output with random markers, never Git's unconverted size header: Git 2.52 can emit more bytes after CRLF conversion than the header reports. Ambiguous or incomplete framing fails closed.
- Added regressions with both `core.autocrlf=true` and explicit CRLF attributes for a single batch, missing-file skipping, exact CRLF and binary comparisons, the converted-size mismatch followed by another blob, and malformed framing. An external smudge filter regression checks length-changing output followed by another blob. Git fixture setup disables hooks, signing and filesystem monitoring and bounds each setup command to 20 seconds.
