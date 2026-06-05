"""CLI commands for chat training mode and conversation diagnostics."""

from __future__ import annotations

import json

import click


@click.group("training")
def training_group() -> None:
    """Training mode: monitor and correct Thomas's conversation behavior."""
    pass


@training_group.command("enable")
@click.option("--log-dir", default=None, help="Directory for training logs.")
@click.pass_context
def training_enable(ctx: click.Context, log_dir: str | None) -> None:
    """Enable training mode to monitor conversation quality."""
    from thomas.chat_logger import TrainingMode, chat_logger

    if log_dir is None:
        from thomas.core.config import AppConfig

        config: AppConfig = ctx.obj["config"]
        log_dir = str(config.memory.root_path / ".thomas" / "training")

    TrainingMode.enable(log_dir=log_dir)
    chat_logger.configure(log_dir=log_dir, enabled=True)
    click.echo(f"Training mode ENABLED. Logs: {log_dir}")
    click.echo("All responses will be evaluated for quality. Flagged issues will be logged.")


@training_group.command("disable")
def training_disable() -> None:
    """Disable training mode."""
    from thomas.chat_logger import TrainingMode

    TrainingMode.disable()
    click.echo("Training mode DISABLED.")


@training_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def training_status(as_json: bool) -> None:
    """Show training mode status and quality report."""
    from thomas.chat_logger import TrainingMode, chat_logger

    report = TrainingMode.get_report()
    summary = chat_logger.summary()

    if as_json:
        click.echo(json.dumps({"training": report, "logger": summary}, indent=2, default=str))
        return

    enabled_str = "ENABLED" if report["enabled"] else "DISABLED"
    click.echo(f"Training mode: {enabled_str}")
    click.echo(f"Total observations: {report.get('total_observations', 0)}")
    click.echo(f"Flagged responses: {report.get('flagged', 0)}")
    flag_rate = report.get("flag_rate", 0)
    click.echo(f"Flag rate: {flag_rate}%")

    dist = report.get("quality_distribution", {})
    if dist:
        click.echo("\nQuality distribution:")
        for quality, count in sorted(dist.items()):
            click.echo(f"  {quality}: {count}")

    issues = report.get("top_issues", [])
    if issues:
        click.echo("\nTop issues:")
        for item in issues[:5]:
            click.echo(f"  [{item['count']}x] {item['reason']}")

    corrections = report.get("corrections_recorded", 0)
    if corrections:
        click.echo(f"\nCorrections recorded: {corrections}")

    click.echo(f"\nPipeline events buffered: {summary.get('total_events', 0)}")


@training_group.command("report")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def training_report(as_json: bool) -> None:
    """Generate a detailed training report."""
    from thomas.chat_logger import TrainingMode

    report = TrainingMode.get_report()

    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
        return

    if report.get("total_observations", 0) == 0:
        click.echo("No observations yet. Enable training mode and have some conversations first.")
        return

    click.echo("=" * 60)
    click.echo("  THOMAS TRAINING REPORT")
    click.echo("=" * 60)
    click.echo(f"  Observations: {report['total_observations']}")
    click.echo(f"  Flagged:      {report['flagged']} ({report['flag_rate']}%)")
    click.echo(f"  Corrections:  {report['corrections_recorded']}")
    click.echo()

    dist = report.get("quality_distribution", {})
    if dist:
        click.echo("  Quality breakdown:")
        for quality, count in sorted(dist.items()):
            pct = round(count / max(report["total_observations"], 1) * 100, 1)
            bar = "#" * max(1, int(pct / 2))
            click.echo(f"    {quality:25s} {count:4d} ({pct:5.1f}%) {bar}")

    issues = report.get("top_issues", [])
    if issues:
        click.echo()
        click.echo("  Top issues to fix:")
        for i, item in enumerate(issues, 1):
            click.echo(f"    {i}. [{item['count']}x] {item['reason']}")

    click.echo()
    click.echo("=" * 60)


@training_group.command("reset")
@click.confirmation_option(prompt="Reset all training data?")
def training_reset() -> None:
    """Reset all training observations and corrections."""
    from thomas.chat_logger import TrainingMode

    TrainingMode.reset()
    click.echo("Training data reset.")


@training_group.command("correct")
@click.argument("user_text")
@click.argument("bad_response")
@click.argument("corrected_response")
@click.option("--reason", default="", help="Reason for correction.")
def training_correct(user_text: str, bad_response: str, corrected_response: str, reason: str) -> None:
    """Record a behavioral correction."""
    from thomas.chat_logger import TrainingMode

    TrainingMode.add_correction(user_text, bad_response, corrected_response, reason)
    click.echo("Correction recorded.")


@training_group.command("logs")
@click.option("-n", "--count", default=20, help="Number of recent events.")
@click.option("--kind", default=None, help="Filter by event kind.")
@click.option("--flags-only", is_flag=True, help="Show only flagged events.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def training_logs(count: int, kind: str | None, flags_only: bool, as_json: bool) -> None:
    """View recent chat pipeline events."""
    from thomas.chat_logger import ChatEventKind, chat_logger

    if flags_only:
        kind = ChatEventKind.TRAINING_FLAG

    events = chat_logger.get_recent_events(n=count, kind=kind)

    if as_json:
        click.echo(json.dumps([e.to_dict() for e in events], indent=2, default=str))
        return

    if not events:
        click.echo("No events found.")
        return

    for evt in events:
        ts = evt.to_dict()["iso"][11:19]  # HH:MM:SS
        kind_str = evt.kind[:16].ljust(16)
        data_preview = json.dumps(evt.data, default=str)[:100]
        click.echo(f"  [{ts}] {kind_str} {data_preview}")


def register_training_commands(cli: click.Group) -> None:
    """Register the training command group with the CLI."""
    if "training" not in cli.commands:
        cli.add_command(training_group)
