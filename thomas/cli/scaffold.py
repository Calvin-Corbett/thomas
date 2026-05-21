"""thomas scaffold — generate correctly-structured files from templates."""

from __future__ import annotations

import pathlib
import textwrap

import click

from thomas._architecture import MODULES

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
THOMAS_ROOT = REPO_ROOT / "thomas"


def _validate_name(name: str) -> None:
    """Ensure name is a valid Python identifier."""
    if not name.isidentifier():
        click.echo(f"Error: '{name}' is not a valid Python identifier.")
        raise SystemExit(1)


@click.group("scaffold")
def scaffold_group() -> None:
    """Generate Thomas project scaffolding."""


@scaffold_group.command("route")
@click.argument("name")
def scaffold_route(name: str) -> None:
    """Scaffold a new aiohttp route handler + test."""
    _validate_name(name)
    route_file = THOMAS_ROOT / "server" / "routes" / f"{name}_aiohttp.py"
    test_file = REPO_ROOT / "tests" / f"test_{name}_routes.py"

    if route_file.exists():
        click.echo(f"Already exists: {route_file.relative_to(REPO_ROOT)}")
        raise SystemExit(1)

    route_file.write_text(
        textwrap.dedent(f'''\
        """Route handler for {name}."""

        from __future__ import annotations

        from aiohttp import web


        def setup_routes(app: web.Application) -> None:
            """Register {name} routes on the app."""
            app.router.add_get("/api/{name}", handle_get_{name})


        async def handle_get_{name}(request: web.Request) -> web.Response:
            """GET /api/{name}"""
            return web.json_response({{"ok": True, "module": "{name}"}})
    '''),
        encoding="utf-8",
    )

    test_file.write_text(
        textwrap.dedent(f'''\
        """Tests for {name} routes."""

        from __future__ import annotations


        def test_{name}_route_exists() -> None:
            from thomas.server.routes.{name}_aiohttp import setup_routes
            assert callable(setup_routes)
    '''),
        encoding="utf-8",
    )

    click.echo(f"Created: {route_file.relative_to(REPO_ROOT)}")
    click.echo(f"Created: {test_file.relative_to(REPO_ROOT)}")
    click.echo("Run: python -m pytest tests/test_architecture.py -x --tb=short -q")


@scaffold_group.command("module")
@click.argument("name")
@click.option("--tier", default="ext", type=click.Choice(["core", "ext", "infra", "support"]))
@click.option("--depends", default="core", help="Comma-separated dependency list")
def scaffold_module(name: str, tier: str, depends: str) -> None:
    """Scaffold a new Thomas module directory + init + test + architecture entry."""
    _validate_name(name)

    if name in MODULES:
        click.echo(f"Error: '{name}' already exists in _architecture.py MODULES.")
        raise SystemExit(1)

    mod_dir = THOMAS_ROOT / name
    if mod_dir.exists():
        click.echo(f"Already exists: thomas/{name}/")
        raise SystemExit(1)

    deps = [d.strip() for d in depends.split(",") if d.strip()]
    mod_dir.mkdir(parents=True)

    init_file = mod_dir / "__init__.py"
    init_file.write_text(
        textwrap.dedent(f'''\
        """{name} module."""

        from __future__ import annotations
    '''),
        encoding="utf-8",
    )

    test_file = REPO_ROOT / "tests" / f"test_{name}.py"
    test_file.write_text(
        textwrap.dedent(f'''\
        """Tests for {name} module."""

        from __future__ import annotations


        def test_{name}_importable() -> None:
            import thomas.{name}
            assert thomas.{name} is not None
    '''),
        encoding="utf-8",
    )

    # Update _architecture.py — append to MODULES
    arch_file = THOMAS_ROOT / "_architecture.py"
    arch_content = arch_file.read_text(encoding="utf-8")
    entry = (
        f'    "{name}": {{"tier": "{tier}", "depends_on": {deps},\n'
        f'                      "health": "green",\n'
        f'                      "description": "{name} module"}},\n'
    )
    # Insert before the closing brace of MODULES
    arch_content = arch_content.replace("\n}\n\n# ---", f"\n{entry}}}\n\n# ---", 1)
    arch_file.write_text(arch_content, encoding="utf-8")

    click.echo(f"Created: thomas/{name}/__init__.py")
    click.echo(f"Created: tests/test_{name}.py")
    click.echo(f"Updated: thomas/_architecture.py (added {name} to MODULES)")
    click.echo("Run: python -m pytest tests/test_architecture.py -x --tb=short -q")


@scaffold_group.command("command")
@click.argument("name")
def scaffold_command(name: str) -> None:
    """Scaffold a new CLI command file."""
    _validate_name(name)
    cmd_file = THOMAS_ROOT / "cli" / f"{name}.py"
    if cmd_file.exists():
        click.echo(f"Already exists: {cmd_file.relative_to(REPO_ROOT)}")
        raise SystemExit(1)

    cmd_file.write_text(
        textwrap.dedent(f'''\
        """thomas {name} — CLI command."""

        from __future__ import annotations

        import click


        @click.command("{name}")
        def {name}_command() -> None:
            """{name.replace("_", " ").title()} command."""
            click.echo("{name}: not yet implemented")
    '''),
        encoding="utf-8",
    )

    click.echo(f"Created: {cmd_file.relative_to(REPO_ROOT)}")
    click.echo(f"Wire it: cli.add_command({name}_command) in thomas/cli/main.py")
