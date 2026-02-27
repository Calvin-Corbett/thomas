"""Built-in modules for task execution."""

import os
import shutil
import subprocess
from pathlib import Path

from thomas.config_mgmt._exceptions import ModuleError
from thomas.config_mgmt._types import ExecutionResult, Host, Task
from thomas.config_mgmt.playbook import ExecutionContext


class BaseModule:
    """Base class for all modules."""

    def __init__(self, name: str, description: str) -> None:
        """Initialize module.

        Args:
            name: Module name.
            description: Module description.
        """
        self.name = name
        self.description = description
        self.supports_check_mode = False

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute module on host.

        Args:
            task: Task containing module arguments.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Module execution result.
        """
        raise NotImplementedError


class FileModule(BaseModule):
    """File operations module (create, delete, modify permissions)."""

    def __init__(self) -> None:
        """Initialize file module."""
        super().__init__(
            "file",
            "Manage files and file properties",
        )
        self.supports_check_mode = True

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute file module.

        Args:
            task: Task with file arguments.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Execution result.
        """
        result = ExecutionResult(
            task_name=task.name,
            host=host.hostname,
            status="ok",
            module="file",
        )

        try:
            args = task.args
            path = args.get("path")
            state = args.get("state", "present")

            if not path:
                raise ModuleError("'path' is required")

            # Convert to absolute path
            target_path = Path(path)

            if state == "present":
                mode = args.get("mode")
                owner = args.get("owner")
                group = args.get("group")

                if not target_path.exists():
                    # Create parent directories
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.touch()
                    result.changed = True
                    result.return_data = {"path": str(target_path), "state": "created"}
                else:
                    result.return_data = {
                        "path": str(target_path),
                        "state": "present",
                    }

                # Set mode
                if mode:
                    try:
                        mode_int = int(mode, 8)
                        current_mode = target_path.stat().st_mode & 0o777
                        if current_mode != mode_int:
                            target_path.chmod(mode_int)
                            result.changed = True
                    except (ValueError, OSError) as e:
                        raise ModuleError(f"Failed to set mode: {e}")

                # Set owner and group
                if owner or group:
                    try:
                        import grp
                        import pwd

                        uid = os.getuid() if not owner else pwd.getpwnam(owner).pw_uid
                        gid = os.getgid() if not group else grp.getgrnam(group).gr_gid

                        st = target_path.stat()
                        if st.st_uid != uid or st.st_gid != gid:
                            os.chown(target_path, uid, gid)
                            result.changed = True
                    except (KeyError, OSError) as e:
                        raise ModuleError(f"Failed to set owner/group: {e}")

            elif state == "absent":
                if target_path.exists():
                    if target_path.is_dir():
                        shutil.rmtree(target_path)
                    else:
                        target_path.unlink()
                    result.changed = True
                    result.return_data = {"path": str(target_path), "state": "absent"}
                else:
                    result.return_data = {
                        "path": str(target_path),
                        "state": "absent",
                    }

            elif state == "touch":
                if target_path.exists():
                    target_path.touch()
                    result.changed = True
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.touch()
                    result.changed = True
                result.return_data = {"path": str(target_path), "state": "touched"}

            elif state == "directory":
                if not target_path.exists():
                    target_path.mkdir(parents=True, exist_ok=True)
                    result.changed = True

                if not target_path.is_dir():
                    raise ModuleError(f"Path exists but is not a directory: {path}")

                result.return_data = {"path": str(target_path), "state": "directory"}

            result.status = "ok" if not result.failed else "failed"
            return result

        except Exception as e:
            result.status = "failed"
            result.failed = True
            result.stderr = str(e)
            return result


class TemplateModule(BaseModule):
    """Template module for variable substitution."""

    def __init__(self) -> None:
        """Initialize template module."""
        super().__init__(
            "template",
            "Template a file out to a remote machine",
        )
        self.supports_check_mode = True

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute template module.

        Args:
            task: Task with template arguments.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Execution result.
        """
        result = ExecutionResult(
            task_name=task.name,
            host=host.hostname,
            status="ok",
            module="template",
        )

        try:
            args = task.args
            src = args.get("src")
            dest = args.get("dest")
            owner = args.get("owner")
            group = args.get("group")
            mode = args.get("mode")
            backup = args.get("backup", True)

            if not src or not dest:
                raise ModuleError("'src' and 'dest' are required")

            # Read source template
            src_path = Path(src)
            if not src_path.exists():
                raise ModuleError(f"Template source not found: {src}")

            template_content = src_path.read_text()

            # Render template with variables
            rendered = self._render_template(template_content, context)

            dest_path = Path(dest)
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if content changed
            changed = False
            if dest_path.exists():
                old_content = dest_path.read_text()
                if old_content != rendered:
                    changed = True
                    if backup:
                        backup_path = Path(str(dest) + ".bak")
                        backup_path.write_text(old_content)
            else:
                changed = True

            if changed:
                dest_path.write_text(rendered)
                result.changed = True

            # Set permissions
            if mode:
                try:
                    mode_int = int(mode, 8)
                    dest_path.chmod(mode_int)
                except (ValueError, OSError) as e:
                    raise ModuleError(f"Failed to set mode: {e}")

            # Set owner/group
            if owner or group:
                try:
                    import grp
                    import pwd

                    uid = os.getuid() if not owner else pwd.getpwnam(owner).pw_uid
                    gid = os.getgid() if not group else grp.getgrnam(group).gr_gid
                    os.chown(dest_path, uid, gid)
                except (KeyError, OSError) as e:
                    raise ModuleError(f"Failed to set owner/group: {e}")

            result.return_data = {"path": str(dest_path), "changed": changed}
            return result

        except Exception as e:
            result.status = "failed"
            result.failed = True
            result.stderr = str(e)
            return result

    @staticmethod
    def _render_template(template: str, context: ExecutionContext) -> str:
        """Render template with context variables.

        Args:
            template: Template string.
            context: Execution context.

        Returns:
            str: Rendered template.
        """
        result = template
        for key, value in context.variables.items():
            placeholder = "{{ " + key + " }}"
            result = result.replace(placeholder, str(value))

        # Handle item loops
        if "item" in context.variables:
            item_placeholder = "{{ item }}"
            result = result.replace(item_placeholder, str(context.variables["item"]))

        return result


class PackageModule(BaseModule):
    """Package manager module (apt, yum, dnf, etc.)."""

    def __init__(self) -> None:
        """Initialize package module."""
        super().__init__(
            "package",
            "Generic package manager",
        )
        self.supports_check_mode = False

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute package module.

        Args:
            task: Task with package arguments.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Execution result.
        """
        result = ExecutionResult(
            task_name=task.name,
            host=host.hostname,
            status="ok",
            module="package",
        )

        try:
            args = task.args
            name = args.get("name")
            state = args.get("state", "present")
            manager = args.get("manager", self._detect_package_manager())

            if not name:
                raise ModuleError("'name' is required")

            if state == "present":
                stdout, returncode = self._install_package(name, manager)
                if returncode == 0:
                    result.changed = True
                    result.stdout = stdout
                    result.return_data = {"name": name, "state": "present"}
                else:
                    raise ModuleError("Package installation failed")

            elif state == "absent":
                stdout, returncode = self._remove_package(name, manager)
                if returncode == 0:
                    result.changed = True
                    result.stdout = stdout
                    result.return_data = {"name": name, "state": "absent"}
                else:
                    raise ModuleError("Package removal failed")

            elif state == "latest":
                stdout, returncode = self._upgrade_package(name, manager)
                if returncode == 0:
                    result.changed = True
                    result.stdout = stdout
                    result.return_data = {"name": name, "state": "latest"}

            return result

        except Exception as e:
            result.status = "failed"
            result.failed = True
            result.stderr = str(e)
            return result

    @staticmethod
    def _detect_package_manager() -> str:
        """Detect system package manager.

        Returns:
            str: Package manager name.
        """
        managers = {
            "/usr/bin/apt-get": "apt",
            "/usr/bin/yum": "yum",
            "/usr/bin/dnf": "dnf",
            "/usr/bin/pacman": "pacman",
        }

        for path, name in managers.items():
            if os.path.exists(path):
                return name

        return "apt"

    @staticmethod
    def _install_package(name: str, manager: str) -> tuple[str, int]:
        """Install package using manager.

        Args:
            name: Package name.
            manager: Package manager.

        Returns:
            tuple[str, int]: (stdout, return_code).
        """
        commands = {
            "apt": ["apt-get", "install", "-y", name],
            "yum": ["yum", "install", "-y", name],
            "dnf": ["dnf", "install", "-y", name],
            "pacman": ["pacman", "-S", "--noconfirm", name],
        }

        cmd = commands.get(manager, ["apt-get", "install", "-y", name])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            return "", 1

    @staticmethod
    def _remove_package(name: str, manager: str) -> tuple[str, int]:
        """Remove package using manager.

        Args:
            name: Package name.
            manager: Package manager.

        Returns:
            tuple[str, int]: (stdout, return_code).
        """
        commands = {
            "apt": ["apt-get", "remove", "-y", name],
            "yum": ["yum", "remove", "-y", name],
            "dnf": ["dnf", "remove", "-y", name],
            "pacman": ["pacman", "-R", "--noconfirm", name],
        }

        cmd = commands.get(manager, ["apt-get", "remove", "-y", name])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            return "", 1

    @staticmethod
    def _upgrade_package(name: str, manager: str) -> tuple[str, int]:
        """Upgrade package using manager.

        Args:
            name: Package name.
            manager: Package manager.

        Returns:
            tuple[str, int]: (stdout, return_code).
        """
        commands = {
            "apt": ["apt-get", "install", "--only-upgrade", "-y", name],
            "yum": ["yum", "update", "-y", name],
            "dnf": ["dnf", "upgrade", "-y", name],
            "pacman": ["pacman", "-S", "--noconfirm", name],
        }

        cmd = commands.get(manager, ["apt-get", "install", "--only-upgrade", "-y", name])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            return "", 1


class CommandModule(BaseModule):
    """Execute arbitrary commands."""

    def __init__(self) -> None:
        """Initialize command module."""
        super().__init__(
            "command",
            "Execute shell commands",
        )
        self.supports_check_mode = False

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute command module.

        Args:
            task: Task with command.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Execution result.
        """
        result = ExecutionResult(
            task_name=task.name,
            host=host.hostname,
            status="ok",
            module="command",
        )

        try:
            args = task.args
            cmd = args.get("cmd")

            if not cmd:
                raise ModuleError("'cmd' is required")

            try:
                proc_result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                result.stdout = proc_result.stdout
                result.stderr = proc_result.stderr
                result.return_data = {
                    "cmd": cmd,
                    "rc": proc_result.returncode,
                    "stdout": proc_result.stdout,
                    "stderr": proc_result.stderr,
                }

                if proc_result.returncode != 0:
                    if not task.ignore_errors:
                        result.failed = True
                        result.status = "failed"

            except subprocess.TimeoutExpired:
                result.failed = True
                result.stderr = "Command execution timed out"
                result.status = "failed"

            return result

        except Exception as e:
            result.status = "failed"
            result.failed = True
            result.stderr = str(e)
            return result


class ModuleRegistry:
    """Registry for modules."""

    def __init__(self) -> None:
        """Initialize module registry."""
        self.modules: dict[str, BaseModule] = {}
        self._register_builtin_modules()

    def _register_builtin_modules(self) -> None:
        """Register built-in modules."""
        self.register("file", FileModule())
        self.register("template", TemplateModule())
        self.register("package", PackageModule())
        self.register("command", CommandModule())

    def register(self, name: str, module: BaseModule) -> None:
        """Register a module.

        Args:
            name: Module name.
            module: Module instance.
        """
        self.modules[name] = module

    def get(self, name: str) -> BaseModule | None:
        """Get module by name.

        Args:
            name: Module name.

        Returns:
            Optional[BaseModule]: Module or None.
        """
        return self.modules.get(name)

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute task using registered module.

        Args:
            task: Task to execute.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Execution result.

        Raises:
            ModuleError: If module not found.
        """
        module = self.get(task.module)
        if not module:
            raise ModuleError(f"Module not found: {task.module}")

        return module.execute(task, host, context)

    def list_modules(self) -> dict[str, str]:
        """List all registered modules.

        Returns:
            Dict[str, str]: Mapping of module names to descriptions.
        """
        return {name: mod.description for name, mod in self.modules.items()}
