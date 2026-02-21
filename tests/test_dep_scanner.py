import os
import unittest
from thomas.tools import dep_scanner


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


if __name__ == "__main__":
    unittest.main()
