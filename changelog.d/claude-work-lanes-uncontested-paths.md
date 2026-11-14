### Added

- **A file nobody else wants no longer refuses your commit.** The claim gates
  refuse any commit whose files are not in your board claim — including files no
  agent on the board has any interest in. That refusal protects nobody, because
  nobody else wants the file; it is pure ceremony, every agent pays it on every
  commit, and it is the most common reason an agent reports being blocked.
  `autoclaim` widens your claim to cover the staged paths no other agent holds, and
  leaves contested ones alone while naming who holds them — so a real collision
  still refuses, with information you can act on. It never narrows anyone's claim,
  so it cannot take work from an agent mid-flight, and it never fails a commit: it
  is an unlock, not a gate. Outside a commit hook it refuses to read the shared
  index at all, because that index holds other agents' in-flight work and claiming
  it would be the opposite of the point — a mistake I made by hand before the
  guard existed.
