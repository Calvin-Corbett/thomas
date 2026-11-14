### Fixed

- The Windows checker launches the runner with a short command line and passes the full test argv through a file, so a long pytest selection does not exceed `CreateProcessWithLogonW`'s command-line limit. The launcher declares pointer-sized Windows handles before putting the suspended process in its kill-on-close job.
