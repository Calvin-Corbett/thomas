### Changed

- **The Build run limit is your machine's own, measured, not a fixed 8.** You asked:
  "make it estimate the most the hardware can do and set that as the limit. this will
  need to happen to everyone who installs as part of the first start up." Every install
  used to cap concurrent Build runs at the same 8 (raisable to a hard 64 via an
  environment variable) no matter whether the machine had 4 cores or 128. A new
  `thomas.core.machine_capacity` module estimates a ceiling from this computer's CPUs and
  memory on first start (and every start after, in case the hardware changed), refines
  the memory budget from what runs actually use once five have been observed, and caps
  the result at 100 so no machine, however large, offers an unbounded number of slots.
  `THOMAS_MAX_CONCURRENT_CODE_RUNS` still overrides it, clamped to that same 100. A new
  `GET /api/machine/capacity` reports the number and why.
