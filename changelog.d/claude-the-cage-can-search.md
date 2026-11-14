### Added

- **The caged Thomas can search the web and read what it finds, and the cage stays
  shut.** The network fence lets the caged Thomas (port 8898) reach the model
  providers and nothing else, so `web.search`, the browser shell's results page and
  `web.fetch` all failed inside it. A search broker now runs as you inside the
  promoter service, on 127.0.0.1:8896, beside the egress proxy:
  - It searches with the providers your Thomas already uses and returns only the
    title, url and snippet of each result. Every returned url can be read for an hour.
  - It reads a page only when that exact url came back from a search. A url with
    anything added, a page that was never a result, a `file://` url, and any page on
    this machine, on your network or at a private, link-local, site-local, multicast
    or reserved address is refused with a plain reason ("not a search result",
    "private address", "too large"). The name is looked up once and the connection
    goes to the address that was checked, so a name that answers differently the
    second time cannot reach your machine. Redirects (at most three) are checked the
    same way. Pages are read up to 2 MB, text only, within 30 seconds.
  - At most 60 searches and 120 reads a minute. Only a program on this machine can
    call it; a web page open in your browser cannot.
  - A broker that cannot start -- its port taken, an import that fails -- never
    takes the network proxy beside it down, and the promoter service tries it again
    every minute.
  - When `THOMAS_SEARCH_BROKER` is set (the caged server sets it once the fence is
    pinned), `web.search` and `web.fetch` go through the broker, so the browser
    shell's results page works in the caged Thomas with no change to the page, and
    `web.search`'s freshness (past day, week, month or year) goes through too. A
    `web.fetch` of a url that was not a search result says so, and says to search
    first. Your uncaged Thomas is unchanged.
- **The cage's way out comes back by itself.** Run
  `scripts/cage/enable_cage_keepalive.ps1` once, in a normal (not elevated)
  PowerShell: it registers ThomasCageKeepalive for your account, every 15 minutes and
  at sign-in. The keepalive starts the promoter service when nothing listens on
  127.0.0.1:8897 and the caged server when nothing listens on 8898, and says it
  started one only once its port is listening. It leaves the caged server stopped
  when its task is disabled, when `C:\ProgramData\ThomasCage\caged_server.off`
  exists, or when a tracked Python file the server loads has uncommitted changes, and
  it never ends a task. Its lines go to `C:\ProgramData\ThomasCage\keepalive.log`.
  It writes a line only when it acts, so no `keepalive.log` yet is normal while both
  ports are up; the setup script says so and says to check that
  `(Get-ScheduledTaskInfo -TaskName ThomasCageKeepalive).LastTaskResult` is 0.

### Fixed

- **When the network proxy is down, Chat says so instead of blaming the model.** From
  2026-09-23 21:51 to 2026-09-24 11:10 the promoter service was not running, every
  model call from the caged Thomas failed, and Chat said "I couldn't get an answer
  from the selected model". Now, when a model call cannot connect and the proxy it
  goes through is refusing connections, Chat says "Thomas's network proxy (the
  promoter service) is not running" and that it restarts within 15 minutes or at your
  next sign-in; the 15 minutes hold once the keepalive task is registered. A model on
  this machine is never blamed on the proxy, and "OAuth is not connected" keeps its
  sign-in wording.
- **Search says which part is down.** When the search broker does not answer,
  `web.search` and `web.fetch` say whether only the broker is down (the promoter
  service starts it again within a minute) or the whole promoter service (it
  restarts at your next sign-in, and within 15 minutes once the keepalive task is registered).
- **The promoter service writes down why it stopped.** It logs a line at every normal
  exit and the error of anything that stops it, from the moment it has taken its
  lock, so a stop with neither was a kill from outside.
