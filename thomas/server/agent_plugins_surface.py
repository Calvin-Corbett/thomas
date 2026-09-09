"""The generated about surface for an installed Agent Plugin.

Every installed plugin needs a surface page (the desktop-plugin contract
requires one); an Agent Plugin does not ship HTML, so Thomas generates a
small tokens.css-themed page stating what was installed and — prominently —
that this is the unverified community tier with its tool servers off.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlparse

from thomas.server.agent_plugins_manifest import AgentPluginInfo


def _is_plain_https_url(value: str) -> bool:
    """Only a parseable https URL may become a link. Everything in
    plugin.json is attacker-controlled; quotes are escaped by ``esc`` but a
    URL that does not parse cleanly has no business in an href at all."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def about_surface_html(info: AgentPluginInfo) -> str:
    def esc(text: str) -> str:
        return escape(text, quote=True)

    skills = "".join(f"<li><code>{esc(s)}</code></li>" for s in info.skills) or "<li>None</li>"
    servers = (
        "".join(
            f"<li><code>{esc(s)}</code> (registered off; enable in MCP settings)</li>"
            for s in info.mcp_servers
        )
        or "<li>None</li>"
    )
    author = esc(info.author_name) or "Unknown author"
    home = (
        f'<p><a href="{esc(info.homepage)}" target="_blank" rel="noopener noreferrer">{esc(info.homepage)}</a></p>'
        if _is_plain_https_url(info.homepage)
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(info.name)}</title>
<link rel="stylesheet" href="/static/css/tokens.css">
<style>
  body {{ padding: 28px; max-width: 720px; margin: 0 auto; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--warn-line); background: var(--warn-bg); color: var(--warn-ink); font-size: 12px; font-weight: 700; }}
  h1 {{ font-family: var(--font-head); margin: 10px 0 4px; }}
  section {{ margin-top: 18px; padding: 14px 16px; border: 1px solid var(--c-border); border-radius: var(--r-card); background: var(--c-surface); }}
  ul {{ margin: 8px 0 0 18px; }}
</style>
</head>
<body>
<span class="badge">Community plugin — unverified</span>
<h1>{esc(info.name)}</h1>
<p style="color: var(--c-dim);">{esc(info.description) or "An Agent Plugin (agent-plugins.org standard)."}</p>
<p style="color: var(--c-muted); font-size: 13px;">Version {esc(info.version)} &middot; {author}</p>
{home}
<section><strong>Skills</strong><ul>{skills}</ul></section>
<section><strong>MCP servers</strong><ul>{servers}</ul></section>
<section style="border-color: var(--warn-line);"><strong>Trust</strong>
<p style="color: var(--c-dim); font-size: 13px; margin-top: 6px;">This plugin came from the open Agent Plugins standard, not the verified store. Thomas installed its skills, and registered its tool servers switched off. Nothing runs until you enable it.</p>
</section>
</body>
</html>
"""
