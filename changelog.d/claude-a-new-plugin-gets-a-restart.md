### Fixed

- **A landing that adds a new plugin now restarts Thomas by itself.** A plugin the running server never loaded cannot be swapped in live. Thomas said so, but treated it as a broken plugin: he showed "the plugin swap was refused" with a Restart button and waited. On 2026-11-10 the landing that added "Look inside the cage" sat that way and the server never loaded it. Such a landing now goes to the ordinary restart, and the notice names the new plugin.
