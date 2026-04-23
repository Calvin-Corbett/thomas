"""P064 CLI: message poll vote and close.

This module is intentionally flexible about how it gets registered, because
the Thomas CLI/parity loader may use Typer or Click depending on the build.

Exports:
  - COMMAND: a Click command object
  - register(app): register into a Typer/Click app/group when possible
  - PROMPT_ID, DOMAIN: prompt metadata
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_ID = "P064"
DOMAIN = "messages"


def _json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build_click_command() -> Any:
    import click  # type: ignore

    @click.command("poll-vote-and-close")
    @click.option("--poll-id", required=True, type=str, help="Poll identifier")
    @click.option("--option", required=True, type=str, help="Option to vote for")
    @click.option("--voter-id", required=False, type=str, help="Voter identifier")
    @click.option("--reason", required=False, type=str, help="Reason (optional)")
    @click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON")
    def cmd(
        poll_id: str,
        option: str,
        voter_id: str | None,
        reason: str | None,
        json_output: bool,
    ) -> None:
        from thomas.messages.p064_message_poll_vote_and_close import PollVoteAndCloseRequest, safe_run

        payload = PollVoteAndCloseRequest(
            poll_id=poll_id,
            option=option,
            voter_id=voter_id,
            reason=reason,
        )
        result = safe_run(payload)

        if json_output:
            click.echo(_json(result))
            # Deterministic non-zero exit on failure for automation.
            if not bool(result.get("ok")):
                raise SystemExit(2)
            return

        if bool(result.get("ok")):
            click.echo(f"Voted '{option}' on poll {poll_id} and closed the poll")
            return

        err = result.get("error", {}) if isinstance(result, dict) else {}
        code = err.get("code", "error")
        msg = err.get("message", "Unknown error")
        click.echo(f"ERROR [{code}]: {msg}", err=True)
        raise SystemExit(2)

    return cmd


COMMAND = build_click_command()


def register(app: Any) -> None:
    """Register onto a Typer or Click app/group."""

    # Typer apps expose `.command(...)` decorator; Click groups expose `.add_command`.
    if hasattr(app, "command"):
        # Likely Typer. Implement using its decorator so help text etc. works.
        try:
            import typer  # type: ignore
        except ImportError:
            # If Typer isn't installed, fall back to click registration when possible.
            if hasattr(app, "add_command"):
                app.add_command(COMMAND)
            return

        @app.command("poll-vote-and-close")
        def poll_vote_and_close(
            poll_id: str = typer.Option(..., "--poll-id", help="Poll identifier"),
            option: str = typer.Option(..., "--option", help="Option to vote for"),
            voter_id: str | None = typer.Option(None, "--voter-id", help="Voter identifier"),
            reason: str | None = typer.Option(None, "--reason", help="Reason (optional)"),
            json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
        ) -> None:
            from thomas.messages.p064_message_poll_vote_and_close import PollVoteAndCloseRequest, safe_run

            payload = PollVoteAndCloseRequest(
                poll_id=poll_id,
                option=option,
                voter_id=voter_id,
                reason=reason,
            )
            result = safe_run(payload)

            if json_output:
                typer.echo(_json(result))
                if not bool(result.get("ok")):
                    raise typer.Exit(code=2)
                return

            if bool(result.get("ok")):
                typer.echo(f"Voted '{option}' on poll {poll_id} and closed the poll")
                return

            err = result.get("error", {}) if isinstance(result, dict) else {}
            code = err.get("code", "error")
            msg = err.get("message", "Unknown error")
            typer.echo(f"ERROR [{code}]: {msg}", err=True)
            raise typer.Exit(code=2)

        return

    if hasattr(app, "add_command"):
        app.add_command(COMMAND)
        return

    raise RuntimeError("Unsupported CLI app type for registration")

    # Compatibility hooks for different parity loaders.
    APP = None
    try:  # pragma: no cover
        import typer  # type: ignore

        _a = typer.Typer(add_completion=False)
        register(_a)
        APP = _a
    except ImportError:  # pragma: no cover
        APP = None

    REGISTER = register
