### Fixed

- Your branch-claim tests now record expiries counted from the day they run, so a later calendar date does not turn valid claims into past-date failures. The expiry-day boundary, reclaim order, CLI record, and push gate remain covered; intentionally expired 2020 records still exercise rejection paths.
