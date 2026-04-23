"""Quick start command for express Thomas setup.

Auto-detects local models, prompts for minimal config,
and gets the user chatting in seconds.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

from thomas.cli.product_shell import print_section_heading

logger = logging.getLogger(__name__)


def _detect_ollama_models() -> list:
    """Detect Ollama models running locally."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _write_minimal_config(base_url: str, api_key: str, model: str, provider: str) -> Path:
    """Write a minimal thomas.toml."""
    provider_type = "anthropic" if provider == "anthropic" else "openai_compat"
    key_line = f'api_key = "{api_key}"' if api_key else "# No API key needed"

    content = f"""# Thomas Quick Config
[models.default]
provider = "{provider_type}"
base_url = "{base_url}"
{key_line}
model = "{model}"
max_tokens = 4096
context_window = 8192

[memory]
root = "./runtime"

[personality]
style = "balanced"
"""
    path = Path("thomas.toml")
    path.write_text(content, encoding="utf-8")
    return path


def run_quickstart() -> str | None:
    """Run express quickstart setup.

    Returns:
        Path to config file, or None if cancelled
    """
    print_section_heading("Thomas Quick Start")
    click.echo("  Start simple. Thomas can grow into deeper automation later.")

    if Path("thomas.toml").exists():
        click.echo(click.style("  OK: Config already exists.", fg="green"))
        return "thomas.toml"

    models = _detect_ollama_models()
    if models:
        click.echo(click.style(f"  OK: Found Ollama with {len(models)} model(s).", fg="green"))
        model = models[0]
        click.echo(f"  Using: {model}")
        path = _write_minimal_config("http://localhost:11434/v1", "", model, "ollama")
        click.echo(click.style(f"  OK: Config saved: {path}", fg="green"))
        click.echo(click.style('\n  Next: thomas chat "hello"', fg="yellow"))
        return str(path)

    click.echo("  No local models found. Let's set up a cloud provider.")
    click.echo("")
    click.echo("  1. OpenAI (GPT-4o)")
    click.echo("  2. Anthropic (Claude)")
    click.echo("  3. Groq (Llama - fast and free-tier friendly)")

    choice = click.prompt("  Provider", type=int, default=1)

    providers = {
        1: ("openai", "https://api.openai.com/v1", "gpt-4o"),
        2: ("anthropic", "https://api.anthropic.com", "claude-sonnet-4-20250514"),
        3: ("groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    }
    provider, base_url, model = providers.get(choice, providers[1])

    api_key = click.prompt("  API Key", hide_input=True)
    if not api_key.strip():
        click.echo(click.style("  No key provided. Aborting.", fg="red"))
        return None

    path = _write_minimal_config(base_url, api_key, model, provider)
    click.echo(click.style(f"\n  OK: Config saved: {path}", fg="green"))
    click.echo(click.style('  Next: thomas chat "hello"', fg="yellow"))
    click.echo("")
    return str(path)


def register_quickstart_commands(cli: click.Group) -> None:
    """Register quickstart command with the CLI."""

    @cli.command("quickstart")
    def quickstart_cmd():
        """Express setup - get chatting in 30 seconds."""
        run_quickstart()
