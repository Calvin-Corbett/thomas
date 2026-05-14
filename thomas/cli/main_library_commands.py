"""Library command registration for the top-level Thomas CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]

from thomas.core.config import AppConfig

BuildLibraryFn = Callable[[AppConfig], Any]
BuildMemoryFn = Callable[[AppConfig], Any]


def register_library_commands(
    cli: Any,
    *,
    build_library: BuildLibraryFn,
    build_memory: BuildMemoryFn,
    logger: Any,
) -> None:
    """Attach `library` command group to the top-level CLI."""

    @cli.group()
    @click.pass_context
    def library(ctx: click.Context) -> None:
        """Manage the durable research library (separate from chat memory)."""

    @library.command("where")
    @click.pass_context
    def library_where(ctx: click.Context) -> None:
        """Show library root path and key files."""
        config: AppConfig = ctx.obj["config"]
        store = build_library(config)
        if store is None:
            click.echo("Library unavailable.", err=True)
            sys.exit(1)
        click.echo(f"Library root: {store.root}")
        click.echo(f"Catalog: {store.index_path}")
        click.echo(f"Index: {store.toc_path}")

    @library.command("list")
    @click.option("--category", "category", default="", help="Filter by category.")
    @click.option("--query", "query", default="", help="Search query.")
    @click.option("--limit", "limit", type=int, default=25, show_default=True)
    @click.pass_context
    def library_list(ctx: click.Context, category: str, query: str, limit: int) -> None:
        """List library entries."""
        config: AppConfig = ctx.obj["config"]
        store = build_library(config)
        if store is None:
            click.echo("Library unavailable.", err=True)
            sys.exit(1)
        rows = store.list_entries(
            category=(category.strip() or None),
            query=(query.strip() or None),
            limit=max(1, int(limit)),
        )
        if not rows:
            click.echo("No library entries found.")
            return
        click.echo(f"Found {len(rows)} entries:")
        for row in rows:
            rid = str(row.get("id", ""))
            title = str(row.get("title", rid))
            cat = str(row.get("category", "uncategorized"))
            src = str(row.get("source", ""))
            click.echo(f"- {rid} [{cat}] {title}")
            if src:
                click.echo(f"  source: {src}")

    @library.command("show")
    @click.argument("entry_id")
    @click.pass_context
    def library_show(ctx: click.Context, entry_id: str) -> None:
        """Show one library entry (metadata + content)."""
        config: AppConfig = ctx.obj["config"]
        store = build_library(config)
        if store is None:
            click.echo("Library unavailable.", err=True)
            sys.exit(1)
        row = store.get_entry(entry_id)
        if row is None:
            click.echo(f"Entry not found: {entry_id}", err=True)
            sys.exit(2)
        click.echo(f"id: {row.get('id')}")
        click.echo(f"title: {row.get('title')}")
        click.echo(f"category: {row.get('category')}")
        click.echo(f"source: {row.get('source')}")
        tags = row.get("tags") or []
        if isinstance(tags, list) and tags:
            click.echo("tags: " + ", ".join(str(t) for t in tags))
        click.echo("")
        click.echo(str(row.get("content", "")))

    @library.command("add")
    @click.option("--title", "title", required=True, help="Entry title.")
    @click.option("--category", "category", default="research-notes", show_default=True)
    @click.option("--summary", "summary", default="", help="Short summary.")
    @click.option("--source", "source", default="", help="Source URL or citation note.")
    @click.option("--tags", "tags", default="", help="Comma-separated tags.")
    @click.option("--content", "content", default="", help="Inline content text.")
    @click.option("--content-file", "content_file", type=click.Path(exists=True, dir_okay=False), default="")
    @click.option("--query", "query", default="", help="Original research query.")
    @click.pass_context
    def library_add(
        ctx: click.Context,
        title: str,
        category: str,
        summary: str,
        source: str,
        tags: str,
        content: str,
        content_file: str,
        query: str,
    ) -> None:
        """Add a new library entry."""
        config: AppConfig = ctx.obj["config"]
        store = build_library(config)
        if store is None:
            click.echo("Library unavailable.", err=True)
            sys.exit(1)

        payload = str(content or "").strip()
        if content_file:
            payload = Path(content_file).read_text(encoding="utf-8", errors="replace").strip()
        if not payload:
            click.echo("Missing content. Use --content or --content-file.", err=True)
            sys.exit(2)

        tag_list = [x.strip() for x in str(tags or "").split(",") if x.strip()]
        row = store.add_entry(
            title=title,
            category=category,
            content=payload,
            summary=summary,
            source=source,
            tags=tag_list,
            query=query,
            auto_captured=False,
            dedupe=True,
        )
        click.echo(f"Saved: {row.get('id')} -> {row.get('path')}")

    @library.command("reindex")
    @click.pass_context
    def library_reindex(ctx: click.Context) -> None:
        """Rebuild table of contents from catalog."""
        config: AppConfig = ctx.obj["config"]
        store = build_library(config)
        if store is None:
            click.echo("Library unavailable.", err=True)
            sys.exit(1)
        store.rebuild_toc()
        click.echo(f"Rebuilt: {store.toc_path}")

    @library.command("curate")
    @click.option("--force", is_flag=True, help="Ignore curator interval cooldown.")
    @click.pass_context
    def library_curate(ctx: click.Context, force: bool) -> None:
        """Run one memory curator pass (promote chat/library knowledge into durable memory)."""
        config: AppConfig = ctx.obj["config"]
        memory = build_memory(config)
        if memory is None:
            click.echo("Memory engine unavailable.", err=True)
            sys.exit(1)
        try:
            runner = getattr(memory, "run_curator", None)
            if not callable(runner):
                click.echo("Curator unavailable for current memory backend.", err=True)
                sys.exit(2)
            result = runner(force=bool(force))
            if not isinstance(result, dict):
                result = {"ran": False, "reason": "invalid_result"}
            click.echo("Curator run:")
            for key in (
                "ran",
                "reason",
                "episodes_scanned",
                "library_entries_scanned",
                "hints_promoted",
                "facts_promoted",
                "duplicates_skipped",
                "last_episode_id",
                "last_library_ts_utc",
            ):
                if key in result:
                    click.echo(f"- {key}: {result.get(key)}")
        finally:
            try:
                memory.close()
            except (OSError, RuntimeError, AttributeError) as exc:
                logger.debug("Failed to close memory engine after library curate: %s", exc)
