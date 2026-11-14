### Fixed
- Your tray-started server now watches landed server Python changes and reloads after in-memory work has drained, without relying on the caged server's owner-desk setting or disabled marker.
- Tray-started servers track handled commits by port, so a separate server does not suppress their reload.
