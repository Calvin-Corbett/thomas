from __future__ import annotations

"""P097 CLI wiring: plugin package bootstrap.

This module is designed to be imported by the existing plugins CLI group.
It exposes a `register(app)` hook and provides JSON output for automation.
"""

import json
from pathlib import Path
from typing import Any

import typer

from thomas.plugins.p097_plugin_package_bootstrap import (
    PluginBootstrapError,
    PluginBootstrapRequest,
    bootstrap_plugin_package,
)


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def register(app: typer.Typer) -> None:
    @app.command("bootstrap")
    def bootstrap(  # noqa: WPS430 - Typer command function
        plugin_name: str = typer.Argument(..., help="Python package name for the plugin."),
        destination: Path = typer.Option(Path("."), "--dest", help="Directory to create the plugin package within."),
        description: str = typer.Option("Thomas plugin package", "--description", help="Plugin package description."),
        author: str = typer.Option("", "--author", help="Author string used in generated metadata."),
        make_skill: bool = typer.Option(
            True, "--make-skill/--skip-skill", help="Create matching .codex SKILL.md file."
        ),
        make_manifest: bool = typer.Option(
            True, "--make-manifest/--skip-manifest", help="Create plugin.json/thomas_plugin.json/manifest.json files."
        ),
        version: str = typer.Option("0.1.0", "--version", help="Plugin version written to generated manifests."),
        install: bool = typer.Option(False, "--install", help="Install the generated plugin after bootstrapping."),
        install_root: Path | None = typer.Option(
            None,
            "--install-root",
            help="Directory where the plugin should be installed (defaults to THOMAS_HOME/plugins).",
        ),
        install_overwrite: bool = typer.Option(
            False, "--install-overwrite", help="Overwrite existing installed plugin during install."
        ),
        skill_root: Path | None = typer.Option(
            None,
            "--skill-root",
            help="Directory where the generated SKILL.md should be written.",
        ),
        skill_name: str = typer.Option(
            "", "--skill-name", help="Skill directory name (defaults to normalized plugin name)."
        ),
        skill_intent: list[str] | None = typer.Option(
            None,
            "--skill-intent",
            help="Repeatable intent declaration for generated SKILL.md.",
        ),
        skill_tool: list[str] | None = typer.Option(
            None,
            "--skill-tool",
            help="Repeatable tool declaration for generated SKILL.md.",
        ),
        skill_example: list[str] | None = typer.Option(
            None,
            "--skill-example",
            help="Repeatable usage example for generated SKILL.md.",
        ),
        assistant_instructions: str = typer.Option(
            "", "--assistant-instructions", help="Tailored instructions for the generated assistant plugin."
        ),
        conversation_starter: list[str] | None = typer.Option(
            None, "--conversation-starter", help="Repeatable starter shown for the generated assistant."
        ),
        knowledge_file: list[Path] | None = typer.Option(
            None, "--knowledge-file", help="Repeatable local knowledge file copied into the plugin package."
        ),
        allow_tool: list[str] | None = typer.Option(
            None, "--allow-tool", help="Repeatable Thomas tool permission granted to this assistant."
        ),
        allow_app: list[str] | None = typer.Option(
            None, "--allow-app", help="Repeatable connected-app permission granted to this assistant."
        ),
        allow_api: list[str] | None = typer.Option(
            None, "--allow-api", help="Repeatable external API permission granted to this assistant."
        ),
        share: bool = typer.Option(False, "--share-bundle", help="Create a portable .thomas-plugin.zip bundle."),
        share_bundle_path: Path | None = typer.Option(
            None, "--share-bundle-path", help="Optional output path for the portable plugin bundle."
        ),
        validate: bool = typer.Option(
            True, "--validate/--skip-validate", help="Validate generated artifacts before returning."
        ),
        overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files if the package exists."),
        json_output: bool = typer.Option(False, "--json", help="Machine readable output."),
    ) -> None:
        try:
            result = bootstrap_plugin_package(
                PluginBootstrapRequest(
                    plugin_name=plugin_name,
                    destination_dir=destination,
                    description=description,
                    author=author,
                    create_skill=make_skill,
                    skill_root=skill_root,
                    skill_name=skill_name,
                    skill_intents=skill_intent or (),
                    skill_tools=skill_tool or (),
                    skill_examples=skill_example or (),
                    assistant_instructions=assistant_instructions,
                    conversation_starters=conversation_starter or (),
                    knowledge_files=knowledge_file or (),
                    allowed_tools=allow_tool or (),
                    allowed_apps=allow_app or (),
                    allowed_apis=allow_api or (),
                    create_manifest=make_manifest,
                    create_share_bundle=share,
                    share_bundle_path=share_bundle_path,
                    plugin_version=version,
                    validate=validate,
                    install_after_bootstrap=install,
                    install_root=install_root,
                    install_overwrite=install_overwrite,
                    overwrite=overwrite,
                )
            )
        except PluginBootstrapError as e:
            if json_output:
                _emit_json({"ok": False, "error": e.to_dict()})
            else:
                typer.echo(f"ERROR[{e.code}]: {e.message}", err=True)
            raise typer.Exit(code=2) from e

        if json_output:
            _emit_json({"ok": True, "result": result.to_dict()})
        else:
            typer.echo(f"Bootstrapped plugin package at: {result.package_dir}")
            typer.echo(f"Validation: {'OK' if result.validation_ok else 'FAILED'}")
            if result.validation_errors:
                for item in result.validation_errors:
                    typer.echo(f"Validation issue: {item}", err=True)
            if result.skill_file:
                typer.echo(f"Bootstrapped matching skill at: {result.skill_file}")
            if result.manifest_file:
                typer.echo(f"Bootstrapped plugin manifest at: {result.manifest_file}")
            if result.installed_path:
                typer.echo(f"Installed generated plugin at: {result.installed_path}")
            if result.share_bundle_file:
                typer.echo(f"Created share bundle at: {result.share_bundle_file}")
