"""Tests for thomas.human_loop module."""
import unittest

from thomas.human_loop.types import (
    HumanInputMode, HumanRequest, HumanResponse,
    EscalationLevel, HumanLoopConfig, RequestType,
)
from thomas.human_loop.handler import HumanInputHandler
from thomas.human_loop.proxy import HumanProxy
from thomas.human_loop.escalation import EscalationManager
from thomas.human_loop.approval import ApprovalGate, GateType


class TestTypes(unittest.TestCase):
    def test_human_request(self):
        req = HumanRequest(prompt="Approve this?", request_type=RequestType.APPROVAL)
        self.assertTrue(len(req.id) > 0)
        self.assertEqual(req.request_type, RequestType.APPROVAL)

    def test_human_response(self):
        resp = HumanResponse(request_id="abc", value="yes")
        self.assertEqual(resp.value, "yes")
        self.assertFalse(resp.timed_out)

    def test_config_defaults(self):
        config = HumanLoopConfig()
        self.assertEqual(config.mode, HumanInputMode.TERMINATE)
        self.assertEqual(config.timeout_seconds, 300)


class TestHandler(unittest.TestCase):
    def test_request_input(self):
        handler = HumanInputHandler(callback=lambda p: "user response")
        response = handler.request_input("What is your name?")
        self.assertEqual(response.value, "user response")
        self.assertFalse(response.timed_out)

    def test_request_approval(self):
        handler = HumanInputHandler(callback=lambda p: "yes")
        approved = handler.request_approval("Delete files?")
        self.assertTrue(approved)

    def test_request_approval_denied(self):
        handler = HumanInputHandler(callback=lambda p: "no")
        approved = handler.request_approval("Delete files?")
        self.assertFalse(approved)

    def test_request_choice(self):
        handler = HumanInputHandler(callback=lambda p: "Option A")
        choice = handler.request_choice("Pick one:", ["Option A", "Option B"])
        self.assertEqual(choice, "Option A")

    def test_history(self):
        handler = HumanInputHandler(callback=lambda p: "ok")
        handler.request_input("Q1")
        handler.request_input("Q2")
        history = handler.get_history()
        self.assertEqual(len(history), 2)


class TestProxy(unittest.TestCase):
    def test_never_mode(self):
        config = HumanLoopConfig(mode=HumanInputMode.NEVER)
        proxy = HumanProxy(config=config)
        proxy.auto_reply = "auto response"
        response = proxy.generate_response([{"role": "assistant", "content": "Hello"}])
        self.assertEqual(response, "auto response")

    def test_always_mode(self):
        config = HumanLoopConfig(mode=HumanInputMode.ALWAYS)
        handler = HumanInputHandler(callback=lambda p: "human says hi")
        proxy = HumanProxy(config=config, handler=handler)
        response = proxy.generate_response([{"role": "assistant", "content": "Hello"}])
        self.assertEqual(response, "human says hi")

    def test_terminate_mode_no_keyword(self):
        config = HumanLoopConfig(mode=HumanInputMode.TERMINATE)
        proxy = HumanProxy(config=config)
        proxy.auto_reply = "auto"
        response = proxy.generate_response([{"role": "assistant", "content": "Hello there"}])
        self.assertEqual(response, "auto")

    def test_terminate_mode_with_keyword(self):
        config = HumanLoopConfig(mode=HumanInputMode.TERMINATE)
        handler = HumanInputHandler(callback=lambda p: "confirmed")
        proxy = HumanProxy(config=config, handler=handler)
        proxy.auto_reply = "auto"
        response = proxy.generate_response([{"role": "assistant", "content": "Task is TERMINATE"}])
        self.assertEqual(response, "confirmed")

    def test_record_feedback(self):
        config = HumanLoopConfig(mode=HumanInputMode.NEVER)
        proxy = HumanProxy(config=config)
        proxy.record_feedback(0.9, "good job")
        stats = proxy.get_feedback_stats()
        self.assertEqual(stats["count"], 1)


class TestEscalation(unittest.TestCase):
    def test_register_handler(self):
        mgr = EscalationManager()
        mgr.register_handler(EscalationLevel.CRITICAL, lambda msg, ctx: HumanResponse(request_id="x", value="handled"))
        self.assertIn(EscalationLevel.CRITICAL, mgr._handlers)

    def test_escalate_info(self):
        mgr = EscalationManager()
        result = mgr.escalate(EscalationLevel.INFO, "Just FYI")
        self.assertIsNone(result)

    def test_escalate_critical(self):
        mgr = EscalationManager()
        mgr.register_handler(EscalationLevel.CRITICAL, lambda msg, ctx: HumanResponse(request_id="x", value="fixed"))
        result = mgr.escalate(EscalationLevel.CRITICAL, "Server down!")
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "fixed")

    def test_history(self):
        mgr = EscalationManager()
        mgr.escalate(EscalationLevel.INFO, "test")
        history = mgr.get_history()
        self.assertEqual(len(history), 1)

    def test_stats(self):
        mgr = EscalationManager()
        mgr.escalate(EscalationLevel.INFO, "info1")
        mgr.escalate(EscalationLevel.WARNING, "warn1")
        stats = mgr.get_stats()
        self.assertEqual(stats["total"], 2)


class TestApprovalGate(unittest.TestCase):
    def test_whitelist(self):
        gate = ApprovalGate()
        gate.add_to_whitelist("safe_action")
        result = gate.check_gate("safe_action", GateType.SENSITIVE_ACTION)
        self.assertTrue(result)

    def test_blacklist(self):
        gate = ApprovalGate()
        gate.add_to_blacklist("dangerous_action")
        result = gate.check_gate("dangerous_action", GateType.SENSITIVE_ACTION)
        self.assertFalse(result)

    def test_handler_approval(self):
        handler = HumanInputHandler(callback=lambda p: "yes")
        gate = ApprovalGate(handler=handler)
        result = gate.check_gate("unknown_action", GateType.SENSITIVE_ACTION)
        self.assertTrue(result)

    def test_handler_denial(self):
        handler = HumanInputHandler(callback=lambda p: "no")
        gate = ApprovalGate(handler=handler)
        result = gate.check_gate("unknown_action", GateType.SENSITIVE_ACTION)
        self.assertFalse(result)

    def test_audit_log(self):
        gate = ApprovalGate()
        gate.add_to_whitelist("action1")
        gate.check_gate("action1", GateType.SENSITIVE_ACTION)
        log = gate.get_audit_log()
        self.assertEqual(len(log), 2)


if __name__ == "__main__":
    unittest.main()
