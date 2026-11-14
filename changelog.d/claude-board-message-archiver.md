### Added

- **Old messages now leave the coordination board by themselves.** `python scripts/praxis/archive_board_messages.py --apply` appends them, word for word, to `plans/thomas/archive/messages-YYYY-MM.txt` and shrinks `plans/thomas/WORKBOARD.md` in the same run. Acknowledged messages older than seven days and unacknowledged p1, p2 and unprioritised messages older than fourteen days move; everything newer stays, and so does the latest message of each sender and task that is still live and the newest row that names a plan file nothing else names. An unacknowledged P0 message never moves by age, because an open P0 is what stops an agent from committing until someone acks it. `--strict` keeps every unacknowledged message, `--max-rows N` caps one run, and `--restore all` (or one `YYYY-MM`) puts the rows back byte for byte. The run output lists how many unacknowledged rows moved per priority and how many open P0 rows stayed (`kept_by_reason.open-p0`). It is a dry run unless you pass `--apply`, takes the same board lock as `message.py`, and proves before it writes that restoring would give your board back exactly.
- **`scripts/praxis/archive_append_only.py`** checks staged changes under `plans/thomas/archive/`: only `messages-YYYY-MM.txt` files, only added or appended to. It is not wired into a gate yet.

### Fixed

- **A torn multi-byte character at the end of an archive file no longer stops the archiver.** Only the incomplete line is skipped and logged; every verified block still restores.
