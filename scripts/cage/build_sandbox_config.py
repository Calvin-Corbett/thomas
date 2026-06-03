#!/usr/bin/env python3
"""Generate a Windows Sandbox (.wsb) config that physically contains a worker.

Cage PROBLEM 1 (containment). The OS-user + ACL layer
(``provision_cage.ps1``) stops the agent from touching *your* files, but a
non-admin same-host shell still has the network and can read other repos. As
the Praxis exercise concluded, no local gate stops a same-user shell — only OS
isolation does. On Windows 11 Pro the built-in **Windows Sandbox** is exactly
that: a disposable, kernel-isolated VM where *nothing exists but what you
explicitly map in*.

This module emits a ``.wsb`` whose properties give the three guarantees the
goal asks for:

* **cannot clone outside its box / reach the network** — ``<Networking>`` is
  ``Disable`` by default, so ``git clone https://…``, ``git push``, and any
  exfil simply have no network to use. (The host-side commit-master does the
  push; the worker never needs the network.)
* **cannot reach other repos** — only the Thomas repo is mapped; every other
  path on the host is invisible inside the sandbox.
* **cannot escape its allowed paths** — the sandbox filesystem contains only
  the mapped folders plus a throwaway OS; changes outside the mapped
  read-write folders evaporate when the box closes.

The cage's one-way channels double as the air-gapped bridge: the worker drops
submissions into the mapped ``inbox`` (read-write) and reads verdicts from the
mapped ``outbox`` (read-only); the commit-master, running on the *host* outside
the sandbox, watches those same host folders. No network required.

stdlib-only; produces well-formed XML via ElementTree so it is unit-testable
without Windows present. Launching the box (``WindowsSandbox.exe``) and enabling
the optional feature are Calvin's elevated steps — see ``docs/CAGE_SETUP.md``.
"""

from __future__ import annotations

import argparse
import sys
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

_REPO_ROOT = Path(__file__).resolve().parents[2]


class ContainmentError(ValueError):
    """Raised when a requested mapping would defeat containment."""


@dataclass
class FolderMapping:
    host: str
    sandbox: str
    read_only: bool = True


@dataclass
class SandboxConfig:
    repo_host: str
    repo_sandbox: str = r"C:\Thomas"
    cage_root_host: str = r"C:\ProgramData\ThomasCage"
    cage_root_sandbox: str = r"C:\ThomasCage"
    networking: bool = False  # False => <Networking>Disable</Networking>
    memory_mb: int = 4096
    agent: str = "thomas-agent"
    extra_mappings: list[FolderMapping] = field(default_factory=list)
    logon_command: str = ""

    def mappings(self) -> list[FolderMapping]:
        """The full mapping set: repo (rw) + cage inbox (rw) + outbox (ro)."""
        inbox_host = str(PureWindowsPath(self.cage_root_host) / "inbox")
        outbox_host = str(PureWindowsPath(self.cage_root_host) / "outbox")
        inbox_sb = str(PureWindowsPath(self.cage_root_sandbox) / "inbox")
        outbox_sb = str(PureWindowsPath(self.cage_root_sandbox) / "outbox")
        base = [
            FolderMapping(self.repo_host, self.repo_sandbox, read_only=False),
            FolderMapping(inbox_host, inbox_sb, read_only=False),
            FolderMapping(outbox_host, outbox_sb, read_only=True),
        ]
        return base + list(self.extra_mappings)

    def default_logon(self) -> str:
        # Point the worker's cage at the mapped inbox/outbox root and drop a
        # console in the repo. Keep it a single command (LogonCommand runs one).
        repo = self.repo_sandbox
        cage = self.cage_root_sandbox
        return (
            f'cmd.exe /c "setx THOMAS_CAGE_ROOT {cage} >NUL & '
            f"setx THOMAS_AGENT_ID {self.agent} >NUL & "
            f'start cmd.exe /k cd /d {repo}"'
        )


# Host folders that must NEVER be mapped wholesale — doing so re-exposes the
# very things the sandbox is meant to hide and defeats containment.
def _is_overbroad(host: str) -> str:
    p = PureWindowsPath(str(host).strip().rstrip("\\/"))
    parts = p.parts
    if not parts:
        return "empty host folder"
    # Drive root, e.g. "C:\"
    if len(parts) == 1 and parts[0].endswith(":\\") or (len(parts) == 1 and parts[0].endswith(":")):
        return f"drive root {host!r}"
    low = [seg.lower() for seg in parts]
    # "C:\" alone, "C:\Users", or "C:\Users\<name>" (a whole profile)
    if len(parts) <= 2 and low[1:2] == ["users"]:
        return f"the entire Users tree {host!r}"
    if len(parts) == 3 and low[1] == "users":
        return f"a whole user profile {host!r}"
    if low[1:2] == ["windows"] or low[1:2] == ["program files"]:
        return f"a system tree {host!r}"
    return ""


def validate_config(config: SandboxConfig) -> list[str]:
    """Return a list of containment problems ([] == safe)."""
    problems: list[str] = []
    for mapping in config.mappings():
        host = str(mapping.host).strip()
        if not host:
            problems.append("mapping with empty host folder")
            continue
        if not PureWindowsPath(host).is_absolute():
            problems.append(f"host folder must be absolute: {host!r}")
        reason = _is_overbroad(host)
        if reason:
            problems.append(f"mapping would expose {reason} -- refuse (defeats containment)")
    if config.memory_mb < 1024:
        problems.append(f"memory_mb too low: {config.memory_mb}")
    return problems


def build_xml(config: SandboxConfig, *, strict: bool = True) -> str:
    """Build the .wsb XML string. Raises ContainmentError on unsafe config."""
    problems = validate_config(config)
    if problems and strict:
        raise ContainmentError("; ".join(problems))

    root = ET.Element("Configuration")
    # The containment knobs — every redirection that could be an escape/exfil
    # path is disabled; ProtectedClient hardens the RDP session.
    ET.SubElement(root, "Networking").text = "Default" if config.networking else "Disable"
    ET.SubElement(root, "vGPU").text = "Disable"
    ET.SubElement(root, "ProtectedClient").text = "Enable"
    ET.SubElement(root, "ClipboardRedirection").text = "Disable"
    ET.SubElement(root, "PrinterRedirection").text = "Disable"
    ET.SubElement(root, "AudioInput").text = "Disable"
    ET.SubElement(root, "VideoInput").text = "Disable"
    ET.SubElement(root, "MemoryInMB").text = str(int(config.memory_mb))

    mapped = ET.SubElement(root, "MappedFolders")
    for mapping in config.mappings():
        node = ET.SubElement(mapped, "MappedFolder")
        ET.SubElement(node, "HostFolder").text = mapping.host
        ET.SubElement(node, "SandboxFolder").text = mapping.sandbox
        ET.SubElement(node, "ReadOnly").text = "true" if mapping.read_only else "false"

    logon = ET.SubElement(root, "LogonCommand")
    ET.SubElement(logon, "Command").text = config.logon_command or config.default_logon()

    raw = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    # Drop the <?xml …?> declaration line; .wsb files are plain XML elements.
    lines = [line for line in pretty.splitlines() if line.strip() and not line.startswith("<?xml")]
    return "\n".join(lines) + "\n"


def audit_xml(xml_text: str) -> dict[str, object]:
    """Summarize an existing .wsb's containment posture (for verify_cage)."""
    root = ET.fromstring(xml_text)
    networking = (root.findtext("Networking") or "Default").strip()
    mappings = []
    for node in root.findall("./MappedFolders/MappedFolder"):
        mappings.append(
            {
                "host": (node.findtext("HostFolder") or "").strip(),
                "sandbox": (node.findtext("SandboxFolder") or "").strip(),
                "read_only": (node.findtext("ReadOnly") or "true").strip().lower() == "true",
            }
        )
    overbroad = [m["host"] for m in mappings if _is_overbroad(str(m["host"]))]
    return {
        "networking": networking,
        "network_isolated": networking.lower() == "disable",
        "mapping_count": len(mappings),
        "mappings": mappings,
        "overbroad_mappings": overbroad,
        "contained": networking.lower() == "disable" and not overbroad,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a Windows Sandbox (.wsb) config for the Thomas cage worker.")
    parser.add_argument("--repo", default=str(_REPO_ROOT), help="Host repo folder to map (default: this repo).")
    parser.add_argument("--repo-sandbox", default=r"C:\Thomas", help="Sandbox-side path for the repo.")
    parser.add_argument("--cage-root", default=r"C:\ProgramData\ThomasCage", help="Host cage channel root.")
    parser.add_argument("--cage-root-sandbox", default=r"C:\ThomasCage", help="Sandbox-side cage root.")
    parser.add_argument("--agent", default="thomas-agent", help="Agent id set inside the sandbox.")
    parser.add_argument("--memory-mb", type=int, default=4096)
    parser.add_argument(
        "--enable-network",
        action="store_true",
        help="DANGER: leave networking ON (defeats clone/exfil containment). Default is disabled.",
    )
    parser.add_argument("--out", default="", help="Write the .wsb here (default: print to stdout).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = SandboxConfig(
        repo_host=str(Path(args.repo).resolve()),
        repo_sandbox=args.repo_sandbox,
        cage_root_host=args.cage_root,
        cage_root_sandbox=args.cage_root_sandbox,
        agent=args.agent,
        memory_mb=args.memory_mb,
        networking=bool(args.enable_network),
    )
    try:
        xml_text = build_xml(config)
    except ContainmentError as exc:
        print(f"refusing to generate config: {exc}", file=sys.stderr)
        return 1
    if args.out:
        out = Path(args.out)
        out.write_text(xml_text, encoding="utf-8")
        posture = audit_xml(xml_text)
        print(f"wrote {out}  (network_isolated={posture['network_isolated']}, mappings={posture['mapping_count']})")
        if args.enable_network:
            print("WARNING: networking is ENABLED — this box can clone/push/exfil. Use only when you mean it.")
    else:
        print(xml_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
