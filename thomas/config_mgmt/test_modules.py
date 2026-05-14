"""Tests for built-in modules."""

import tempfile
from pathlib import Path

from thomas.config_mgmt._types import Connection, ConnectionType, Credential, Host, Task
from thomas.config_mgmt.modules import (
    CommandModule,
    FileModule,
    ModuleRegistry,
    TemplateModule,
)
from thomas.config_mgmt.playbook import ExecutionContext


class TestFileModule:
    """Tests for file module."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.module = FileModule()
        self.cred = Credential(username="root", password="secret")
        self.conn = Connection(
            type=ConnectionType.SSH,
            host="testhost",
            port=22,
            credential=self.cred,
        )
        self.host = Host(hostname="testhost", connection=self.conn)
        self.context = ExecutionContext()

    def test_file_creation(self) -> None:
        """Test file creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.txt")

            task = Task(
                name="Create file",
                module="file",
                args={"path": path, "state": "present"},
            )

            result = self.module.execute(task, self.host, self.context)
            assert result.changed
            assert Path(path).exists()

    def test_file_deletion(self) -> None:
        """Test file deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.txt")
            Path(path).touch()

            task = Task(
                name="Delete file",
                module="file",
                args={"path": path, "state": "absent"},
            )

            result = self.module.execute(task, self.host, self.context)
            assert result.changed
            assert not Path(path).exists()

    def test_directory_creation(self) -> None:
        """Test directory creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "newdir")

            task = Task(
                name="Create directory",
                module="file",
                args={"path": path, "state": "directory"},
            )

            result = self.module.execute(task, self.host, self.context)
            assert result.changed
            assert Path(path).is_dir()

    def test_file_touch(self) -> None:
        """Test file touch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.txt")

            task = Task(
                name="Touch file",
                module="file",
                args={"path": path, "state": "touch"},
            )

            result = self.module.execute(task, self.host, self.context)
            assert result.changed
            assert Path(path).exists()

    def test_file_missing_path(self) -> None:
        """Test file module with missing path."""
        task = Task(
            name="Missing path",
            module="file",
            args={"state": "present"},
        )

        result = self.module.execute(task, self.host, self.context)
        assert result.failed


class TestTemplateModule:
    """Tests for template module."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.module = TemplateModule()
        self.cred = Credential(username="root", password="secret")
        self.conn = Connection(
            type=ConnectionType.SSH,
            host="testhost",
            port=22,
            credential=self.cred,
        )
        self.host = Host(hostname="testhost", connection=self.conn)
        self.context = ExecutionContext()
        self.context.set_variable("app_name", "MyApp")
        self.context.set_variable("app_port", "8080")

    def test_template_rendering(self) -> None:
        """Test template rendering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create template source
            src = str(Path(tmpdir) / "app.conf.j2")
            Path(src).write_text("App: {{ app_name }}\nPort: {{ app_port }}\n")

            dest = str(Path(tmpdir) / "app.conf")

            task = Task(
                name="Render template",
                module="template",
                args={"src": src, "dest": dest},
            )

            result = self.module.execute(task, self.host, self.context)
            assert result.changed
            assert Path(dest).exists()

            content = Path(dest).read_text()
            assert "MyApp" in content
            assert "8080" in content

    def test_template_no_change(self) -> None:
        """Test template with no changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = str(Path(tmpdir) / "app.conf.j2")
            dest = str(Path(tmpdir) / "app.conf")

            template_content = "App: {{ app_name }}\nPort: {{ app_port }}\n"
            Path(src).write_text(template_content)
            Path(dest).write_text("App: MyApp\nPort: 8080\n")

            task = Task(
                name="Render template",
                module="template",
                args={"src": src, "dest": dest},
            )

            result = self.module.execute(task, self.host, self.context)
            assert not result.changed

    def test_template_backup(self) -> None:
        """Test template backup creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = str(Path(tmpdir) / "app.conf.j2")
            dest = str(Path(tmpdir) / "app.conf")

            Path(src).write_text("New content: {{ app_name }}\n")
            Path(dest).write_text("Old content\n")

            task = Task(
                name="Render template with backup",
                module="template",
                args={"src": src, "dest": dest, "backup": True},
            )

            self.module.execute(task, self.host, self.context)
            assert Path(dest + ".bak").exists()


class TestCommandModule:
    """Tests for command module."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.module = CommandModule()
        self.cred = Credential(username="root", password="secret")
        self.conn = Connection(
            type=ConnectionType.SSH,
            host="testhost",
            port=22,
            credential=self.cred,
        )
        self.host = Host(hostname="testhost", connection=self.conn)
        self.context = ExecutionContext()

    def test_command_success(self) -> None:
        """Test successful command execution."""
        task = Task(
            name="Echo test",
            module="command",
            args={"cmd": "echo hello"},
        )

        result = self.module.execute(task, self.host, self.context)
        assert not result.failed
        assert "hello" in result.stdout

    def test_command_failure(self) -> None:
        """Test command failure."""
        task = Task(
            name="Failing command",
            module="command",
            args={"cmd": "false"},
            ignore_errors=False,
        )

        result = self.module.execute(task, self.host, self.context)
        assert result.failed

    def test_command_ignore_errors(self) -> None:
        """Test ignore_errors flag."""
        task = Task(
            name="Failing but ignored",
            module="command",
            args={"cmd": "false"},
            ignore_errors=True,
        )

        result = self.module.execute(task, self.host, self.context)
        assert not result.failed

    def test_command_missing_cmd(self) -> None:
        """Test command module with missing cmd."""
        task = Task(
            name="No command",
            module="command",
            args={},
        )

        result = self.module.execute(task, self.host, self.context)
        assert result.failed


class TestModuleRegistry:
    """Tests for module registry."""

    def test_registry_initialization(self) -> None:
        """Test registry has built-in modules."""
        registry = ModuleRegistry()
        assert registry.get("file") is not None
        assert registry.get("template") is not None
        assert registry.get("package") is not None
        assert registry.get("command") is not None

    def test_list_modules(self) -> None:
        """Test listing available modules."""
        registry = ModuleRegistry()
        modules = registry.list_modules()
        assert len(modules) >= 4

    def test_register_custom_module(self) -> None:
        """Test registering custom module."""
        registry = ModuleRegistry()
        custom_module = CommandModule()
        registry.register("custom_module", custom_module)
        assert registry.get("custom_module") is not None
