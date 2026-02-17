from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .config import PolicyConfig, AutomationSiteRule
from .rules import Rule, default_rules
from .types import PolicyContext, PolicyDecision, PolicyDecisionType


_HOST_PATTERN = re.compile(r"\b([a-z0-9][a-z0-9\-.]*\.[a-z]{2,63})\b", re.IGNORECASE)


def _normalize_mode(raw: str) -> str:
    v = str(raw or "").strip().lower()
    if v in {"allow", "allowed", "autonomous", "auto", "autonomous_allowed"}:
        return "autonomous_allowed"
    if v in {"manual", "manual_only", "approval", "require_approval"}:
        return "manual_only"
    if v in {"deny", "denied", "block", "blocked"}:
        return "blocked"
    return "autonomous_allowed"


def _normalize_domain(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        try:
            s = str(urlparse(s).hostname or "").strip().lower()
        except Exception:
            pass
    if s.startswith("*."):
        s = s[2:]
    if s.startswith("www."):
        s = s[4:]
    if ":" in s:
        s = s.split(":", 1)[0]
    return s.strip(".")


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield k
            yield from _iter_strings(v)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
        return


def _extract_domains_from_context(ctx: PolicyContext) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()

    def _add(host: str) -> None:
        d = _normalize_domain(host)
        if not d:
            return
        if d in seen:
            return
        seen.add(d)
        out.append(d)

    priority_keys = {
        "url",
        "urls",
        "site",
        "sites",
        "domain",
        "domains",
        "host",
        "hostname",
        "website",
    }
    if isinstance(ctx.args, dict):
        for k, v in ctx.args.items():
            key = str(k or "").strip().lower()
            if key in priority_keys:
                if isinstance(v, str):
                    _add(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            _add(item)

    for text in _iter_strings(ctx.args):
        s = str(text or "").strip()
        if not s:
            continue
        if "://" in s:
            try:
                host = urlparse(s).hostname
            except Exception:
                host = None
            if host:
                _add(host)
        for m in _HOST_PATTERN.finditer(s):
            _add(m.group(1))

    return out


def _site_rule_matches(domain: str, rule_domain: str) -> bool:
    d = _normalize_domain(domain)
    r = _normalize_domain(rule_domain)
    if not d or not r:
        return False
    return d == r or d.endswith("." + r)


def _strictest_mode(modes: Iterable[str]) -> str:
    rank = {
        "autonomous_allowed": 0,
        "manual_only": 1,
        "blocked": 2,
    }
    best = "autonomous_allowed"
    best_rank = -1
    for raw in modes:
        mode = _normalize_mode(raw)
        r = rank.get(mode, 0)
        if r > best_rank:
            best_rank = r
            best = mode
    return best


@dataclass
class PolicyEngine:
    config: PolicyConfig
    rules: List[Rule]

    @staticmethod
    def from_config(cfg: PolicyConfig, *, include_default_rules: bool = True) -> "PolicyEngine":
        rules: List[Rule] = []
        if include_default_rules:
            rules = default_rules(
                allow_tools=cfg.allow_tools,
                deny_tools=cfg.deny_tools,
                deny_roots=cfg.deny_roots,
                deny_paths=cfg.deny_paths,
            )
        return PolicyEngine(cfg, rules)

    def automation_sites(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self.config.automation.sites:
            domain = _normalize_domain(getattr(row, "domain", ""))
            if not domain:
                continue
            rows.append(
                {
                    "domain": domain,
                    "mode": _normalize_mode(getattr(row, "mode", "autonomous_allowed")),
                    "note": str(getattr(row, "note", "") or ""),
                }
            )
        return rows

    def resolve_automation_mode_for_domain(self, domain: str) -> Dict[str, Any]:
        d = _normalize_domain(domain)
        if not d:
            return {
                "domain": "",
                "mode": "autonomous_allowed",
                "source": "none",
                "matched_domain": "",
                "note": "",
                "enabled": bool(self.config.automation.enabled),
            }
        if not self.config.automation.enabled:
            return {
                "domain": d,
                "mode": "autonomous_allowed",
                "source": "disabled",
                "matched_domain": "",
                "note": "",
                "enabled": False,
            }

        for row in self.config.automation.sites:
            entry_domain = _normalize_domain(getattr(row, "domain", ""))
            if not entry_domain:
                continue
            if _site_rule_matches(d, entry_domain):
                return {
                    "domain": d,
                    "mode": _normalize_mode(getattr(row, "mode", "autonomous_allowed")),
                    "source": "site",
                    "matched_domain": entry_domain,
                    "note": str(getattr(row, "note", "") or ""),
                    "enabled": True,
                }

        return {
            "domain": d,
            "mode": _normalize_mode(self.config.automation.default_mode),
            "source": "default",
            "matched_domain": "",
            "note": "",
            "enabled": True,
        }

    def resolve_automation_for_context(self, ctx: PolicyContext) -> Dict[str, Any]:
        domains = _extract_domains_from_context(ctx)
        if not domains:
            return {
                "domains": [],
                "domain": "",
                "mode": "autonomous_allowed",
                "source": "none",
                "matched_domain": "",
                "note": "",
                "enabled": bool(self.config.automation.enabled),
            }

        details = [self.resolve_automation_mode_for_domain(d) for d in domains]
        final_mode = _strictest_mode(d.get("mode", "autonomous_allowed") for d in details)
        selected = next((d for d in details if _normalize_mode(d.get("mode", "")) == final_mode), details[0])
        return {
            "domains": domains,
            "domain": selected.get("domain", ""),
            "mode": final_mode,
            "source": selected.get("source", "none"),
            "matched_domain": selected.get("matched_domain", ""),
            "note": selected.get("note", ""),
            "enabled": bool(self.config.automation.enabled),
        }

    def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        # Explicit allow/deny lists in config can short-circuit via rule order.
        for rule in self.rules:
            dec = rule.apply(ctx)
            if dec is not None:
                return dec

        auto = self.resolve_automation_for_context(ctx)
        mode = str(auto.get("mode") or "autonomous_allowed")
        if mode == "blocked":
            reason = f"Automation blocked by site policy for domain '{auto.get('domain')}'."
            if auto.get("note"):
                reason += f" {auto.get('note')}"
            return PolicyDecision.deny(
                reason,
                rule_id="automation_site_policy",
                policy_scope="automation",
                domain=auto.get("domain"),
                mode=mode,
                source=auto.get("source"),
                matched_domain=auto.get("matched_domain"),
            )
        if mode == "manual_only":
            reason = f"Site policy for '{auto.get('domain')}' requires manual approval."
            if auto.get("note"):
                reason += f" {auto.get('note')}"
            return PolicyDecision.require_approval(
                reason,
                rule_id="automation_site_policy",
                policy_scope="automation",
                domain=auto.get("domain"),
                mode=mode,
                source=auto.get("source"),
                matched_domain=auto.get("matched_domain"),
            )

        # Optional: force approvals for listed tools
        if ctx.tool_name in self.config.guardrails.tools_require_approval:
            return PolicyDecision.require_approval(f"Tool '{ctx.tool_name}' requires approval by config.", rule_id="config_tools_require_approval")

        return PolicyDecision.allow("No matching rule; allowed.", rule_id="default_allow")
