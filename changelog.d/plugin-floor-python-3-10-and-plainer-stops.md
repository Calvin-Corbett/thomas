### Fixed

- **The plugin list and closing Thomas no longer need Python 3.11.** `pyproject.toml` says 3.10 is enough, but the list of plugins could not be read there and the code that runs the server and closes it could not begin. Ctrl+C, a restart and a plugin that will not end now behave the same on 3.10 as on 3.12, except for a worker thread that never ends, which only 3.12 can stop waiting for. A whole server start on 3.10 has not been proven.
- **A request that ignores being stopped can no longer hold Thomas open.** A forced stop went on without it and named it in the log, but the close then waited for its connection, which could only end when the request did. The port was closed, the lock stayed and a restart never happened. What waits on code a stop gave up on now gets the same limit that code does.
- **When a forced stop leaves a request running, the log now names its route.** It used to give a task number such as Task-100, which told you nothing about what was left.
- **A plugin refused for taking an address Thomas already answers now names the method its author wrote.** The reason said HEAD when both sides had asked for GET.
- **Stop now on a plugin stuck in a stopping step now takes its limit once.** It could hold for 20 seconds where the limit is 10.
