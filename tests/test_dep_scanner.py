import os
import unittest
from pathlib import Path

import pytest
from thomas.tools import dep_scanner
from thomas.tools import dep_scanner_python


class TestPolicyFilters(unittest.TestCase):
    def test_min_severity_filter(self):
        cfg = {"min_severity": "high"}
        vulns = [
            dep_scanner.VulnRecord("a","1.0","low","CVE-1","", "python"),
            dep_scanner.VulnRecord("b","1.0","high","CVE-2","", "python"),
        ]
        out = dep_scanner._apply_policy_filters(cfg, vulns)  # type: ignore
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].package, "b")

    def test_ignore_packages(self):
        cfg = {"ignore_packages": ["a"]}
        vulns = [
            dep_scanner.VulnRecord("a","1.0","high","CVE-1","", "python"),
            dep_scanner.VulnRecord("b","1.0","high","CVE-2","", "python"),
        ]
        out = dep_scanner._apply_policy_filters(cfg, vulns)  # type: ignore
        self.assertEqual([v.package for v in out], ["b"])


class TestSortingAndDedup(unittest.TestCase):
    def test_dedup_keeps_worst(self):
        vulns = [
            dep_scanner.VulnRecord("pkg","1","low","CVE-1","", "python"),
            dep_scanner.VulnRecord("pkg","1","high","CVE-1","", "python"),
        ]
        out = dep_scanner._dedup(vulns)  # type: ignore
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, "high")


def test_python_scan_accepts_dict_shaped_pip_audit_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("pygments==2.19.2\n", encoding="utf-8")

    monkeypatch.setattr(dep_scanner_python, "_ensure_pip_audit_available", lambda: None)
    monkeypatch.setattr(
        dep_scanner_python,
        "_run_pip_audit_json",
        lambda args, cwd: {  # noqa: ARG005
            "dependencies": [
                {
                    "name": "pygments",
                    "version": "2.19.2",
                    "vulns": [
                        {
                            "id": "PYSEC-2026-1",
                            "aliases": ["CVE-2026-4539"],
                            "fix_versions": [],
                        }
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(dep_scanner_python, "_osv_get_vuln", lambda cfg, vuln_id: None)  # noqa: ARG005

    vulns = dep_scanner_python._python_scan({}, reqs)

    assert len(vulns) == 1
    assert vulns[0].package == "pygments"
    assert vulns[0].version == "2.19.2"
    assert vulns[0].cve == "CVE-2026-4539"


if __name__ == "__main__":
    unittest.main()
