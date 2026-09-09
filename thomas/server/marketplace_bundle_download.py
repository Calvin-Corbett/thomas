"""Download marketplace plugin bundles from allow-listed public hosts.

Serves the Install-from-URL flow for both tiers (signed bundles and Agent
Plugins). The allowlist plus ``validate_public_url`` keep this from becoming
an SSRF primitive: only public GitHub archive/raw hosts are reachable, the
final host is re-checked after redirects, and the payload is capped.
"""

from __future__ import annotations

from urllib.parse import urlparse

import aiohttp

from thomas.server.net_safety import validate_public_url

PLUGIN_URL_HOSTS = frozenset(
    {
        "github.com",
        "codeload.github.com",
        "objects.githubusercontent.com",
        "raw.githubusercontent.com",
    }
)
PLUGIN_URL_MAX_BYTES = 30 * 1024 * 1024


def _host_of(value: str) -> str:
    host = urlparse(value).hostname if isinstance(value, str) else value
    return str(host or "").strip().lower()


async def download_plugin_bundle(raw_url: str) -> bytes:
    """Fetch a plugin bundle zip from an allow-listed public host."""
    url = validate_public_url(raw_url)
    if _host_of(url) not in PLUGIN_URL_HOSTS:
        allowed = ", ".join(sorted(PLUGIN_URL_HOSTS))
        raise ValueError(f"Plugin URLs are limited to: {allowed}")
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, max_redirects=5) as response:
            if response.status != 200:
                raise ValueError(f"Download failed (HTTP {response.status})")
            if str(response.url.host or "").strip().lower() not in PLUGIN_URL_HOSTS:
                raise ValueError("Download redirected outside the allowed hosts")
            data = bytearray()
            async for chunk in response.content.iter_chunked(1 << 16):
                data.extend(chunk)
                if len(data) > PLUGIN_URL_MAX_BYTES:
                    raise ValueError("Plugin bundle is larger than 30MB")
            return bytes(data)
