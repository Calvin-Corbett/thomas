import unittest
from pathlib import Path

from thomas.core.dep_monitor import DepMonitor


class TestMonitorDiff(unittest.TestCase):
    def test_diff_new_high(self):
        m = DepMonitor(project_root=Path.cwd())
        m._state.last_results = {
            "combined": {
                "vulnerabilities": [{"package": "a", "severity": "high", "cve": "CVE-1", "fix_version": ""}],
                "high": 1,
                "critical": 0,
                "total": 1,
            }
        }  # type: ignore
        current = [
            {"package": "a", "severity": "high", "cve": "CVE-1", "fix_version": ""},
            {"package": "b", "severity": "critical", "cve": "CVE-2", "fix_version": "1.0"},
        ]
        new = m._diff_new_high_critical(current)  # type: ignore
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["package"], "b")


if __name__ == "__main__":
    unittest.main()
