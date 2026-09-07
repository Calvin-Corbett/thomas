from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import PolicyContext, PolicyDecision


def _norm(p: str) -> str:
    return p.replace("\\", "/").rstrip("/")


def _extract_paths(args: dict[str, Any]) -> list[str]:
    """Heuristic extraction of path-like values from tool args."""
    out: list[str] = []
    keys = ("path", "paths", "src", "dst", "dest", "file", "filename", "directory", "dir", "target", "cwd", "root")
    for k, v in args.items():
        if k in keys:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out.extend([x for x in v if isinstance(x, str)])
    # shell commands sometimes include paths; ignore here (handled separately)
    return out


def _resolve_path(p: str, cwd: str) -> Path:
    try:
        pp = Path(p)
        if not pp.is_absolute():
            pp = Path(cwd) / pp
        # strict=False: do not require existence
        return pp.resolve(strict=False)
    except Exception:
        return Path(cwd).resolve(strict=False) / p


def _is_under(child: Path, root: Path) -> bool:
    try:
        child = child.resolve(strict=False)
        root = root.resolve(strict=False)
        child.relative_to(root)
        return True
    except Exception:
        return False


def _default_deny_roots(runtime_root: str) -> list[Path]:
    home = Path.home()
    roots: list[Path] = [
        home / ".ssh",
        home / ".aws",
        home / ".gnupg",
    ]
    # Windows-ish
    for env in ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v) / "ssh")
            roots.append(Path(v) / "Microsoft" / "Credentials")
    # Thomas runtime secrets
    if runtime_root:
        rr = Path(runtime_root)
        roots.append(rr / ".thomas")
    return roots


def _default_deny_paths(runtime_root: str) -> list[Path]:
    out: list[Path] = []
    if runtime_root:
        rr = Path(runtime_root) / ".thomas"
        out.extend(
            [
                rr / "secrets.json",
                rr / "secrets.toml",
                rr / "secrets.db",
                rr / "audit.sqlite3",
                rr / "runs.sqlite3",
            ]
        )
    return out


@dataclass(frozen=True)
class Rule:
    """Base class for policy rules.

    Each rule evaluates a PolicyContext and returns an optional PolicyDecision.
    If the rule matches, it returns a decision (allow, deny, or require_approval).
    If the rule doesn't match, it returns None to indicate no decision.
    """

    id: str

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        """Apply rule to a policy context.

        Evaluates the rule against the provided context. Returns a decision
        if the rule matches, or None if it doesn't apply.

        Args:
            ctx: PolicyContext containing tool name, args, cwd, etc.

        Returns:
            PolicyDecision (allow, deny, require_approval) or None if rule doesn't match

        Raises:
            Various exceptions depending on rule implementation
        """
        # Default: no decision (rule doesn't match)
        # Subclasses override to implement specific policy logic
        return None


@dataclass(frozen=True)
class DenyInvalidConfigRule(Rule):
    validation_errors: tuple[str, ...]

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        return PolicyDecision.deny(
            "Policy configuration is invalid; all tool calls are denied.",
            rule_id=self.id,
            validation_errors=list(self.validation_errors),
        )


# Maps preference-toggle group names to tool categories + exact tool names.
# Values ending with "." are prefix matches; others are exact matches.
_GROUP_TOOL_PATTERNS: dict[str, tuple[str, ...]] = {
    "shell": ("shell.", "shell", "bash.exec", "powershell.exec", "cmd.exec", "sandbox.run", "sandbox.test_snippet"),
    "file_write": (
        "file.write",
        "file.append",
        "file.delete",
        "file.mkdir",
        "file.rmdir",
        "file.move",
        "file.rename",
        "file.copy",
        "file.save",
        "file.create",
    ),
    "network": ("http.", "web_search", "web_fetch", "web."),
    "browser": ("browser.",),
    "channels": ("telegram.", "discord.", "slack.", "email.", "channel."),
    "git": ("git.", "git_exec"),
}
# Fallback: map group names to tool categories for catch-all matching.
_GROUP_CATEGORY_MAP: dict[str, tuple[str, ...]] = {
    "shell": ("shell",),
    "file_write": ("filesystem",),
    "network": ("web",),
    "browser": ("browser",),
    "channels": (),
    "git": ("git",),
}


@dataclass(frozen=True)
class DenyToolGroupRule(Rule):
    """Deny tools by named group (shell, file_write, network, browser, channels, git).

    Matches by tool name pattern first, then falls back to tool category if a
    tool_categories map is provided.
    """

    deny_groups: tuple[str, ...]
    tool_categories: dict[str, str] = field(default_factory=dict)  # tool_name -> category

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        tn = ctx.tool_name
        for group in self.deny_groups:
            # Check explicit tool name patterns.
            patterns = _GROUP_TOOL_PATTERNS.get(group, ())
            for pat in patterns:
                if pat.endswith(".") and tn.startswith(pat):
                    return PolicyDecision.deny(
                        f"Tool '{tn}' blocked by group:{group} deny policy.",
                        rule_id=self.id,
                        group=group,
                    )
                if tn == pat:
                    return PolicyDecision.deny(
                        f"Tool '{tn}' blocked by group:{group} deny policy.",
                        rule_id=self.id,
                        group=group,
                    )
            # Fallback: check tool category.
            cats = _GROUP_CATEGORY_MAP.get(group, ())
            if cats and self.tool_categories.get(tn, "") in cats:
                return PolicyDecision.deny(
                    f"Tool '{tn}' (category '{self.tool_categories[tn]}') blocked by group:{group} deny policy.",
                    rule_id=self.id,
                    group=group,
                )
        return None


@dataclass(frozen=True)
class DenyToolRule(Rule):
    deny_tools: tuple[str, ...]

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        if ctx.tool_name in self.deny_tools:
            return PolicyDecision.deny(f"Tool '{ctx.tool_name}' is denied by policy.", rule_id=self.id)
        return None


@dataclass(frozen=True)
class RequireApprovalToolRule(Rule):
    approval_tools: tuple[str, ...]

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        if ctx.tool_name in self.approval_tools:
            return PolicyDecision.require_approval(
                f"Tool '{ctx.tool_name}' requires approval by config.",
                rule_id=self.id,
            )
        return None


@dataclass(frozen=True)
class AllowToolRule(Rule):
    allow_tools: tuple[str, ...]

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        if ctx.tool_name in self.allow_tools:
            return PolicyDecision.allow(f"Tool '{ctx.tool_name}' is allowed by policy.", rule_id=self.id)
        return None


@dataclass(frozen=True)
class DenySecretReadRule(Rule):
    """Deny reads of secret-ish locations."""

    deny_roots: tuple[str, ...] = ()
    deny_paths: tuple[str, ...] = ()

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        candidates = _extract_paths(ctx.args)
        if not candidates:
            return None

        runtime_root = ctx.runtime_root or ""
        roots = (
            [_resolve_path(p, ctx.cwd) for p in self.deny_roots]
            if self.deny_roots
            else _default_deny_roots(runtime_root)
        )
        paths = (
            [_resolve_path(p, ctx.cwd) for p in self.deny_paths]
            if self.deny_paths
            else _default_deny_paths(runtime_root)
        )

        for raw in candidates:
            rp = _resolve_path(raw, ctx.cwd)
            for dp in paths:
                if rp == dp:
                    return PolicyDecision.deny(f"Blocked access to protected file: {rp}", rule_id=self.id)
            for root in roots:
                if _is_under(rp, root):
                    return PolicyDecision.deny(f"Blocked access under protected root: {root}", rule_id=self.id)
        return None


@dataclass(frozen=True)
class RequireApprovalWriteOutsideSandboxRule(Rule):
    """Require approval for writes outside sandbox_root."""

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        tool = ctx.tool_name.lower()
        # heuristic: tools that write or mutate filesystem
        mutating = any(
            s in tool
            for s in (
                "write",
                "append",
                "delete",
                "remove",
                "mkdir",
                "rmdir",
                "move",
                "rename",
                "copy",
                "save",
                "create",
            )
        )
        if not mutating:
            return None
        sandbox = Path(ctx.sandbox_root).resolve(strict=False)
        candidates = _extract_paths(ctx.args)
        for raw in candidates:
            rp = _resolve_path(raw, ctx.cwd)
            if not _is_under(rp, sandbox):
                return PolicyDecision.require_approval(
                    f"Write/mutate outside sandbox root requires approval: {rp}",
                    rule_id=self.id,
                    target=str(rp),
                    sandbox_root=str(sandbox),
                )
        return None


@dataclass(frozen=True)
class RequireApprovalGitPushRule(Rule):
    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        tn = ctx.tool_name.lower()
        if tn in ("git.push", "git", "git_exec"):
            # always_ask: publishing leaves the machine, so Builder mode does not
            # get to answer for it. See AlwaysAskOutboundRule for the rest.
            return PolicyDecision.require_approval(
                "git push requires approval.", rule_id=self.id, always_ask=True
            )
        # shell tool sometimes used
        cmd = ""
        if "cmd" in ctx.args and isinstance(ctx.args["cmd"], str):
            cmd = ctx.args["cmd"]
        elif "command" in ctx.args and isinstance(ctx.args["command"], str):
            cmd = ctx.args["command"]
        if cmd and "git push" in cmd.lower():
            return PolicyDecision.require_approval(
                "git push via shell requires approval.", rule_id=self.id, always_ask=True
            )
        return None


# Actions that leave this machine or cannot be undone. Everything here asks a
# human even when no_human_mode is "allow" — see AlwaysAskOutboundRule.
#
# Tool names are matched on the part before any dot as well as the whole name,
# so `discord.send_message` and `discord_send` both land. Shell fragments cover
# the same act typed into a terminal, because a gate the model can walk around
# by spelling it differently is decoration.
# The git tool names are deliberately absent: RequireApprovalGitPushRule already
# owns them and carries always_ask itself, so leaving them here would only change
# which rule_id gets reported for a decision that is identical either way.
_OUTBOUND_TOOL_NAMES: tuple[str, ...] = ()
# Match the ACTION, not the namespace. An earlier version listed "email",
# "discord", "trading" and friends as prefixes, which gated email.read,
# discord.read_messages, channels.list and trading.get_quote — inbound reads
# that send nothing. Under a strict gatekeeper those become hard refusals, so
# a gate meant to protect publishing made reading your own mail impossible.
#
# Only verbs that are themselves outbound may lead a name.
_OUTBOUND_TOOL_PREFIXES: tuple[str, ...] = (
    "deploy",
    "publish",
    "release",
)
_OUTBOUND_TOOL_SUFFIXES: tuple[str, ...] = (
    # messages sent as the owner
    ".send",
    ".send_message",
    ".post",
    ".reply",
    ".forward",
    ".broadcast",
    # publishing
    ".publish",
    ".deploy",
    ".release",
    # money
    ".buy",
    ".sell",
    ".order",
    ".place_order",
    ".transfer",
    ".checkout",
    ".charge",
    ".refund",
    ".pay",
    ".withdraw",
    ".deposit",
)
_OUTBOUND_SHELL_FRAGMENTS: tuple[str, ...] = (
    "git push",
    "gh pr ",
    "gh pr create",
    "gh release",
    "npm publish",
    "pip upload",
    "twine upload",
    "docker push",
)


@dataclass(frozen=True)
class AlwaysAskOutboundRule(Rule):
    """Ask a human before anything leaves the machine, in every mode.

    ``PolicyEngine.evaluate`` collapses REQUIRE_APPROVAL to ALLOW when
    no_human_mode is "allow", which is what Builder mode sets. That is correct
    for ordinary work and wrong for publishing: turning Builder on used to turn
    off the gate on ``git push`` as a side effect nobody chose.

    Decisions from this rule carry ``always_ask=True`` so the engine leaves them
    alone. Denial is stricter than asking, so a "deny" mode still denies.
    """

    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        name = str(ctx.tool_name or "").strip().lower()
        head = name.split(".", 1)[0]
        matched = (
            name in _OUTBOUND_TOOL_NAMES
            or head in _OUTBOUND_TOOL_PREFIXES
            or any(name.endswith(suffix) for suffix in _OUTBOUND_TOOL_SUFFIXES)
        )
        if not matched:
            for key in ("cmd", "command"):
                raw = ctx.args.get(key)
                if isinstance(raw, str) and raw:
                    lowered = raw.lower()
                    if any(fragment in lowered for fragment in _OUTBOUND_SHELL_FRAGMENTS):
                        matched = True
                        break
        if not matched:
            return None
        return PolicyDecision.require_approval(
            "This sends something out of your machine or spends money, so it asks first "
            "even in Builder mode.",
            rule_id=self.id,
            always_ask=True,
        )


@dataclass(frozen=True)
class RequireApprovalShellExecRule(Rule):
    def apply(self, ctx: PolicyContext) -> PolicyDecision | None:
        if ctx.tool_name.lower() in ("shell.exec", "shell", "bash.exec", "powershell.exec", "cmd.exec"):
            return PolicyDecision.require_approval("Shell execution requires approval.", rule_id=self.id)
        return None


def default_rules(
    *,
    validation_errors: Sequence[str] = (),
    allow_tools: Sequence[str] = (),
    deny_tools: Sequence[str] = (),
    require_approval_tools: Sequence[str] = (),
    deny_roots: Sequence[str] = (),
    deny_paths: Sequence[str] = (),
    deny_groups: Sequence[str] = (),
    tool_categories: dict[str, str] | None = None,
) -> list[Rule]:
    """Built-in rule library (order matters)."""
    rules: list[Rule] = []
    if validation_errors:
        rules.append(
            DenyInvalidConfigRule(
                id="deny_invalid_config",
                validation_errors=tuple(validation_errors),
            )
        )
    # Group deny evaluated BEFORE individual deny so toggles take precedence.
    if deny_groups:
        rules.append(
            DenyToolGroupRule(
                id="deny_tool_groups",
                deny_groups=tuple(deny_groups),
                tool_categories=dict(tool_categories or {}),
            )
        )
    if deny_tools:
        rules.append(DenyToolRule(id="deny_tools", deny_tools=tuple(deny_tools)))

    rules.extend(
        [
            DenySecretReadRule(id="deny_secret_reads", deny_roots=tuple(deny_roots), deny_paths=tuple(deny_paths)),
            # Sits after the deny rules (refusing outright is stronger than asking)
            # and ahead of everything else, so neither the generic approval rules
            # nor an allow_tools entry can answer for an outbound action first.
            AlwaysAskOutboundRule(id="always_ask_outbound"),
            RequireApprovalShellExecRule(id="approve_shell_exec"),
            RequireApprovalGitPushRule(id="approve_git_push"),
            RequireApprovalWriteOutsideSandboxRule(id="approve_write_outside_sandbox"),
        ]
    )
    if require_approval_tools:
        rules.append(
            RequireApprovalToolRule(
                id="config_tools_require_approval",
                approval_tools=tuple(require_approval_tools),
            )
        )
    # An allowlist may label an otherwise unrestricted tool, but it must never
    # bypass a deny or approval decision. Keep this rule last.
    if allow_tools:
        rules.append(AllowToolRule(id="allow_tools", allow_tools=tuple(allow_tools)))
    return rules
