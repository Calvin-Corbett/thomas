### Fixed

- **Checking whether an agent is still running no longer sends Ctrl+C on Windows.** Thomas's presence checks asked whether an agent's process was alive with `os.kill(pid, 0)`. On Windows, signal 0 is `CTRL_C_EVENT`, which can interrupt every process sharing the console, and every startup router's presence check made that call. Thomas projects running side by side kept dying with KeyboardInterrupt, and one of those projects' own teams found the cause. Windows is now asked through `OpenProcess` and `GetExitCodeProcess` instead, and still tells a running process from a finished one.
