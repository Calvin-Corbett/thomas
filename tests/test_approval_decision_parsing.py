import unittest

from thomas.server.guardrails_api import _parse_decision as parse_guardrails_decision
from thomas.server.routes.mission_approvals import _parse_decision as parse_mission_decision


class TestApprovalDecisionParsing(unittest.TestCase):
    def test_mission_approval_parses_approve_alias(self):
        payload = {"decision": "approve"}
        self.assertTrue(parse_mission_decision(payload, default=False))

    def test_mission_approval_parses_denial_alias(self):
        payload = {"approve": "deny"}
        self.assertFalse(parse_mission_decision(payload, default=True))

    def test_mission_approval_defaults_when_missing(self):
        payload = {"other": "value"}
        self.assertIsNone(parse_mission_decision(payload, default=None))

    def test_guardrails_decision_parses_numeric_aliases(self):
        self.assertTrue(parse_guardrails_decision({"approved": 1}, default=None))
        self.assertFalse(parse_guardrails_decision({"approved": 0}, default=None))

    def test_guardrails_decision_parses_text_aliases(self):
        self.assertTrue(parse_guardrails_decision({"decision": "yes"}, default=None))
        self.assertFalse(parse_guardrails_decision({"decision": "failed"}, default=None))


if __name__ == "__main__":
    unittest.main()
