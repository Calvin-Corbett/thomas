"""Tests for thomas.sandbox module."""
import unittest

from thomas.sandbox.types import ExecutionResult, SandboxConfig, SandboxType, CodeLanguage
from thomas.sandbox.executor import SubprocessExecutor
from thomas.sandbox.restricted import RestrictedExecutor, DangerousCodeError
from thomas.sandbox.manager import SandboxManager


class TestSubprocessExecutor(unittest.TestCase):
    def setUp(self):
        self.executor = SubprocessExecutor()

    def test_execute_python_print(self):
        result = self.executor.execute("print('hello world')", CodeLanguage.PYTHON)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello world", result.stdout)
        self.assertFalse(result.timed_out)

    def test_execute_python_math(self):
        result = self.executor.execute("print(2 + 3)", CodeLanguage.PYTHON)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("5", result.stdout)

    def test_execute_bash(self):
        result = self.executor.execute("echo 'hi from bash'", CodeLanguage.BASH)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hi from bash", result.stdout)

    def test_timeout(self):
        config = SandboxConfig(timeout_seconds=1)
        result = self.executor.execute(
            "import time; time.sleep(10); print('done')",
            CodeLanguage.PYTHON,
            config,
        )
        self.assertTrue(result.timed_out)

    def test_syntax_error(self):
        result = self.executor.execute("def broken(:", CodeLanguage.PYTHON)
        self.assertNotEqual(result.exit_code, 0)

    def test_duration_tracked(self):
        result = self.executor.execute("print(1)", CodeLanguage.PYTHON)
        self.assertGreaterEqual(result.duration_ms, 0)


class TestRestrictedExecutor(unittest.TestCase):
    def setUp(self):
        self.executor = RestrictedExecutor()

    def test_safe_code(self):
        result = self.executor.execute_restricted("x = 2 + 3\nprint(x)")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("5", result.stdout)

    def test_block_os_import(self):
        result = self.executor.execute_restricted("import os\nos.system('ls')")
        self.assertNotEqual(result.exit_code, 0)

    def test_block_subprocess(self):
        result = self.executor.execute_restricted("import subprocess")
        self.assertNotEqual(result.exit_code, 0)

    def test_block_eval(self):
        result = self.executor.execute_restricted("eval('1+1')")
        self.assertNotEqual(result.exit_code, 0)

    def test_allow_math(self):
        config = SandboxConfig()
        result = self.executor.execute_restricted("import math\nprint(math.sqrt(16))", config)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("4.0", result.stdout)

    def test_allow_json(self):
        result = self.executor.execute_restricted("import json\nprint(json.dumps({'a': 1}))")
        self.assertEqual(result.exit_code, 0)

    def test_safe_builtins(self):
        result = self.executor.execute_restricted("print(len([1, 2, 3]))")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("3", result.stdout)


class TestSandboxManager(unittest.TestCase):
    def test_execute(self):
        mgr = SandboxManager()
        result = mgr.execute("print('managed')", CodeLanguage.PYTHON)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("managed", result.stdout)

    def test_stats(self):
        mgr = SandboxManager()
        mgr.execute("print(1)", CodeLanguage.PYTHON)
        stats = mgr.stats()
        self.assertEqual(stats["executions"], 1)

    def test_get_available(self):
        mgr = SandboxManager()
        avail = mgr.get_available_sandboxes()
        self.assertIn(SandboxType.SUBPROCESS, avail)
        self.assertIn(SandboxType.RESTRICTED, avail)

    def test_validate_code(self):
        mgr = SandboxManager()
        warnings = mgr.validate_code("import os\nos.system('rm -rf /')", CodeLanguage.PYTHON)
        self.assertIsInstance(warnings, list)


if __name__ == "__main__":
    unittest.main()
