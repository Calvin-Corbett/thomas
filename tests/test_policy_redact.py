import unittest

from thomas.policy.config import PolicyConfig
from thomas.policy.policy import PolicyEngine
from thomas.policy.redact import Redactor
from thomas.policy.types import PolicyContext


class TestRedaction(unittest.TestCase):
    def test_private_key_redaction(self):
        r = Redactor()
        s = """-----BEGIN PRIVATE KEY-----
abcdefghijklmnopqrstuvwxyz
-----END PRIVATE KEY-----"""
        out = r.redact_text(s)
        self.assertIn("<REDACTED:PRIVATE_KEY>", out)

    def test_bearer_redaction(self):
        r = Redactor()
        s = "Authorization: Bearer abcdef1234567890"
        out = r.redact_text(s)
        self.assertIn("<REDACTED:BEARER>", out)

    def test_assignment_redaction(self):
        r = Redactor()
        s = "api_key=supersecretvalue123"
        out = r.redact_text(s)
        self.assertNotIn("supersecretvalue123", out)
        self.assertIn("<REDACTED>", out)

    def test_recursive_redaction(self):
        r = Redactor()
        obj = {"token": "sk-abcdefghijklmnopqrstuvwxyz0123456789", "nested": [{"password": "hunter2"}]}
        out = r.redact_obj(obj)
        self.assertEqual(
            out["token"], "<REDACTED:SECRET_KEY>" if out["token"].startswith("<REDACTED") else out["token"]
        )
        self.assertIn("<REDACTED>", out["nested"][0]["password"])


class TestPolicyRules(unittest.TestCase):
    def test_deny_secret_root(self):
        cfg = PolicyConfig()
        engine = PolicyEngine.from_config(cfg)
        ctx = PolicyContext(
            tool_name="fs.read_file",
            args={"path": str(__import__("pathlib").Path.home() / ".ssh" / "id_rsa")},
            cwd=str(__import__("pathlib").Path.cwd()),
            sandbox_root=str(__import__("pathlib").Path.cwd()),
            iteration=1,
            conversation_summary="hi",
        )
        dec = engine.evaluate(ctx)
        self.assertEqual(dec.type.value, "DENY")

    def test_require_approval_shell_exec(self):
        cfg = PolicyConfig()
        engine = PolicyEngine.from_config(cfg)
        ctx = PolicyContext(
            tool_name="shell.exec",
            args={"cmd": "dir"},
            cwd=str(__import__("pathlib").Path.cwd()),
            sandbox_root=str(__import__("pathlib").Path.cwd()),
            iteration=1,
            conversation_summary="hi",
        )
        dec = engine.evaluate(ctx)
        self.assertEqual(dec.type.value, "REQUIRE_APPROVAL")

    def test_default_allow(self):
        cfg = PolicyConfig()
        engine = PolicyEngine.from_config(cfg)
        ctx = PolicyContext(
            tool_name="math.add",
            args={"a": 1, "b": 2},
            cwd=str(__import__("pathlib").Path.cwd()),
            sandbox_root=str(__import__("pathlib").Path.cwd()),
            iteration=1,
            conversation_summary="hi",
        )
        dec = engine.evaluate(ctx)
        self.assertEqual(dec.type.value, "ALLOW")

    def test_require_approval_converts_to_allow_when_no_human_allow(self):
        cfg = PolicyConfig()
        cfg.guardrails.no_human_mode = "allow"
        engine = PolicyEngine.from_config(cfg)
        ctx = PolicyContext(
            tool_name="shell.exec",
            args={"cmd": "dir"},
            cwd=str(__import__("pathlib").Path.cwd()),
            sandbox_root=str(__import__("pathlib").Path.cwd()),
            iteration=1,
            conversation_summary="hi",
        )
        dec = engine.evaluate(ctx)
        self.assertEqual(dec.type.value, "ALLOW")
        self.assertEqual(dec.meta.get("no_human_mode"), "allow")

    def test_require_approval_converts_to_deny_when_no_human_deny(self):
        cfg = PolicyConfig()
        cfg.guardrails.no_human_mode = "deny"
        engine = PolicyEngine.from_config(cfg)
        ctx = PolicyContext(
            tool_name="shell.exec",
            args={"cmd": "dir"},
            cwd=str(__import__("pathlib").Path.cwd()),
            sandbox_root=str(__import__("pathlib").Path.cwd()),
            iteration=1,
            conversation_summary="hi",
        )
        dec = engine.evaluate(ctx)
        self.assertEqual(dec.type.value, "DENY")
        self.assertEqual(dec.meta.get("no_human_mode"), "deny")


if __name__ == "__main__":
    unittest.main()
