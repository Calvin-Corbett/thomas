### Changed

- **Reading a Thomas project's change can now be turned off and on while Thomas runs.** `GET /api/self/projects/{conversation_id}/change` moved out of the server's fixed list into an entry called Stopped project changes, which ships on, so nothing changes until you turn it off. While it is off that address answers 404, and nothing you use changes, because no page in Thomas reads it. The project list, starting, sending back, handing in again and stopping a project are separate and carry on.
