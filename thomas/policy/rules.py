from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .types import PolicyContext, PolicyDecision

def _norm(p: str) -> str:
    return p.replace("\\", "/").rstrip("/")

def _extract_paths(args: Dict[str, Any]) -> List[str]:
    """Heuristic extraction of path-like values from tool args."""
    out: List[str] = []
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

def _default_deny_roots(runtime_root: str) -> List[Path]:
    home = Path.home()
    roots: List[Path] = [
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

def _default_deny_paths(runtime_root: str) -> List[Path]:
    out: List[Path] = []
    if runtime_root:
        rr = Path(runtime_root) / ".thomas"
        out.extend([
            rr / "secrets.json",
            rr / "secrets.toml",
            rr / "secrets.db",
            rr / "audit.sqlite3",
            rr / "runs.sqlite3",
        ])
    return out

@dataclass(frozen=True)
class Rule:
    id: str
    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        raise NotImplementedError

@dataclass(frozen=True)
class DenyToolRule(Rule):
    deny_tools: Tuple[str, ...]
    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        if ctx.tool_name in self.deny_tools:
            return PolicyDecision.deny(f"Tool '{ctx.tool_name}' is denied by policy.", rule_id=self.id)
        return None

@dataclass(frozen=True)
class AllowToolRule(Rule):
    allow_tools: Tuple[str, ...]
    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        if ctx.tool_name in self.allow_tools:
            return PolicyDecision.allow(f"Tool '{ctx.tool_name}' is allowed by policy.", rule_id=self.id)
        return None

@dataclass(frozen=True)
class DenySecretReadRule(Rule):
    """Deny reads of secret-ish locations."""
    deny_roots: Tuple[str, ...] = ()
    deny_paths: Tuple[str, ...] = ()

    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        candidates = _extract_paths(ctx.args)
        if not candidates:
            return None

        runtime_root = ctx.runtime_root or ""
        roots = [_resolve_path(p, ctx.cwd) for p in self.deny_roots] if self.deny_roots else _default_deny_roots(runtime_root)
        paths = [_resolve_path(p, ctx.cwd) for p in self.deny_paths] if self.deny_paths else _default_deny_paths(runtime_root)

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
    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        tool = ctx.tool_name.lower()
        # heuristic: tools that write or mutate filesystem
        mutating = any(s in tool for s in ("write", "append", "delete", "remove", "mkdir", "rmdir", "move", "rename", "copy", "save", "create"))
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
    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        tn = ctx.tool_name.lower()
        if tn in ("git.push", "git", "git_exec"):
            return PolicyDecision.require_approval("git push requires approval.", rule_id=self.id)
        # shell tool sometimes used
        cmd = ""
        if "cmd" in ctx.args and isinstance(ctx.args["cmd"], str):
            cmd = ctx.args["cmd"]
        elif "command" in ctx.args and isinstance(ctx.args["command"], str):
            cmd = ctx.args["command"]
        if cmd and "git push" in cmd.lower():
            return PolicyDecision.require_approval("git push via shell requires approval.", rule_id=self.id)
        return None

@dataclass(frozen=True)
class RequireApprovalShellExecRule(Rule):
    def apply(self, ctx: PolicyContext) -> Optional[PolicyDecision]:
        if ctx.tool_name.lower() in ("shell.exec", "shell", "bash.exec", "powershell.exec", "cmd.exec"):
            return PolicyDecision.require_approval("Shell execution requires approval.", rule_id=self.id)
        return None

def default_rules(
    *,
    allow_tools: Sequence[str] = (),
    deny_tools: Sequence[str] = (),
    deny_roots: Sequence[str] = (),
    deny_paths: Sequence[str] = (),
) -> List[Rule]:
    """Built-in rule library (order matters)."""
    rules: List[Rule] = []
    if allow_tools:
        rules.append(AllowToolRule(id="allow_tools", allow_tools=tuple(allow_tools)))
    if deny_tools:
        rules.append(DenyToolRule(id="deny_tools", deny_tools=tuple(deny_tools)))

    rules.extend([
        DenySecretReadRule(id="deny_secret_reads", deny_roots=tuple(deny_roots), deny_paths=tuple(deny_paths)),
        RequireApprovalShellExecRule(id="approve_shell_exec"),
        RequireApprovalGitPushRule(id="approve_git_push"),
        RequireApprovalWriteOutsideSandboxRule(id="approve_write_outside_sandbox"),
    ])
    return rules
