"""Tests for the cage containment layer (PROBLEM 1).

* the generated .wsb is well-formed XML, network-isolated by default, and maps
  ONLY the repo (rw) + cage inbox (rw) + outbox (ro);
* the containment guard refuses mappings that would re-expose the host (drive
  root, the Users tree, a whole profile, system trees);
* enabling networking is reported as NOT contained (an honest opt-out);
* the egress tripwire flags submodule adds, .git writes, out-of-allowlist
  files, and clone/remote commands, and passes a clean diff.
"""

from __future__ import annotations

import pytest
import scripts.cage.build_sandbox_config as sb
import scripts.forge.gates.cage_egress_guard as egress


# --------------------------------------------------------------------------- #
# sandbox config
# --------------------------------------------------------------------------- #
def _cfg(**kw) -> sb.SandboxConfig:
    kw.setdefault("repo_host", r"C:\Users\dev\Thomas")
    return sb.SandboxConfig(**kw)


def test_default_config_is_network_isolated_and_well_formed() -> None:
    xml = sb.build_xml(_cfg())
    posture = sb.audit_xml(xml)
    assert posture["network_isolated"] is True
    assert posture["networking"] == "Disable"
    assert posture["contained"] is True
    assert posture["mapping_count"] == 3


def test_only_repo_and_cage_channels_are_mapped() -> None:
    posture = sb.audit_xml(sb.build_xml(_cfg()))
    by_sandbox = {m["sandbox"]: m for m in posture["mappings"]}
    assert by_sandbox[r"C:\Thomas"]["read_only"] is False  # repo: read-write
    assert by_sandbox[r"C:\ThomasCage\inbox"]["read_only"] is False  # inbox: drop submissions
    assert by_sandbox[r"C:\ThomasCage\outbox"]["read_only"] is True  # outbox: read verdicts only
    assert posture["overbroad_mappings"] == []


@pytest.mark.parametrize(
    "host",
    [r"C:\\", r"C:\Users", r"C:\Users\dev", r"C:\Windows", r"C:\Program Files"],
)
def test_overbroad_mappings_are_refused(host: str) -> None:
    with pytest.raises(sb.ContainmentError):
        sb.build_xml(_cfg(repo_host=host))


def test_relative_host_folder_is_refused() -> None:
    with pytest.raises(sb.ContainmentError):
        sb.build_xml(_cfg(repo_host="relative/path"))


def test_enabling_network_is_reported_uncontained() -> None:
    posture = sb.audit_xml(sb.build_xml(_cfg(networking=True)))
    assert posture["network_isolated"] is False
    assert posture["contained"] is False


def test_logon_command_sets_cage_root_and_agent() -> None:
    xml = sb.build_xml(_cfg(agent="thomas-agent"))
    assert "THOMAS_CAGE_ROOT" in xml
    assert "thomas-agent" in xml
    assert r"C:\ThomasCage" in xml


def test_audit_flags_overbroad_existing_config() -> None:
    # An externally-authored .wsb that maps a whole profile is caught by audit.
    xml = (
        "<Configuration><Networking>Disable</Networking>"
        "<MappedFolders><MappedFolder>"
        r"<HostFolder>C:\Users\dev</HostFolder><SandboxFolder>C:\u</SandboxFolder>"
        "<ReadOnly>false</ReadOnly></MappedFolder></MappedFolders></Configuration>"
    )
    posture = sb.audit_xml(xml)
    assert posture["overbroad_mappings"]
    assert posture["contained"] is False


# --------------------------------------------------------------------------- #
# egress tripwire
# --------------------------------------------------------------------------- #
def test_clean_diff_passes() -> None:
    diff = "diff --git a/thomas/x.py b/thomas/x.py\n+++ b/thomas/x.py\n+print('hi')\n"
    result = egress.evaluate(patch_file="", repo=None, allow_roots=None)
    # call scan_diff directly to avoid touching the real staged tree
    findings = egress.scan_diff(diff)
    assert findings["block"] == []
    assert findings["warn"] == []
    assert result is not None


def test_submodule_add_is_blocked() -> None:
    diff = (
        "diff --git a/.gitmodules b/.gitmodules\n"
        "+++ b/.gitmodules\n"
        '+[submodule "evil"]\n'
        "+\turl = https://example.com/other-repo.git\n"
    )
    findings = egress.scan_diff(diff)
    assert any(f["type"] == "submodule_add" for f in findings["block"])


def test_git_internal_write_is_blocked() -> None:
    diff = "diff --git a/.git/hooks/pre-commit b/.git/hooks/pre-commit\n+++ b/.git/hooks/pre-commit\n+exit 0\n"
    findings = egress.scan_diff(diff)
    assert any(f["type"] == "git_internal_write" for f in findings["block"])


def test_out_of_allowlist_is_blocked() -> None:
    diff = "+++ b/thomas/secret_exfil.py\n+data = 1\n"
    findings = egress.scan_diff(diff, allow_roots=["scripts/cage"])
    assert any(f["type"] == "out_of_allowlist" for f in findings["block"])
    # within the allowlist -> clean
    diff_ok = "+++ b/scripts/cage/new_tool.py\n+data = 1\n"
    assert egress.scan_diff(diff_ok, allow_roots=["scripts/cage"])["block"] == []


def test_clone_command_is_warned_not_blocked() -> None:
    diff = "+++ b/setup.sh\n+git clone https://example.com/repo.git /tmp/x\n"
    findings = egress.scan_diff(diff)
    assert findings["block"] == []
    assert any(f["type"] == "egress_command" for f in findings["warn"])


def test_strict_fails_on_warnings(tmp_path) -> None:
    patch = tmp_path / "p.diff"
    patch.write_text("+++ b/setup.sh\n+git remote add evil https://example.com/r.git\n", encoding="utf-8")
    lenient = egress.evaluate(patch_file=str(patch), strict=False)
    strict = egress.evaluate(patch_file=str(patch), strict=True)
    assert lenient["ok"] is True
    assert strict["ok"] is False
