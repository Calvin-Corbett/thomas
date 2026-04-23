import os
import tempfile
import unittest

from thomas.marketplace.autonomy.policy import AutonomyPolicy


class TestAutonomyPolicyNoHuman(unittest.TestCase):
    ENV_KEYS = ("THOMAS_AUTONOMY_NO_HUMAN_MODE", "THOMAS_NO_HUMAN_MODE", "THOMAS_GUARDRAILS_NO_HUMAN_MODE")

    def setUp(self):
        self._previous_env = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k in self.ENV_KEYS:
            previous = self._previous_env.get(k)
            if previous is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = previous

    def test_env_no_human_mode_overrides_policy(self):
        os.environ["THOMAS_AUTONOMY_NO_HUMAN_MODE"] = "deny"
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = os.path.join(tmpdir, "policy.toml")
            with open(policy_path, "w", encoding="utf-8") as f:
                f.write("")
            policy = AutonomyPolicy.load(policy_path)
        self.assertEqual(policy.no_human_mode, "deny")

    def test_invalid_no_human_mode_defaults_to_human(self):
        os.environ["THOMAS_NO_HUMAN_MODE"] = "nonsense"
        policy = AutonomyPolicy.load("")
        self.assertEqual(policy.no_human_mode, "human")

    def test_decision_converts_approve_to_allow_in_no_human_mode_allow(self):
        policy = AutonomyPolicy()
        policy.policy["api"]["no_human_mode"] = "allow"
        decision = policy.decision_for_job("reminder", "medium")
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_approval)

    def test_decision_converts_approve_to_deny_in_no_human_mode_deny(self):
        policy = AutonomyPolicy()
        policy.policy["api"]["no_human_mode"] = "deny"
        decision = policy.decision_for_job("reminder", "medium")
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_approval)


if __name__ == "__main__":
    unittest.main()
