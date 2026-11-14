### Changed

- **The list of what your windows landed can now be turned off and on while Thomas runs.** `GET /api/self/windows` moved out of the server's fixed list into an entry called Window records, which ships on, so nothing changes until you turn it off. While it is off that address answers 404, and nothing you use changes, because no page in Thomas reads it. The records of your windows are only ever read, so they are untouched either way, and the Landed in line on a change's card does not use this list.
