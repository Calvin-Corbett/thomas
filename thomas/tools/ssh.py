"""SSH remote execution tool with connection pooling and SFTP support."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from thomas.tools.base import Tool, ToolResult

# Try to import asyncssh, fall back to paramiko or subprocess
try:
    import asyncssh

    HAS_ASYNCSSH = True
except ImportError:
    HAS_ASYNCSSH = False

try:
    import paramiko

    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


# Custom exceptions
class SSHError(Exception):
    """Base SSH error."""

    pass


class SSHConnectionError(SSHError):
    """Connection establishment failed."""

    pass


class SSHAuthenticationError(SSHError):
    """Authentication failed."""

    pass


class SSHCommandError(SSHError):
    """Command execution failed."""

    pass


class SSHTimeoutError(SSHError):
    """Operation timed out."""

    pass


class SSHFileError(SSHError):
    """File operation failed."""

    pass


class SSHConnectionPool:
    """Connection pool for managing SSH connections."""

    def __init__(self):
        self._connections: dict[str, Any] = {}
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        """Detect which SSH backend to use."""
        if HAS_ASYNCSSH:
            return "asyncssh"
        elif HAS_PARAMIKO:
            return "paramiko"
        else:
            return "subprocess"

    async def connect(
        self,
        host: str,
        port: int = 22,
        username: str = "root",
        password: str | None = None,
        key_path: str | None = None,
        key_passphrase: str | None = None,
    ) -> Any:
        """Establish SSH connection (asyncssh backend)."""
        conn_key = f"{username}@{host}:{port}"

        # Return existing connection if available
        if conn_key in self._connections:
            conn = self._connections[conn_key]
            if self._backend == "asyncssh":
                # Check if connection is still alive
                try:
                    if not conn.is_active():
                        del self._connections[conn_key]
                    else:
                        return conn
                except Exception:
                    del self._connections[conn_key]

        if self._backend == "asyncssh":
            return await self._connect_asyncssh(host, port, username, password, key_path, key_passphrase, conn_key)
        elif self._backend == "paramiko":
            return await self._connect_paramiko(host, port, username, password, key_path, key_passphrase, conn_key)
        else:
            raise SSHConnectionError("No SSH backend available (install asyncssh or paramiko)")

    async def _connect_asyncssh(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        key_path: str | None,
        key_passphrase: str | None,
        conn_key: str,
    ) -> Any:
        """Connect using asyncssh."""
        try:
            known_hosts = os.path.expanduser("~/.ssh/known_hosts")
            known_hosts = known_hosts if os.path.exists(known_hosts) else None

            conn = await asyncssh.connect(
                host,
                port=port,
                username=username,
                password=password,
                client_keys=[key_path] if key_path else None,
                passphrase=key_passphrase,
                known_hosts=known_hosts,
                server_host_key_alg=["rsa-sha2-256", "rsa-sha2-512", "ecdsa-sha2-nistp256", "ssh-ed25519"],
            )
            self._connections[conn_key] = conn
            return conn
        except asyncssh.DisconnectError as e:
            raise SSHConnectionError(f"Connection refused: {e}")
        except asyncssh.PermissionDenied as e:
            raise SSHAuthenticationError(f"Authentication failed: {e}")
        except asyncssh.HostKeyNotVerifiable as e:
            raise SSHConnectionError(f"Host key verification failed: {e}")
        except Exception as e:
            raise SSHConnectionError(f"Connection failed: {e}")

    async def _connect_paramiko(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        key_path: str | None,
        key_passphrase: str | None,
        conn_key: str,
    ) -> Any:
        """Connect using paramiko (blocking, wrapped in asyncio)."""

        def _connect():
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(
                    host,
                    port=port,
                    username=username,
                    password=password,
                    key_filename=key_path,
                    passphrase=key_passphrase,
                    timeout=10,
                )
                return ssh
            except paramiko.AuthenticationException as e:
                raise SSHAuthenticationError(f"Authentication failed: {e}")
            except paramiko.SSHException as e:
                raise SSHConnectionError(f"Connection failed: {e}")

        loop = asyncio.get_event_loop()
        conn = await loop.run_in_executor(None, _connect)
        self._connections[conn_key] = conn
        return conn

    async def disconnect(self, host: str, port: int = 22, username: str = "root") -> None:
        """Disconnect from specific host."""
        conn_key = f"{username}@{host}:{port}"
        conn = self._connections.pop(conn_key, None)
        if conn:
            if self._backend == "asyncssh" or self._backend == "paramiko":
                conn.close()

    async def disconnect_all(self) -> None:
        """Disconnect all connections."""
        for conn in self._connections.values():
            try:
                if self._backend == "asyncssh" or self._backend == "paramiko":
                    conn.close()
            except Exception:
                pass
        self._connections.clear()

    async def execute(
        self,
        conn: Any,
        command: str,
        timeout: int = 30,
        sudo: bool = False,
        sudo_password: str | None = None,
    ) -> tuple[str, str, int]:
        """Execute command on remote host."""
        if sudo:
            if self._backend == "asyncssh" and sudo_password:
                # asyncssh doesn't natively support sudo with password
                # Use -S flag to read password from stdin
                command = f"sudo -S {command}"
            else:
                command = f"sudo {command}"

        if self._backend == "asyncssh":
            return await self._execute_asyncssh(conn, command, timeout, sudo_password)
        elif self._backend == "paramiko":
            return await self._execute_paramiko(conn, command, timeout)
        else:
            raise SSHCommandError("No SSH backend available")

    async def _execute_asyncssh(
        self,
        conn: Any,
        command: str,
        timeout: int,
        sudo_password: str | None = None,
    ) -> tuple[str, str, int]:
        """Execute command using asyncssh."""
        try:
            result = await asyncio.wait_for(
                conn.run(command, check=False, input=sudo_password.encode() if sudo_password else None),
                timeout=timeout,
            )
            stdout = result.stdout if result.stdout else ""
            stderr = result.stderr if result.stderr else ""
            return stdout, stderr, result.exit_status
        except asyncio.TimeoutError:
            raise SSHTimeoutError(f"Command timed out after {timeout}s")
        except Exception as e:
            raise SSHCommandError(f"Command execution failed: {e}")

    async def _execute_paramiko(
        self,
        conn: Any,
        command: str,
        timeout: int,
    ) -> tuple[str, str, int]:
        """Execute command using paramiko (blocking, wrapped in asyncio)."""

        def _exec():
            try:
                stdin, stdout, stderr = conn.exec_command(command, timeout=timeout)
                stdout_text = stdout.read().decode("utf-8", errors="replace")
                stderr_text = stderr.read().decode("utf-8", errors="replace")
                exit_code = stdout.channel.recv_exit_status()
                return stdout_text, stderr_text, exit_code
            except Exception as e:
                raise SSHCommandError(f"Command execution failed: {e}")

        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _exec),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise SSHTimeoutError(f"Command timed out after {timeout}s")

    async def upload_file(
        self,
        conn: Any,
        local_path: str,
        remote_path: str,
        mode: int | None = None,
    ) -> None:
        """Upload file via SFTP."""
        if self._backend == "asyncssh":
            await self._upload_asyncssh(conn, local_path, remote_path, mode)
        elif self._backend == "paramiko":
            await self._upload_paramiko(conn, local_path, remote_path, mode)
        else:
            raise SSHFileError("No SSH backend available")

    async def _upload_asyncssh(
        self,
        conn: Any,
        local_path: str,
        remote_path: str,
        mode: int | None = None,
    ) -> None:
        """Upload file using asyncssh SFTP."""
        try:
            async with conn.open_sftp() as sftp:
                await sftp.put(local_path, remote_path)
                if mode:
                    await sftp.chmod(remote_path, mode)
        except Exception as e:
            raise SSHFileError(f"File upload failed: {e}")

    async def _upload_paramiko(
        self,
        conn: Any,
        local_path: str,
        remote_path: str,
        mode: int | None = None,
    ) -> None:
        """Upload file using paramiko SFTP (blocking, wrapped in asyncio)."""

        def _upload():
            try:
                sftp = conn.open_sftp()
                sftp.put(local_path, remote_path)
                if mode:
                    sftp.chmod(remote_path, mode)
                sftp.close()
            except Exception as e:
                raise SSHFileError(f"File upload failed: {e}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _upload)

    async def download_file(
        self,
        conn: Any,
        remote_path: str,
        local_path: str,
    ) -> None:
        """Download file via SFTP."""
        if self._backend == "asyncssh":
            await self._download_asyncssh(conn, remote_path, local_path)
        elif self._backend == "paramiko":
            await self._download_paramiko(conn, remote_path, local_path)
        else:
            raise SSHFileError("No SSH backend available")

    async def _download_asyncssh(
        self,
        conn: Any,
        remote_path: str,
        local_path: str,
    ) -> None:
        """Download file using asyncssh SFTP."""
        try:
            async with conn.open_sftp() as sftp:
                await sftp.get(remote_path, local_path)
        except Exception as e:
            raise SSHFileError(f"File download failed: {e}")

    async def _download_paramiko(
        self,
        conn: Any,
        remote_path: str,
        local_path: str,
    ) -> None:
        """Download file using paramiko SFTP (blocking, wrapped in asyncio)."""

        def _download():
            try:
                sftp = conn.open_sftp()
                sftp.get(remote_path, local_path)
                sftp.close()
            except Exception as e:
                raise SSHFileError(f"File download failed: {e}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _download)

    async def list_directory(self, conn: Any, remote_path: str) -> list:
        """List remote directory contents."""
        if self._backend == "asyncssh":
            return await self._list_asyncssh(conn, remote_path)
        elif self._backend == "paramiko":
            return await self._list_paramiko(conn, remote_path)
        else:
            raise SSHFileError("No SSH backend available")

    async def _list_asyncssh(self, conn: Any, remote_path: str) -> list:
        """List directory using asyncssh SFTP."""
        try:
            async with conn.open_sftp() as sftp:
                entries = await sftp.listdir_attr(remote_path)
                return [
                    {
                        "name": entry.filename,
                        "size": entry.st_size,
                        "permissions": entry.st_mode,
                        "is_dir": entry.filename not in [".", ".."],
                    }
                    for entry in entries
                ]
        except Exception as e:
            raise SSHFileError(f"Directory listing failed: {e}")

    async def _list_paramiko(self, conn: Any, remote_path: str) -> list:
        """List directory using paramiko SFTP (blocking, wrapped in asyncio)."""

        def _list():
            try:
                sftp = conn.open_sftp()
                entries = sftp.listdir_attr(remote_path)
                result = [
                    {
                        "name": entry.filename,
                        "size": entry.st_size,
                        "permissions": entry.st_mode,
                        "is_dir": entry.filename not in [".", ".."],
                    }
                    for entry in entries
                ]
                sftp.close()
                return result
            except Exception as e:
                raise SSHFileError(f"Directory listing failed: {e}")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _list)

    async def read_file(self, conn: Any, remote_path: str) -> str:
        """Read remote file contents."""
        if self._backend == "asyncssh":
            return await self._read_asyncssh(conn, remote_path)
        elif self._backend == "paramiko":
            return await self._read_paramiko(conn, remote_path)
        else:
            raise SSHFileError("No SSH backend available")

    async def _read_asyncssh(self, conn: Any, remote_path: str) -> str:
        """Read file using asyncssh SFTP."""
        try:
            async with conn.open_sftp() as sftp:
                content = await sftp.read_text(remote_path)
                return content
        except Exception as e:
            raise SSHFileError(f"File read failed: {e}")

    async def _read_paramiko(self, conn: Any, remote_path: str) -> str:
        """Read file using paramiko SFTP (blocking, wrapped in asyncio)."""

        def _read():
            try:
                sftp = conn.open_sftp()
                with sftp.file(remote_path, "r") as f:
                    content = f.read().decode("utf-8", errors="replace")
                sftp.close()
                return content
            except Exception as e:
                raise SSHFileError(f"File read failed: {e}")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read)

    async def write_file(
        self,
        conn: Any,
        remote_path: str,
        content: str,
        mode: int | None = None,
    ) -> None:
        """Write content to remote file."""
        if self._backend == "asyncssh":
            await self._write_asyncssh(conn, remote_path, content, mode)
        elif self._backend == "paramiko":
            await self._write_paramiko(conn, remote_path, content, mode)
        else:
            raise SSHFileError("No SSH backend available")

    async def _write_asyncssh(
        self,
        conn: Any,
        remote_path: str,
        content: str,
        mode: int | None = None,
    ) -> None:
        """Write file using asyncssh SFTP."""
        try:
            async with conn.open_sftp() as sftp:
                await sftp.write_text(content, remote_path)
                if mode:
                    await sftp.chmod(remote_path, mode)
        except Exception as e:
            raise SSHFileError(f"File write failed: {e}")

    async def _write_paramiko(
        self,
        conn: Any,
        remote_path: str,
        content: str,
        mode: int | None = None,
    ) -> None:
        """Write file using paramiko SFTP (blocking, wrapped in asyncio)."""

        def _write():
            try:
                sftp = conn.open_sftp()
                with sftp.file(remote_path, "w") as f:
                    f.write(content.encode("utf-8"))
                if mode:
                    sftp.chmod(remote_path, mode)
                sftp.close()
            except Exception as e:
                raise SSHFileError(f"File write failed: {e}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)


# Global connection pool
_ssh_pool = SSHConnectionPool()


class SSHTool(Tool):
    """SSH remote execution and file transfer tool."""

    name = "ssh.exec"
    category = "remote"
    description = (
        "Execute commands on remote SSH servers, transfer files via SFTP, "
        "manage connections, and create SSH tunnels. "
        "Supports password and key-based authentication with connection pooling."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "execute",
                    "upload",
                    "download",
                    "list",
                    "read_file",
                    "write_file",
                    "connect",
                    "disconnect",
                    "disconnect_all",
                ],
                "description": "Action to perform",
            },
            "host": {
                "type": "string",
                "description": "Remote hostname or IP address",
            },
            "port": {
                "type": "integer",
                "description": "SSH port (default: 22)",
            },
            "username": {
                "type": "string",
                "description": "SSH username (default: root)",
            },
            "password": {
                "type": "string",
                "description": "SSH password (password-based auth)",
            },
            "key_path": {
                "type": "string",
                "description": "Path to SSH private key file",
            },
            "key_passphrase": {
                "type": "string",
                "description": "Passphrase for encrypted SSH key",
            },
            "command": {
                "type": "string",
                "description": "Command to execute on remote host",
            },
            "timeout": {
                "type": "integer",
                "description": "Command timeout in seconds (default: 30)",
            },
            "sudo": {
                "type": "boolean",
                "description": "Execute command with sudo",
            },
            "local_path": {
                "type": "string",
                "description": "Local file path for upload/download",
            },
            "remote_path": {
                "type": "string",
                "description": "Remote file path",
            },
            "mode": {
                "type": "integer",
                "description": "File permissions (octal, e.g., 0o644)",
            },
            "content": {
                "type": "string",
                "description": "Content to write to remote file",
            },
        },
        "required": ["action", "host"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """Execute SSH tool action."""
        action = args.get("action")
        args.get("host", "")
        args.get("port", 22)
        args.get("username", "root")

        try:
            if action == "connect":
                return await self._handle_connect(args)
            elif action == "execute":
                return await self._handle_execute(args)
            elif action == "upload":
                return await self._handle_upload(args)
            elif action == "download":
                return await self._handle_download(args)
            elif action == "list":
                return await self._handle_list(args)
            elif action == "read_file":
                return await self._handle_read_file(args)
            elif action == "write_file":
                return await self._handle_write_file(args)
            elif action == "disconnect":
                return await self._handle_disconnect(args)
            elif action == "disconnect_all":
                return await self._handle_disconnect_all(args)
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

    async def _handle_connect(self, args: dict[str, Any]) -> ToolResult:
        """Handle connection establishment."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        password = args.get("password")
        key_path = args.get("key_path")
        key_passphrase = args.get("key_passphrase")

        if not host:
            return ToolResult(ok=False, error="host is required")

        try:
            await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=password,
                key_path=key_path,
                key_passphrase=key_passphrase,
            )
            return ToolResult(ok=True, data=f"Connected to {username}@{host}:{port}")
        except (SSHConnectionError, SSHAuthenticationError) as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_execute(self, args: dict[str, Any]) -> ToolResult:
        """Handle command execution."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        command = args.get("command", "")
        timeout = args.get("timeout", 30)
        sudo = args.get("sudo", False)
        sudo_password = args.get("password") if sudo else None

        if not host or not command:
            return ToolResult(ok=False, error="host and command are required")

        try:
            # Ensure connection exists
            conn = await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=args.get("password"),
                key_path=args.get("key_path"),
                key_passphrase=args.get("key_passphrase"),
            )

            stdout, stderr, exit_code = await _ssh_pool.execute(
                conn=conn,
                command=command,
                timeout=timeout,
                sudo=sudo,
                sudo_password=sudo_password,
            )

            # Build output
            parts = []
            if stdout.strip():
                parts.append(stdout.rstrip())
            if stderr.strip():
                parts.append(f"[stderr]\n{stderr.rstrip()}")
            parts.append(f"[exit code: {exit_code}]")
            output = "\n".join(parts)

            # Truncate very long output
            max_len = 100_000
            if len(output) > max_len:
                output = output[:max_len] + f"\n... (truncated, {len(output)} chars total)"

            return ToolResult(
                ok=exit_code == 0,
                data=output,
                error=f"Exit code {exit_code}" if exit_code != 0 else None,
            )
        except SSHCommandError as e:
            return ToolResult(ok=False, error=str(e))
        except SSHTimeoutError as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_upload(self, args: dict[str, Any]) -> ToolResult:
        """Handle file upload."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        local_path = args.get("local_path", "")
        remote_path = args.get("remote_path", "")
        mode = args.get("mode")

        if not host or not local_path or not remote_path:
            return ToolResult(ok=False, error="host, local_path, and remote_path are required")

        if not os.path.exists(local_path):
            return ToolResult(ok=False, error=f"Local file not found: {local_path}")

        try:
            conn = await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=args.get("password"),
                key_path=args.get("key_path"),
                key_passphrase=args.get("key_passphrase"),
            )
            await _ssh_pool.upload_file(conn, local_path, remote_path, mode)
            return ToolResult(ok=True, data=f"Uploaded {local_path} to {remote_path}")
        except SSHFileError as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_download(self, args: dict[str, Any]) -> ToolResult:
        """Handle file download."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        remote_path = args.get("remote_path", "")
        local_path = args.get("local_path", "")

        if not host or not remote_path or not local_path:
            return ToolResult(ok=False, error="host, remote_path, and local_path are required")

        try:
            conn = await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=args.get("password"),
                key_path=args.get("key_path"),
                key_passphrase=args.get("key_passphrase"),
            )
            await _ssh_pool.download_file(conn, remote_path, local_path)
            return ToolResult(ok=True, data=f"Downloaded {remote_path} to {local_path}")
        except SSHFileError as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_list(self, args: dict[str, Any]) -> ToolResult:
        """Handle directory listing."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        remote_path = args.get("remote_path", "/")

        if not host:
            return ToolResult(ok=False, error="host is required")

        try:
            conn = await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=args.get("password"),
                key_path=args.get("key_path"),
                key_passphrase=args.get("key_passphrase"),
            )
            entries = await _ssh_pool.list_directory(conn, remote_path)
            return ToolResult(ok=True, data={"entries": entries, "path": remote_path})
        except SSHFileError as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_read_file(self, args: dict[str, Any]) -> ToolResult:
        """Handle remote file reading."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        remote_path = args.get("remote_path", "")

        if not host or not remote_path:
            return ToolResult(ok=False, error="host and remote_path are required")

        try:
            conn = await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=args.get("password"),
                key_path=args.get("key_path"),
                key_passphrase=args.get("key_passphrase"),
            )
            content = await _ssh_pool.read_file(conn, remote_path)
            return ToolResult(ok=True, data=content)
        except SSHFileError as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_write_file(self, args: dict[str, Any]) -> ToolResult:
        """Handle remote file writing."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")
        remote_path = args.get("remote_path", "")
        content = args.get("content", "")
        mode = args.get("mode")

        if not host or not remote_path:
            return ToolResult(ok=False, error="host and remote_path are required")

        try:
            conn = await _ssh_pool.connect(
                host=host,
                port=port,
                username=username,
                password=args.get("password"),
                key_path=args.get("key_path"),
                key_passphrase=args.get("key_passphrase"),
            )
            await _ssh_pool.write_file(conn, remote_path, content, mode)
            return ToolResult(ok=True, data=f"Wrote {len(content)} bytes to {remote_path}")
        except SSHFileError as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_disconnect(self, args: dict[str, Any]) -> ToolResult:
        """Handle disconnection from specific host."""
        host = args.get("host", "")
        port = args.get("port", 22)
        username = args.get("username", "root")

        if not host:
            return ToolResult(ok=False, error="host is required")

        try:
            await _ssh_pool.disconnect(host, port, username)
            return ToolResult(ok=True, data=f"Disconnected from {username}@{host}:{port}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def _handle_disconnect_all(self, args: dict[str, Any]) -> ToolResult:
        """Handle disconnection from all hosts."""
        try:
            await _ssh_pool.disconnect_all()
            return ToolResult(ok=True, data="Disconnected from all hosts")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_ssh_tools(registry: Any) -> None:
    """Register SSH tools with the registry."""
    registry.register(SSHTool())
