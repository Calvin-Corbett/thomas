"""thomas generate-agent-docs — create per-directory AGENTS.md + Mermaid graph."""

from __future__ import annotations

import pathlib

import click

from thomas._architecture import MODULES, get_all_by_tier

THOMAS_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = THOMAS_ROOT.parent


@click.command("generate-agent-docs")
@click.option("--dry-run", is_flag=True, help="Print what would be generated without writing.")
def generate_agent_docs_command(dry_run: bool) -> None:
    """Generate per-directory AGENTS.md files and architecture graph."""
    generated = 0

    for name, mod in sorted(MODULES.items()):
        mod_dir = THOMAS_ROOT / name
        if not mod_dir.is_dir():
            continue

        tier = mod["tier"]
        deps = ", ".join(mod["depends_on"])
        desc = mod.get("description", "")
        debt = mod.get("debt", "")
        health = mod.get("health", "green")

        lines = [
            f"# thomas/{name}",
            "",
            f"**{desc}** | tier: {tier} | health: {health}",
            f"Allowed imports: {deps}",
        ]
        if debt:
            lines.append(f"Known debt: {debt}")

        if tier == "ext":
            lines.append("Rule: extensions cannot import other extensions.")

        content = "\n".join(lines) + "\n"
        target = mod_dir / "AGENTS.md"

        if dry_run:
            click.echo(f"  Would write: {target.relative_to(REPO_ROOT)}")
        else:
            target.write_text(content, encoding="utf-8")
            generated += 1

    # Generate Mermaid dependency graph
    graph_lines = ["# Architecture Dependency Graph", "", "```mermaid", "graph TD"]

    for name, mod in sorted(MODULES.items()):
        for dep in mod["depends_on"]:
            if dep in MODULES:
                graph_lines.append(f"    {name} --> {dep}")

    graph_lines.extend([
        "",
        "    classDef core fill:#4a9eff,color:#fff",
        "    classDef ext fill:#50c878,color:#fff",
        "    classDef infra fill:#ff9f43,color:#fff",
        "    classDef support fill:#a29bfe,color:#fff",
    ])

    for tier_name in ["core", "ext", "infra", "support"]:
        members = sorted(get_all_by_tier(tier_name).keys())
        if members:
            graph_lines.append(f"    class {','.join(members)} {tier_name}")

    graph_lines.append("```")
    graph_content = "\n".join(graph_lines) + "\n"
    graph_path = REPO_ROOT / "docs" / "ARCHITECTURE_GRAPH.md"

    if dry_run:
        click.echo(f"  Would write: {graph_path.relative_to(REPO_ROOT)}")
    else:
        graph_path.write_text(graph_content, encoding="utf-8")
        generated += 1

    if dry_run:
        click.echo("Dry run complete.")
    else:
        click.echo(f"Generated {generated} files.")
