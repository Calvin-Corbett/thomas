### Fixed

- When a self-project uses its last repair round and review sends its change back again, start a new project in the existing green checkout rather than abandoning the unfinished change. Carry the original request and remaining findings into the new team's first message, and retain the earlier project's hand-in history.
- Keep the Chat card following the successor instead of saying the unfinished change stopped, and reserve its green checkout between Build runs so another Chat request cannot claim it. After the last repair round, wait for the successor link to be written before deciding no successor started.
- If Build accepted a successor but the old project's link was not saved, recover the bound successor on retry rather than starting a second team in the same checkout.
- Wait for the Code-page steering watcher's handoff in its regression test instead of assuming a busy filesystem will complete the off-thread read within a fixed sleep.
- Scan persisted successor reservations off the Chat event loop when starting, sweeping or preparing a workspace; check a green's git directory only after finding a successor link, without invoking git or rewriting green metadata during that scan.
