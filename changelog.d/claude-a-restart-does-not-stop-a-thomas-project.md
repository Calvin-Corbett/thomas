### Fixed

- **A restart no longer stops your Thomas projects.** Before, when the server
  restarted, a Build run it was doing on Autopilot just stopped. The listing
  kept calling the project "running". The only way to get it going again was to
  send it a message, and Autopilot's done check then treated that message as the
  whole goal. Now, once the restarted server can start runs, each Autopilot run
  it was doing starts again by itself, once. The new run's message starts with
  Autopilot's own prefix, so your request stays the goal and the fuse does not
  count it. It says in plain words that the server restarted and the work picks
  up where it stopped. It also carries the stopped run's message in full, so a
  repair round keeps its findings and a done check stays a done check.
  - A run counts as stopped by the restart when its start is recorded (its
    conversation turn, and Build's run receipt says "running") but no end is,
    and it started before this server did.
  - Some are left alone: a project handed in to your card, one you stopped, one
    waiting out a usage limit (the pause handles it), one whose run is already
    going again, and one another Thomas server started. Two servers can share
    this checkout's catalog, but each keeps its own run receipts, so a run with
    no receipt here was not this server's.
  - Some are not restarted, and the listing says they stopped when the server
    did: a run that started more than 3 hours before this server did, one that
    3 restarts in a row stopped before any run finished, one whose result was
    lost after it ended, and one not on Autopilot.
  - If the new run dies too, Autopilot's usual rules take over. Ordinary Build
    conversations on Autopilot are handled the same way, after Thomas projects.
  - The stopped run's helpers, which Praxis restarts when the server starts, are
    closed, so only one team works in the folder.
  - A project Chat started gets a new card in that chat. The card says the work
    is going again and follows it to the end.
