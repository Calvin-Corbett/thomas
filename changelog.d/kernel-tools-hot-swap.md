### Added
- Edit-capable Build turns opt in to kernel-mounted tools before loop construction; read-only and lower-autonomy Build turns keep their existing tool boundaries.
- The server registers a provider for its tool registry on the kernel tools seam at plugin startup. Installed plugins exposing `get_tools()` can contribute tools to subsequent server Chat and worker loop construction; unplug removes those tools without restarting.
- Regression tests mount an installed plugin with a tool, check worker and Chat V2 turn tool discovery and execution, then unplug it through the plugin supervisor. An empty enabled registry can receive its first plugin tool; restricted and tools-disabled turns do not acquire plugin tools.

### Fixed
- Re-resolving nested mounted tool views during worker loop construction keeps denied tools absent when two plugins are mounted, rather than re-adding the first plugin's tool.
- A plugin returning a non-Tool or a tool without a name fails its mount before it can affect the next turn's registry; the supervisor reports the failure.
