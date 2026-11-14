### Fixed

- The cage keepalive remembers Task Scheduler's Last Run Time before a successful server run request. If the server port is still down and that timestamp is unchanged on the next pass, it requests `/End` followed by `/Run`; an advanced timestamp leaves a slow-starting server alone.
- Server start diagnostics include Task Scheduler's status, Last Run Time, and Last Result before and after the request, plus the result of a recovery `/End`. A failed `/End` does not issue another `/Run`.
