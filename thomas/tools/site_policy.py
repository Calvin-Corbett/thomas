"""Sensitive-site policy for agentic browser actions.

Frontier browser agents (Claude in Chrome, ChatGPT's agent mode) pause on
banking, payment, health and government sites so the person can act or watch.
Thomas's browser tools clicked and typed anywhere the host policy allowed a
fetch. This module is the pause: a built-in list of sensitive hosts, the
hosts the user adds in settings, and a mode - ``pause`` (refuse the action
and say why) or ``allow``.

``browser.click`` and ``browser.type`` consult it with the page's current URL
before acting. Reading a page (``browser.open``, ``browser.extract``) is not
gated here; looking is not acting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# Hosts where an autonomous click or keystroke can move money, change a
# record, or expose credentials. Suffix match: "chase.com" covers
# "secure01a.chase.com". Kept deliberately short and obvious; the user's own
# additions live in settings.
DEFAULT_SENSITIVE_HOSTS: tuple[str, ...] = (
    # US banks and brokerages
    "wellsfargo.com",
    "chase.com",
    "bankofamerica.com",
    "citi.com",
    "citibank.com",
    "usbank.com",
    "capitalone.com",
    "pnc.com",
    "truist.com",
    "schwab.com",
    "fidelity.com",
    "vanguard.com",
    "ally.com",
    "discover.com",
    "americanexpress.com",
    "navyfederal.org",
    # payments and money movement
    "paypal.com",
    "venmo.com",
    "cash.app",
    "zellepay.com",
    "stripe.com",
    "coinbase.com",
    "kraken.com",
    "robinhood.com",
    # government and tax
    "irs.gov",
    "ssa.gov",
    "login.gov",
    "id.me",
    "usa.gov",
    "dmv.org",
    # health
    "mychart.com",
    "healthcare.gov",
    "medicare.gov",
)

_MODES = ("pause", "allow")


def _host_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except (ValueError, AttributeError):
        return ""
    return host.rstrip(".")


def _matches(host: str, rule: str) -> bool:
    rule = rule.strip().lower().lstrip(".")
    if not host or not rule:
        return False
    return host == rule or host.endswith("." + rule)


@dataclass(frozen=True)
class SitePolicy:
    """What counts as sensitive, and what happens when the agent tries to act there."""

    extra_hosts: tuple[str, ...] = ()
    mode: str = "pause"
    builtin: tuple[str, ...] = field(default=DEFAULT_SENSITIVE_HOSTS)

    def __post_init__(self) -> None:
        cleaned = tuple(h.strip().lower().lstrip(".") for h in self.extra_hosts if str(h).strip())
        object.__setattr__(self, "extra_hosts", cleaned)
        mode = str(self.mode or "pause").strip().lower()
        object.__setattr__(self, "mode", mode if mode in _MODES else "pause")

    def matched_rule(self, url: str) -> str | None:
        host = _host_of(url)
        for rule in (*self.extra_hosts, *self.builtin):
            if _matches(host, rule):
                return rule
        return None

    def is_sensitive(self, url: str) -> bool:
        return self.matched_rule(url) is not None


_current = SitePolicy()


def configure_site_policy(
    *, extra_hosts: list[str] | tuple[str, ...] | str | None = None, mode: str = "pause"
) -> SitePolicy:
    """Install the process-wide policy (called when preferences load or change)."""
    global _current
    if isinstance(extra_hosts, str):
        hosts: tuple[str, ...] = tuple(
            part.strip() for part in extra_hosts.replace("\n", ",").split(",") if part.strip()
        )
    else:
        hosts = tuple(str(h) for h in (extra_hosts or ()))
    _current = SitePolicy(extra_hosts=hosts, mode=mode)
    return _current


def current_site_policy() -> SitePolicy:
    return _current


def sensitive_action_verdict(url: str, *, action: str, policy: SitePolicy | None = None) -> str | None:
    """Return the pause text for ``action`` on ``url``, or None when the action may proceed."""
    active = policy or _current
    if active.mode == "allow":
        return None
    rule = active.matched_rule(url)
    if rule is None:
        return None
    host = _host_of(url) or rule
    return (
        f"Paused: {host} is a sensitive site (matches '{rule}'), so Thomas will not {action} there on its own. "
        "Do this step yourself in the browser, or change the sensitive-site setting to 'allow' "
        "(Settings > Tools > Sensitive sites) if you want Thomas to act on this site."
    )


__all__ = [
    "DEFAULT_SENSITIVE_HOSTS",
    "SitePolicy",
    "configure_site_policy",
    "current_site_policy",
    "sensitive_action_verdict",
]
