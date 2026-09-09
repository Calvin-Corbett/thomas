"""Playbook and configuration file parsing."""

from pathlib import Path
from typing import Any

from thomas.config_mgmt._exceptions import (
    InvalidPlaybookError,
)
from thomas.config_mgmt._types import (
    Handler,
    Playbook,
    Role,
    Task,
)


class PlaybookParser:
    """Parses playbook definitions from YAML-like format."""

    @staticmethod
    def parse_yaml(content: str) -> list[Playbook]:
        """Parse YAML playbook content.

        Args:
            content: YAML content.

        Returns:
            List[Playbook]: Parsed playbooks.

        Raises:
            InvalidPlaybookError: If playbook is invalid.
        """
        try:
            import yaml

            data = yaml.safe_load(content)
            if not isinstance(data, list):
                data = [data]

            playbooks: list[Playbook] = []
            for play_data in data:
                playbook = PlaybookParser._build_playbook(play_data)
                playbooks.append(playbook)

            return playbooks
        except ImportError:
            raise InvalidPlaybookError("PyYAML not installed")
        except Exception as e:
            raise InvalidPlaybookError(f"Failed to parse playbook: {e}")

    @staticmethod
    def _build_playbook(data: dict[str, Any]) -> Playbook:
        """Build playbook from parsed data.

        Args:
            data: Parsed YAML data.

        Returns:
            Playbook: Constructed playbook.

        Raises:
            InvalidPlaybookError: If data is invalid.
        """
        if not isinstance(data, dict):
            raise InvalidPlaybookError("Playbook must be a dictionary")

        name = data.get("name")
        hosts = data.get("hosts")

        if not name or not hosts:
            raise InvalidPlaybookError("'name' and 'hosts' are required")

        # Parse tasks
        tasks: list[Task] = []
        for task_data in data.get("tasks", []):
            task = PlaybookParser._build_task(task_data)
            tasks.append(task)

        # Parse pre_tasks
        pre_tasks: list[Task] = []
        for task_data in data.get("pre_tasks", []):
            task = PlaybookParser._build_task(task_data)
            pre_tasks.append(task)

        # Parse post_tasks
        post_tasks: list[Task] = []
        for task_data in data.get("post_tasks", []):
            task = PlaybookParser._build_task(task_data)
            post_tasks.append(task)

        # Parse handlers
        handlers: list[Handler] = []
        for handler_data in data.get("handlers", []):
            handler = PlaybookParser._build_handler(handler_data)
            handlers.append(handler)

        # Parse roles
        roles: list[Role] = []
        for role_data in data.get("roles", []):
            role = PlaybookParser._build_role(role_data)
            roles.append(role)

        playbook = Playbook(
            name=name,
            hosts=hosts,
            tasks=tasks,
            pre_tasks=pre_tasks,
            post_tasks=post_tasks,
            handlers=handlers,
            roles=roles,
            variables=data.get("vars", {}),
            vars_files=data.get("vars_files", []),
            tags=data.get("tags", []),
            max_fail_percentage=float(data.get("max_fail_percentage", 0)),
            serial=data.get("serial"),
            strategy=data.get("strategy", "linear"),
        )

        return playbook

    @staticmethod
    def _build_task(data: dict[str, Any]) -> Task:
        """Build task from parsed data.

        Args:
            data: Parsed task data.

        Returns:
            Task: Constructed task.

        Raises:
            InvalidPlaybookError: If task data is invalid.
        """
        if not isinstance(data, dict):
            raise InvalidPlaybookError("Task must be a dictionary")

        name = data.get("name")
        if not name:
            raise InvalidPlaybookError("Task 'name' is required")

        # Extract module and args
        module: str | None = None
        args: dict[str, Any] = {}

        # Common modules that take 'name' as module arg
        for key in data:
            if key not in [
                "name",
                "when",
                "with_items",
                "register",
                "notify",
                "tags",
                "ignore_errors",
                "changed_when",
                "failed_when",
                "retries",
                "delay",
                "become",
                "become_user",
            ]:
                module = key
                module_args = data[key]
                if isinstance(module_args, dict):
                    args = module_args
                elif isinstance(module_args, str):
                    args = {"name": module_args}
                break

        if not module:
            raise InvalidPlaybookError("Task must specify a module")

        task = Task(
            name=name,
            module=module,
            args=args,
            when=data.get("when"),
            with_items=data.get("with_items"),
            register=data.get("register"),
            notify=data.get("notify", []),
            tags=data.get("tags", []),
            ignore_errors=data.get("ignore_errors", False),
            changed_when=data.get("changed_when"),
            failed_when=data.get("failed_when"),
            retries=int(data.get("retries", 1)),
            delay=int(data.get("delay", 0)),
            become=data.get("become", False),
            become_user=data.get("become_user"),
        )

        return task

    @staticmethod
    def _build_handler(data: dict[str, Any]) -> Handler:
        """Build handler from parsed data.

        Args:
            data: Parsed handler data.

        Returns:
            Handler: Constructed handler.
        """
        if isinstance(data, str):
            return Handler(name=data, action="notify")

        name = data.get("name", "")
        action = data.get("action", data.get("service", ""))

        return Handler(
            name=name,
            action=action,
            tags=data.get("tags", []),
            listen=data.get("listen"),
        )

    @staticmethod
    def _build_role(data: dict[str, Any]) -> Role:
        """Build role from parsed data.

        Args:
            data: Parsed role data.

        Returns:
            Role: Constructed role.
        """
        if isinstance(data, str):
            return Role(name=data)

        name = data.get("name", "")

        return Role(
            name=name,
            variables=data.get("vars", {}),
            defaults=data.get("defaults", {}),
            tags=data.get("tags", []),
            dependencies=data.get("dependencies", []),
        )

    @staticmethod
    def parse_from_file(filepath: str) -> list[Playbook]:
        """Parse playbook from file.

        Args:
            filepath: Path to playbook file.

        Returns:
            List[Playbook]: Parsed playbooks.

        Raises:
            InvalidPlaybookError: If file cannot be read.
        """
        try:
            path = Path(filepath)
            content = path.read_text()
            return PlaybookParser.parse_yaml(content)
        except FileNotFoundError:
            raise InvalidPlaybookError(f"Playbook file not found: {filepath}")
        except Exception as e:
            raise InvalidPlaybookError(f"Failed to parse playbook file: {e}")
