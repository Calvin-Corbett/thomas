### Changed

- **A change whose check gives no answer three times is parked with a note instead of being checked again for hours.** A check that broke the same way with the change and on dev counted no strike, so the change was checked again up to 96 times, each a full check: one change was checked 22 times (48 test hours). After the third such check the change now waits, never handed in unchecked, with a note saying why and one recorded issue, until its team's next turn. You chose this on 2026-10-29: "Park after 3, tell me".

### Fixed

- **Checks in the cage no longer break because importing `coverage` lists the folders above the copy.** The real-data tripwire counted that listing of `LOCALAPPDATA\Thomas` as touching your data and failed every such run with all its tests passed, so the check blamed dev and tried again. Each check's clocks record now also keeps its own line, so a check that gave no answer can be read afterwards.
