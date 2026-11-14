### Changed

- **Stopping a Build run no longer goes through a named call.** Build hands its stop function to Praxis directly when it starts, so your Stop button reaches the same function as before with one less lookup in between.
