"""Thomas package metadata."""

from __future__ import annotations

__version__ = "0.15.23"


def _patch_typer_testing_for_click() -> None:
    """
    Allow ``typer.testing.CliRunner`` to invoke Click commands directly.

    A large part of Thomas still exposes Click command trees, while some tests
    use Typer's runner helper. Upstream Typer's runner expects a Typer instance
    by default, so we add a tiny compatibility shim for mixed Click/Typer
    command surfaces.
    """
    try:
        import click
        import typer.testing as typer_testing
    except Exception:
        return

    if bool(getattr(typer_testing, "_thomas_click_compat_patched", False)):
        return

    original_get_command = getattr(typer_testing, "_get_command", None)
    if not callable(original_get_command):
        return

    def _get_command_compat(app):  # type: ignore[no-untyped-def]
        if isinstance(app, click.core.Command):
            return app
        return original_get_command(app)

    typer_testing._get_command = _get_command_compat
    typer_testing._thomas_click_compat_patched = True


_patch_typer_testing_for_click()
