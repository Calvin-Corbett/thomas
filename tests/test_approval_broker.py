import asyncio
import unittest

from thomas.agent.approval import ApprovalBroker

class TestApprovalBroker(unittest.TestCase):
    def test_resolve(self):
        async def main():
            b = ApprovalBroker()
            task = asyncio.create_task(b.require(
                run_id="r1",
                tool_call_id="t1",
                session_id="s1",
                tool_name="shell.exec",
                args_preview={},
                reason="need approval",
                timeout_s=5,
            ))
            await asyncio.sleep(0.05)
            ok = await b.resolve(run_id="r1", tool_call_id="t1", approved=True)
            self.assertTrue(ok)
            res = await task
            self.assertTrue(res)
        asyncio.run(main())

    def test_timeout_default_deny(self):
        async def main():
            b = ApprovalBroker()
            res = await b.require(
                run_id="r1",
                tool_call_id="t2",
                session_id="s1",
                tool_name="shell.exec",
                args_preview={},
                reason="need approval",
                timeout_s=0.1,
            )
            self.assertFalse(res)
        asyncio.run(main())

    def test_session_allowlist(self):
        async def main():
            b = ApprovalBroker()
            b.allow_tool_for_session("s1", "shell.exec")
            res = await b.require(
                run_id="r1",
                tool_call_id="t3",
                session_id="s1",
                tool_name="shell.exec",
                args_preview={},
                reason="need approval",
                timeout_s=1,
            )
            self.assertTrue(res)
        asyncio.run(main())

if __name__ == "__main__":
    unittest.main()
