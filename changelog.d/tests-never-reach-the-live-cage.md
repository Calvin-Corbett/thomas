### Fixed
- A test can no longer write into the live cage. Under pytest, the cage folder refuses to resolve to C:\ProgramData\ThomasCage unless a test points it elsewhere: on 2026-10-24 a copy of a test run outside tests/ and a fixture shared across tests wrote fake hand-ins into your inbox, and the promoter made a card of one.
