"""
Example usage and integration examples for configuration management module.

Demonstrates how to use the config_mgmt module for common tasks.
"""

from thomas.config_mgmt.core import (
    ConfigManager,
    Inventory,
    Resource,
    ResourceType,
    Task,
)
from thomas.config_mgmt.playbook import ExecutionStrategy, Playbook
from thomas.config_mgmt.reporting import Reporter
from thomas.config_mgmt.state_tracker import ChangeType, StateChange, StateTracker
from thomas.config_mgmt.templates import TemplateEngine
from thomas.config_mgmt.validation import Validator


def example_basic_resource_management() -> None:
    """Example: Basic resource management."""
    # Create a configuration manager
    manager = ConfigManager.create(dry_run=False, strict=False)

    # Create and manage resources
    resource = Resource(
        id="web-server-1",
        resource_type=ResourceType.SERVICE,
        name="nginx",
    )

    resource.add_attribute(
        name="status",
        value="stopped",
        expected="running",
    )

    manager.add_resource(resource)

    # Check compliance
    compliance = manager.check_compliance()
    print(f"Compliant: {compliance['compliant_resources']}")
    print(f"Drift found: {compliance['non_compliant_resources']}")


def example_playbook_execution() -> None:
    """Example: Execute a playbook."""
    # Create inventory
    inventory = Inventory()
    inventory.add_host("web1", role="webserver", env="prod")
    inventory.add_host("web2", role="webserver", env="prod")
    inventory.add_group("webservers", ["web1", "web2"])

    # Create playbook
    playbook = Playbook.create(
        name="Deploy Web Servers",
        description="Configure web server environment",
    )
    playbook.set_target_hosts(["web1", "web2"])
    playbook.strategy = ExecutionStrategy.LINEAR
    playbook.add_variable("app_version", "2.0.0")
    playbook.add_variable("app_port", 8080)

    # Add tasks to playbook
    task1 = Task.create(
        name="Install packages",
        module="package",
        resource_type=ResourceType.PACKAGE,
        state="present",
    )
    task1.tags = ["install"]

    task2 = Task.create(
        name="Start service",
        module="service",
        resource_type=ResourceType.SERVICE,
        state="started",
        enabled=True,
    )
    task2.tags = ["start"]
    task2.depends_on = [task1.id]

    playbook.add_task(task1)
    playbook.add_task(task2)

    # Execute playbook
    manager = ConfigManager.create()
    execution = manager.execute_playbook(playbook, inventory)

    # Check results
    print(f"Execution ID: {execution.execution_id}")
    print(f"Success Rate: {execution.success_rate:.1f}%")
    print(f"Total Tasks: {execution.total_tasks}")
    print(f"Successful: {execution.successful_tasks}")


def example_template_engine() -> None:
    """Example: Using template engine for configuration."""
    engine = TemplateEngine()

    # Set variables
    engine.set_variable("app_name", "MyApp")
    engine.set_variable("version", "1.0.0")
    engine.set_variable("servers", ["web1", "web2", "web3"])
    engine.set_variable("debug_enabled", True)

    # Render templates
    template1 = "Application: {{ app_name }} v{{ version }}"
    result1 = engine.render(template1)
    print(f"Result 1: {result1}")

    # Template with filters
    template2 = "{{ app_name | upper }}"
    result2 = engine.render(template2)
    print(f"Result 2: {result2}")

    # Template with conditionals
    template3 = """
    {% if debug_enabled %}
    Debug mode is enabled
    {% endif %}
    """
    result3 = engine.render(template3)
    print(f"Result 3: {result3}")

    # Template with loops
    template4 = """
    Servers:
    {% for server in servers %}
    - {{ server }}
    {% endfor %}
    """
    result4 = engine.render(template4)
    print(f"Result 4: {result4}")


def example_validation() -> None:
    """Example: Configuration validation."""
    validator = Validator()

    # Define schema
    config_schema = {
        "app_name": {
            "type": str,
            "required": True,
            "pattern": r"^[a-zA-Z0-9_-]+$",
        },
        "port": {
            "type": int,
            "required": True,
            "min_value": 1024,
            "max_value": 65535,
        },
        "workers": {
            "type": int,
            "required": False,
            "min_value": 1,
            "max_value": 16,
        },
    }

    # Valid config
    valid_config = {
        "app_name": "my-app",
        "port": 8080,
        "workers": 4,
    }

    result = validator.validate_schema(valid_config, config_schema)
    print(f"Valid config: {result.is_valid}")

    # Invalid config
    invalid_config = {
        "app_name": "my app",  # Spaces not allowed
        "port": 9999999,  # Out of range
    }

    result = validator.validate_schema(invalid_config, config_schema)
    print(f"Invalid config: {result.is_valid}")
    print(f"Errors: {len(result.errors)}")


def example_state_tracking() -> None:
    """Example: Track configuration state changes."""
    tracker = StateTracker()

    # Create a resource
    resource = Resource(
        id="app-config-1",
        resource_type=ResourceType.FILE,
        name="app.conf",
    )

    # Track a change
    change = StateChange(
        change_id="change-001",
        resource_id=resource.id,
        resource_name=resource.name,
        change_type=ChangeType.CREATED,
        after_state={"path": "/etc/app.conf", "size": 1024},
        initiated_by="admin",
    )

    tracker.track_change(change)

    # Get change history
    history = tracker.get_history(resource.id)
    if history:
        print(f"Total changes: {history.get_change_count()}")
        print(f"Change summary: {history.get_change_types_summary()}")

    # Get timeline
    timeline = tracker.get_state_timeline(resource.id)
    for entry in timeline:
        print(f"  {entry['timestamp']}: {entry['change_type']}")


def example_reporting() -> None:
    """Example: Generate reports."""
    reporter = Reporter()

    # Generate execution report
    execution_data = {
        "execution_id": "exec-001",
        "playbook_name": "Deploy Web Servers",
        "total_tasks": 10,
        "successful_tasks": 9,
        "failed_tasks": 1,
        "skipped_tasks": 0,
        "duration_ms": 5432.1,
        "success_rate": 90.0,
        "host_count": 3,
        "changed_resources": 7,
        "failed_resources": 1,
    }

    report = reporter.generate_execution_report(execution_data)
    print("\n" + report.to_human_readable())

    # Generate compliance report
    compliance_data = {
        "report_id": "comp-001",
        "total_resources": 50,
        "compliant_resources": 45,
        "non_compliant_resources": 5,
        "drift_summary": [
            {
                "resource_type": "service",
                "resource_id": "svc-001",
                "drift": [{"name": "status", "current": "stopped", "expected": "running"}],
            },
        ],
    }

    comp_report = reporter.generate_compliance_report(compliance_data)
    print("\n" + comp_report.to_human_readable())


def example_inventory_management() -> None:
    """Example: Manage inventory."""
    inventory = Inventory()

    # Add hosts with attributes
    inventory.add_host("web-01", ip="192.168.1.10", role="webserver", env="prod")
    inventory.add_host("web-02", ip="192.168.1.11", role="webserver", env="prod")
    inventory.add_host("db-01", ip="192.168.1.20", role="database", env="prod")

    # Create groups
    inventory.add_group("webservers", ["web-01", "web-02"])
    inventory.add_group("databases", ["db-01"])
    inventory.add_group("production", ["web-01", "web-02", "db-01"])

    # Set inventory-wide variables
    inventory.variables["domain"] = "example.com"
    inventory.variables["region"] = "us-west-2"

    # Query inventory
    webserver_hosts = inventory.get_hosts_in_group("webservers")
    print(f"Webservers: {webserver_hosts}")

    # Filter hosts
    prod_servers = inventory.filter_hosts(env="prod")
    print(f"Production servers: {prod_servers}")

    # Get host variables
    host_vars = inventory.get_host_variables("web-01")
    print(f"Web-01 variables: {host_vars}")


if __name__ == "__main__":
    print("=== Basic Resource Management ===")
    example_basic_resource_management()

    print("\n=== Playbook Execution ===")
    example_playbook_execution()

    print("\n=== Template Engine ===")
    example_template_engine()

    print("\n=== Validation ===")
    example_validation()

    print("\n=== State Tracking ===")
    example_state_tracking()

    print("\n=== Reporting ===")
    example_reporting()

    print("\n=== Inventory Management ===")
    example_inventory_management()
