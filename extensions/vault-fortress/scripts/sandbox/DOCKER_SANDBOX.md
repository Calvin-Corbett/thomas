# Docker Sandbox Mode

If Docker Desktop is installed, you can run secret-touching tools in a container.

Suggested hardening flags:
- --network none (default deny)
- --read-only
- --cap-drop ALL
- Mount only explicitly allowed directories

On Windows, Docker Desktop runs Linux containers in a VM, giving a real isolation boundary.
