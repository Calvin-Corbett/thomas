from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TailscalePolicy:
    """Connection policy for companion-control traffic."""

    tailscale_only: bool = True
    allowed_tailnet_suffix: str = ".ts.net"
    allow_localhost_dev: bool = True


def is_tailscale_identity(peer_identity: str, policy: Optional[TailscalePolicy] = None) -> bool:
    policy = policy or TailscalePolicy()
    text = str(peer_identity or "").strip().lower()
    if not text:
        return False
    if policy.allow_localhost_dev and text in {"localhost", "127.0.0.1", "::1"}:
        return True
    if text.endswith(policy.allowed_tailnet_suffix.lower()):
        return True
    if text.startswith("ts:"):
        return True
    return False


def assert_peer_allowed(peer_identity: str, policy: Optional[TailscalePolicy] = None) -> None:
    policy = policy or TailscalePolicy()
    if not policy.tailscale_only:
        return
    if not is_tailscale_identity(peer_identity, policy=policy):
        raise PermissionError("companion control plane requires tailscale identity")
