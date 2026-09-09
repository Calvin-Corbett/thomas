from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click


@click.group()
@click.pass_context
def webhooks(ctx: click.Context) -> None:
    """Manage webhook registrations, stats, and inbox."""
    _ = ctx


def _webhook_fail(e: Exception) -> None:
    detail = getattr(e, "detail", None)
    status = getattr(e, "status_code", None)
    if detail is None:
        detail = str(e)
    if status is not None:
        click.echo(f"Webhook error ({status}): {detail}", err=True)
    else:
        click.echo(f"Webhook error: {detail}", err=True)
    sys.exit(1)


def _load_json_file(path_text: str) -> dict[str, object]:
    path = Path(str(path_text or "").strip()).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise click.ClickException(f"event file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"invalid JSON in event file: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException("event file JSON must be an object")
    return dict(payload)


def _resolve_token(token: str, token_env: str) -> str:
    direct = str(token or "").strip()
    if direct:
        return direct
    key = str(token_env or "").strip()
    if key:
        env_value = str(os.environ.get(key) or "").strip()
        if env_value:
            return env_value
    raise click.ClickException(f"missing token (use --token or set {key or 'token env var'})")


@webhooks.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_list(as_json: bool) -> None:
    """List registered webhooks."""
    from thomas.server.routes import webhooks as wh

    try:
        items = wh._STORE.list()
        rows = [
            {
                "id": r.id,
                "has_secret": bool(r.secret),
                "created_at": r.created_at,
                "rate_limit_per_min": int(r.rate_limit_per_min),
            }
            for r in items
        ]
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps({"count": len(rows), "webhooks": rows}, ensure_ascii=False, indent=2))
        return
    click.echo(f"Webhooks: {len(rows)}")
    for row in rows:
        secret = "yes" if row["has_secret"] else "no"
        click.echo(
            f"- {row['id']} | secret={secret} | rate_limit_per_min={row['rate_limit_per_min']} | created={row['created_at']}"
        )


@webhooks.command("show")
@click.argument("webhook_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_show(webhook_id: str, as_json: bool) -> None:
    """Show one webhook registration."""
    from thomas.server.routes import webhooks as wh

    try:
        rec = wh._STORE.get(str(webhook_id).strip())
        if rec is None:
            click.echo(f"Webhook '{webhook_id}' not found.", err=True)
            sys.exit(1)
        stats = wh._STATS.get(f"generic:{rec.id}")
        payload = {
            "id": rec.id,
            "has_secret": bool(rec.secret),
            "goal_template": rec.goal_template,
            "created_at": rec.created_at,
            "rate_limit_per_min": int(rec.rate_limit_per_min),
            "stats": stats,
        }
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"id: {payload['id']}")
    click.echo(f"has_secret: {payload['has_secret']}")
    click.echo(f"rate_limit_per_min: {payload['rate_limit_per_min']}")
    click.echo(f"created_at: {payload['created_at']}")
    click.echo(f"goal_template: {payload['goal_template']}")
    click.echo(f"stats: {payload['stats']}")


@webhooks.command("register")
@click.option("--id", "webhook_id", required=True, help="Webhook id.")
@click.option("--template", "goal_template", required=True, help="Goal template text.")
@click.option("--secret", default="", help="Optional webhook secret.")
@click.option("--rate-limit", "rate_limit_per_min", default=0, type=int, help="Rate limit per minute.")
@click.option("--upsert", is_flag=True, help="Update existing webhook if it exists.")
def webhooks_register(
    webhook_id: str,
    goal_template: str,
    secret: str,
    rate_limit_per_min: int,
    upsert: bool,
) -> None:
    """Register a webhook."""
    from thomas.server.routes import webhooks as wh

    try:
        rec = wh.WebhookRecord(
            id=str(webhook_id).strip(),
            secret=str(secret).strip() or None,
            goal_template=str(goal_template),
            created_at=wh._now_iso(),
            rate_limit_per_min=int(rate_limit_per_min or wh.DEFAULT_RATE_LIMIT_PER_MIN),
        )
        if upsert:
            wh._STORE.upsert(rec)
        else:
            wh._STORE.register(rec)
    except Exception as e:
        _webhook_fail(e)
        return

    action = "upserted" if upsert else "registered"
    click.echo(f"Webhook {action}: {rec.id}")


@webhooks.command("delete")
@click.argument("webhook_id")
def webhooks_delete(webhook_id: str) -> None:
    """Delete a webhook."""
    from thomas.server.routes import webhooks as wh

    try:
        wh._STORE.delete(str(webhook_id).strip())
    except Exception as e:
        _webhook_fail(e)
        return
    click.echo(f"Webhook deleted: {webhook_id}")


@webhooks.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_stats(as_json: bool) -> None:
    """Show webhook aggregate stats."""
    from thomas.server.routes import webhooks as wh

    try:
        payload = wh._STATS.all()
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo("Webhook stats:")
    for key, val in payload.items():
        click.echo(f"- {key}: {val}")


@webhooks.command("inbox")
@click.option("--limit", default=25, show_default=True, type=int, help="Max inbox records.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_inbox(limit: int, as_json: bool) -> None:
    """Show recent webhook inbox records."""
    from thomas.server.routes import webhooks as wh

    try:
        rows = wh._INBOX.tail(int(limit))
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps({"count": len(rows), "records": rows}, ensure_ascii=False, indent=2))
        return
    click.echo(f"Inbox records: {len(rows)}")
    for row in rows:
        eid = str(row.get("event_id") or "")
        provider = str(row.get("provider") or "")
        status = str(row.get("status") or "")
        goal_id = str(row.get("goal_id") or "-")
        received_at = str(row.get("received_at") or "")
        click.echo(f"- {received_at} | {provider} | {status} | goal={goal_id} | event={eid}")


@webhooks.command("github-issue-sync")
@click.option("--event-file", default="", help="GitHub webhook payload JSON file.")
@click.option("--repo", default="", help="Repo slug like owner/repo.")
@click.option("--issue-number", default=0, type=int, help="Issue number (used when no event file is provided).")
@click.option("--token", default="", help="GitHub token (fallback to --token-env).")
@click.option("--token-env", default="GITHUB_TOKEN", show_default=True, help="GitHub token environment variable.")
@click.option("--base-url", default="https://api.github.com", show_default=True, help="GitHub API base URL.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_github_issue_sync(
    event_file: str,
    repo: str,
    issue_number: int,
    token: str,
    token_env: str,
    base_url: str,
    as_json: bool,
) -> None:
    """Normalize a GitHub issue into a task payload."""
    from thomas.integrations import github_automation as gha

    try:
        issue: dict[str, object]
        payload_source = "event_file"
        if str(event_file or "").strip():
            event = _load_json_file(event_file)
            row = event.get("issue")
            if not isinstance(row, dict):
                if "number" in event and "title" in event:
                    row = event
                else:
                    raise click.ClickException("event file does not include an issue payload")
            issue = dict(row)
            repository = event.get("repository")
            if isinstance(repository, dict) and "repository" not in issue:
                issue["repository"] = dict(repository)
        else:
            repo_value = str(repo or "").strip()
            if not repo_value or int(issue_number) <= 0:
                raise click.ClickException("provide --event-file or both --repo and --issue-number")
            payload_source = "github_api"
            token_value = _resolve_token(token, token_env)
            issue = gha.fetch_issue(
                base_url=str(base_url or "").strip() or "https://api.github.com",
                repo=repo_value,
                issue_number=int(issue_number),
                token=token_value,
            )

        task = gha.normalize_issue_to_task(issue)
        out = {"ok": True, "source": payload_source, "task": task}
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    click.echo(f"task: {str((out.get('task') or {}).get('source_id') or '')}")
    click.echo(f"title: {str((out.get('task') or {}).get('title') or '')}")
    click.echo(f"priority: {str((out.get('task') or {}).get('priority') or '')}")
    click.echo(f"status: {str((out.get('task') or {}).get('status') or '')}")


@webhooks.command("github-pr-risk-scan")
@click.option("--event-file", default="", help="GitHub webhook payload JSON file.")
@click.option("--repo", default="", help="Repo slug like owner/repo.")
@click.option("--pr-number", default=0, type=int, help="Pull request number.")
@click.option("--token", default="", help="GitHub token (fallback to --token-env).")
@click.option("--token-env", default="GITHUB_TOKEN", show_default=True, help="GitHub token environment variable.")
@click.option("--base-url", default="https://api.github.com", show_default=True, help="GitHub API base URL.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_github_pr_risk_scan(
    event_file: str,
    repo: str,
    pr_number: int,
    token: str,
    token_env: str,
    base_url: str,
    as_json: bool,
) -> None:
    """Compute deterministic risk summary for a GitHub pull request."""
    from thomas.integrations import github_automation as gha

    try:
        payload_source = "event_file"
        pr: dict[str, object]
        files: list[dict[str, object]] = []
        if str(event_file or "").strip():
            event = _load_json_file(event_file)
            row = event.get("pull_request")
            if not isinstance(row, dict):
                if "number" in event and "title" in event:
                    row = event
                else:
                    raise click.ClickException("event file does not include a pull_request payload")
            pr = dict(row)
            files_raw = event.get("files")
            if isinstance(files_raw, list):
                files = [dict(item) for item in files_raw if isinstance(item, dict)]
        else:
            repo_value = str(repo or "").strip()
            if not repo_value or int(pr_number) <= 0:
                raise click.ClickException("provide --event-file or both --repo and --pr-number")
            payload_source = "github_api"
            token_value = _resolve_token(token, token_env)
            pr = gha.fetch_pull_request(
                base_url=str(base_url or "").strip() or "https://api.github.com",
                repo=repo_value,
                pr_number=int(pr_number),
                token=token_value,
            )
            files = gha.fetch_pull_request_files(
                base_url=str(base_url or "").strip() or "https://api.github.com",
                repo=repo_value,
                pr_number=int(pr_number),
                token=token_value,
            )

        risk = gha.summarize_pr_risk(pr, files).to_dict()
        out = {
            "ok": True,
            "source": payload_source,
            "pull_request": {
                "title": str(pr.get("title") or ""),
                "number": int(pr.get("number") or 0),
                "html_url": str(pr.get("html_url") or ""),
                "draft": bool(pr.get("draft", False)),
            },
            "risk": risk,
        }
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    click.echo(f"pr: #{out['pull_request']['number']} {out['pull_request']['title']}")
    click.echo(f"risk: {out['risk']['level']} (score={out['risk']['score']})")
    click.echo(f"summary: {out['risk']['summary']}")


@webhooks.command("github-ci-status")
@click.option("--event-file", required=True, help="GitHub check/workflow webhook payload JSON file.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_github_ci_status(event_file: str, as_json: bool) -> None:
    """Normalize GitHub CI webhook payload into dashboard-friendly status."""
    from thomas.integrations import github_automation as gha

    try:
        event = _load_json_file(event_file)
        status = gha.normalize_ci_status_event(event)
        out = {"ok": True, "status": status}
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    row = out["status"]
    click.echo(f"kind: {row.get('kind')}")
    click.echo(f"repo: {row.get('repo')}")
    click.echo(f"status: {row.get('status')}")
    click.echo(f"conclusion: {row.get('conclusion')}")
    click.echo(f"url: {row.get('html_url')}")


def register_webhooks_commands(cli: click.Group) -> None:
    if "webhooks" not in cli.commands:
        cli.add_command(webhooks)
