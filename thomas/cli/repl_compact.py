from __future__ import annotations

from prompt_toolkit.formatted_text import HTML
from rich.panel import Panel
from rich.text import Text


async def handle_compact_command(runtime) -> None:
    """Handle the /compact slash command for a REPL runtime."""
    from rich.live import Live as _Lv
    from rich.spinner import Spinner as _Sp

    from thomas.agent.context_compaction import (
        ContextCompactor,
        estimate_conversation_tokens,
    )

    conv_tokens = estimate_conversation_tokens(runtime._conversation)
    hard_cap = runtime._active_context_limit()
    pct = int((conv_tokens / max(1, hard_cap)) * 100)
    msg_count = len(runtime._conversation)

    runtime._console.print("[bold]Context Budget[/bold]")
    runtime._console.print(
        f"  Tokens: [cyan]{conv_tokens:,}[/cyan] / {hard_cap:,} "
        f"([{'red' if pct > 85 else 'yellow' if pct > 60 else 'green'}]{pct}%[/])"
    )
    runtime._console.print(f"  Messages: {msg_count}")

    user_turns = sum(1 for m in runtime._conversation if m.get("role") == "user")
    asst_turns = sum(1 for m in runtime._conversation if m.get("role") == "assistant")
    tool_msgs = sum(1 for m in runtime._conversation if m.get("role") == "tool")
    system_msgs = sum(1 for m in runtime._conversation if m.get("role") == "system")
    runtime._console.print(
        f"  Breakdown: {user_turns} user, {asst_turns} assistant, {tool_msgs} tool, {system_msgs} system"
    )

    if conv_tokens < int(hard_cap * 0.50):
        runtime._console.print("\n[dim]Context usage is low. No compaction needed yet.[/dim]")
        return

    runtime._console.print("\n[dim]Compaction will summarize older turns to free token budget.[/dim]")
    try:
        confirm = await runtime._session.prompt_async(
            HTML("<prompt>Compact now?</prompt> <ansigray>(y/n)</ansigray> > "),
        )
    except (KeyboardInterrupt, EOFError):
        return

    if str(confirm or "").strip().lower() not in ("y", "yes"):
        runtime._console.print("[dim]Compaction cancelled.[/dim]")
        return

    compactor = ContextCompactor(
        llm=runtime._get_llm(),
        max_summary_tokens=400,
        segment_size=8,
    )
    spinner = _Lv(
        _Sp("dots", text=Text(" compacting context...", style="dim")),
        console=runtime._console,
        transient=True,
    )
    spinner.start()

    try:
        result = await compactor.compact(
            runtime._conversation,
            target_budget=int(hard_cap * 0.55),
            preserve_recent=6,
            use_llm=True,
        )
    except Exception as exc:
        spinner.stop()
        runtime._console.print(f"[red]Compaction failed: {exc}[/red]")
        return

    spinner.stop()
    runtime._console.print("\n[bold]Compaction Complete[/bold]")
    runtime._console.print(
        f"  Tokens: {result.original_tokens:,} -> "
        f"[green]{result.compacted_tokens:,}[/green] "
        f"(saved {result.tokens_saved:,})"
    )
    runtime._console.print(f"  Messages: {result.original_message_count} -> {result.compacted_message_count}")
    if result.segments_summarized > 0:
        runtime._console.print(f"  Segments summarized: {result.segments_summarized}")
    runtime._console.print(f"  Time: {result.elapsed_ms:.0f}ms")

    if result.summary_text:
        summary_preview = result.summary_text
        if len(summary_preview) > 500:
            summary_preview = summary_preview[:500] + "..."
        runtime._console.print(
            Panel(
                summary_preview,
                title="Summary of compacted context",
                border_style="dim",
                expand=True,
            )
        )
