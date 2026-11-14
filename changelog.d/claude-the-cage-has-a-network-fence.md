### Added

- **The caged Thomas can reach only the hosts you pinned.** A Windows Firewall rule
  blocks every outbound connection the cage account makes to anything but loopback.
  Its one way out is a proxy that runs as you, inside the self-change promoter
  service, on 127.0.0.1:8897. The proxy opens a tunnel only to a host listed in
  `C:\ProgramData\ThomasPins\egress.allow`, which only an administrator can change:
  the model providers Thomas is configured for, the Codex sign-in, PyPI and npm.
  `scripts/cage/enable_network_fence.ps1` sets it up at one UAC prompt. It proves
  the fence from the cage account's own side, and takes it back out if the fence
  does not hold or the models become unreachable. Measured on 2026-09-23 as the
  cage account: a direct connection went from 200 to blocked, an unpinned host was
  refused, a model host connected, and the caged Thomas answered a chat through the
  proxy. Your own account is not fenced.
