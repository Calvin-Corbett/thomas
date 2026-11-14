### Changed

- **Chat sessions and the run log now have a named place in the program.** Each folder of sessions has one store per process, handed out by `thomas.chat.session_slot`, and the server's own plugin list can ask for the sessions, the run log and the model slot. Chat no longer falls back to a `.thomas/sessions_v2` folder in whatever directory Thomas was started from: if it is not told where to keep your sessions it says so instead of writing there.
