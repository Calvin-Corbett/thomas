"""Interactive setup wizard for Thomas first-run configuration.

Walks users through provider selection, API key input, model
selection, connection testing, and config file generation.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

from thomas.cli.product_shell import print_section_heading, print_step_heading

logger = logging.getLogger(__name__)

PROVIDERS: list[dict[str, str]] = [
    {
        "id": "ollama",
        "name": "Ollama (Local)",
        "desc": "Run models locally - free, private, no API key needed",
        "base_url": "http://localhost:11434/v1",
        "key_required": "false",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "desc": "GPT-4o, GPT-4-turbo, o1 - cloud API",
        "base_url": "https://api.openai.com/v1",
        "key_required": "true",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "desc": "Claude Sonnet, Opus, Haiku - cloud API",
        "base_url": "https://api.anthropic.com",
        "key_required": "true",
    },
    {
        "id": "google",
        "name": "Google AI",
        "desc": "Gemini Pro, Gemini Flash - cloud API",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_required": "true",
    },
    {
        "id": "groq",
        "name": "Groq",
        "desc": "Ultra-fast inference - Llama, Mixtral",
        "base_url": "https://api.groq.com/openai/v1",
        "key_required": "true",
    },
    {
        "id": "custom",
        "name": "Custom (OpenAI-compatible)",
        "desc": "Any provider with an OpenAI-compatible API",
        "base_url": "",
        "key_required": "true",
    },
]

MODEL_RECOMMENDATIONS: dict[str, list[tuple[str, str]]] = {
    "ollama": [
        ("llama3.2:latest", "Best all-around local model"),
        ("qwen2.5-coder:7b", "Optimized for coding"),
        ("mistral:latest", "Fast and capable"),
    ],
    "openai": [
        ("gpt-4o", "Best quality (Recommended)"),
        ("gpt-4o-mini", "Fast and cheap"),
        ("o1-mini", "Reasoning model"),
    ],
    "anthropic": [
        ("claude-sonnet-4-20250514", "Best balance (Recommended)"),
        ("claude-haiku-4-20250414", "Fast and cheap"),
        ("claude-opus-4-20250514", "Highest quality"),
    ],
    "google": [("gemini-2.0-flash", "Fast (Recommended)"), ("gemini-2.0-pro", "Highest quality")],
    "groq": [("llama-3.3-70b-versatile", "Best quality (Recommended)"), ("llama-3.1-8b-instant", "Ultra fast")],
    "custom": [],
}


def _banner() -> None:
    """Print the setup wizard banner."""
    print_section_heading("Thomas Setup Wizard")
    click.echo("  Start simple. You can add more systems and surfaces later.")


def _step(n: int, title: str) -> None:
    """Print a step header."""
    print_step_heading(n, title)


def _detect_existing_config() -> Path | None:
    """Check if thomas.toml already exists."""
    candidates = [Path("thomas.toml"), Path.home() / ".thomas" / "thomas.toml"]
    for p in candidates:
        if p.exists():
            return p
    return None


def _detect_ollama() -> bool:
    """Check if Ollama is running locally."""
    try:
        import urllib.request

        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _test_connection(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """Test connection to the model provider."""
    try:
        import json
        import urllib.request

        url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 10,
            }
        ).encode()

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, reply.strip() or "(empty response - but connection works)"
    except Exception as e:
        return False, str(e)[:200]


def _generate_config(
    provider_id: str,
    base_url: str,
    api_key: str,
    model: str,
    personality: str,
) -> str:
    """Generate thomas.toml content."""
    provider_type = "openai_compat"
    if provider_id == "anthropic":
        provider_type = "anthropic"
    elif provider_id == "google":
        provider_type = "google"

    key_line = f'api_key = "{api_key}"' if api_key else '# api_key = ""  # Not needed for local models'

    return f"""# Thomas Configuration
# Generated by setup wizard

[models.default]
provider = "{provider_type}"
base_url = "{base_url}"
{key_line}
model = "{model}"
max_tokens = 4096
context_window = 8192

[memory]
root = "./runtime"
context_budget = 12000

[tools]
sandbox_root = "."
allow_shell = false
shell_timeout = 30

[server]
access_mode = "local"

[personality]
style = "{personality}"
"""


def run_wizard() -> str | None:
    """Run the interactive setup wizard.

    Returns:
        Path to generated config file, or None if cancelled
    """
    _banner()

    existing = _detect_existing_config()
    if existing:
        click.echo(f"  Found existing config: {existing}")
        if not click.confirm("  Reconfigure?", default=False):
            click.echo("  Keeping existing config. Done!")
            return str(existing)

    _step(1, "Choose Your AI Provider")

    ollama_running = _detect_ollama()
    if ollama_running:
        click.echo(click.style("  OK: Ollama detected running locally.", fg="green"))

    for i, provider in enumerate(PROVIDERS, 1):
        marker = " <- local default" if provider["id"] == "ollama" and ollama_running else ""
        click.echo(f"  {i}. {provider['name']:30s} {provider['desc']}{marker}")

    choice = click.prompt("\n  Select provider", type=int, default=1 if ollama_running else 2)
    provider = PROVIDERS[max(0, min(choice - 1, len(PROVIDERS) - 1))]

    base_url = provider["base_url"]
    if provider["id"] == "custom":
        base_url = click.prompt("  Base URL", default="http://localhost:8080/v1")

    api_key = ""
    if provider["key_required"] == "true":
        _step(2, "API Key")
        api_key = click.prompt("  Enter your API key", hide_input=True)
        if not api_key.strip():
            click.echo(click.style("  Warning: no API key provided. Connection may fail.", fg="yellow"))
    else:
        click.echo(click.style("\n  No API key needed for local models.", fg="green"))

    _step(3, "Choose Your Model")

    models = MODEL_RECOMMENDATIONS.get(provider["id"], [])
    if models:
        for i, (model_name, desc) in enumerate(models, 1):
            click.echo(f"  {i}. {model_name:35s} {desc}")
        idx = click.prompt("\n  Select model", type=int, default=1)
        model = models[max(0, min(idx - 1, len(models) - 1))][0]
    else:
        model = click.prompt("  Enter model name")

    _step(4, "Testing Connection")
    click.echo(f"  Connecting to {model}...")

    ok, reply = _test_connection(base_url, api_key, model)
    if ok:
        click.echo(click.style(f'  OK: Connected. Response: "{reply[:60]}"', fg="green"))
    else:
        click.echo(click.style(f"  ERROR: Connection failed: {reply[:100]}", fg="red"))
        if not click.confirm("  Continue anyway?", default=True):
            click.echo("  Setup cancelled.")
            return None

    _step(5, "Personality Preferences")
    click.echo("  1. Casual        - relaxed, friendly, uses humor")
    click.echo("  2. Balanced      - smart and conversational (Recommended)")
    click.echo("  3. Professional  - formal, precise, business-focused")
    p_choice = click.prompt("\n  Select style", type=int, default=2)
    personality = ["casual", "balanced", "professional"][max(0, min(p_choice - 1, 2))]

    _step(6, "Saving Configuration")

    config_content = _generate_config(provider["id"], base_url, api_key, model, personality)
    config_path = Path("thomas.toml")

    config_path.write_text(config_content, encoding="utf-8")
    click.echo(click.style(f"  OK: Config saved to {config_path.resolve()}", fg="green"))

    print_section_heading("Setup Complete")
    click.echo("  Quick start commands:")
    click.echo(click.style('    thomas chat "hello"', fg="yellow") + "    - single query")
    click.echo(click.style("    thomas repl", fg="yellow") + "              - interactive mode")
    click.echo(click.style("    thomas serve", fg="yellow") + "             - web UI at localhost:8899")
    click.echo("")

    return str(config_path)


def register_setup_commands(cli: click.Group) -> None:
    """Register setup wizard commands with the CLI."""

    @cli.command("setup")
    def setup_cmd():
        """Interactive setup wizard - configure Thomas step by step."""
        run_wizard()
