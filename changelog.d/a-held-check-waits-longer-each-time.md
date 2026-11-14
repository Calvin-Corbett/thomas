### Changed
- A held change that could not be checked now waits longer after each try: 15 minutes twice, then 30, 60 and at most 120 minutes. Each try is a full check, and on 2026-10-27 a change that selected 1,961 test files ran past its hour limit nine times in one day while it was tried every 15 minutes. A wait for a usage limit's reset is unchanged.
