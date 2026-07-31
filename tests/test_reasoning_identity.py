"""Guard tests for Thomas's canonical governed-operator identity."""

import unittest

from thomas.core.autonomy import autonomy_spec, chat_delegation_directive
from thomas.marketplace.specialists.reasoning import (
    THOMAS_CHATBOT_SYSTEM_PROMPT,
    THOMAS_OPERATOR_SYSTEM_PROMPT,
)


class TestThomasIdentity(unittest.TestCase):
    def test_declares_persistent_governed_operator(self):
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("your entire job", low)
        self.assertIn("persistent, locally governed software operator", low)
        self.assertIn("replaceable engine", low)
        self.assertIn("one consistent voice", low)

    def test_permits_only_bounded_direct_action(self):
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("bounded reversible actions", low)
        self.assertIn("narrow, audited product surface", low)
        self.assertIn("never bypass guardrails or approval", low)

    def test_allows_read_to_inform_and_report(self):
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("read", low)
        # He reads state and reports back ("how's the evolve loop going?").
        self.assertIn("evolve loop", low)

    def test_assistant_framing(self):
        self.assertIn("assistant", THOMAS_OPERATOR_SYSTEM_PROMPT.lower())

    def test_work_is_handed_to_task_manager(self):
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("task manager", low)

    def test_autonomy_preserves_user_sovereignty(self):
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("autonomy and permission", low)
        self.assertIn("never erase user sovereignty", low)

    def test_forbids_fake_completion(self):
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("never claim", low)

    def test_forbids_claiming_work_started_and_offers_instead(self):
        # The chat agent must not assert work began ("on it" / "I've handed that
        # off") when it never called send_task — that's a false claim. Guards the
        # live "logic doesn't add up" dishonesty (positive framing, 2026-06-26).
        #
        # This asserted one literal sentence, "never tell the user you handed
        # something off unless you actually called the tool", and went red on
        # 2026-07-20 when 24ffc614 reworded it to "never tell the user you're
        # handling something...". The rule was never weakened; the VOICE changed
        # on purpose — that commit removed "handed off to <worker>" everywhere so
        # Thomas stops naming a task manager to the user.
        #
        # It stayed red for eleven days, and the obvious "fix" would have been to
        # paste the old sentence back, reintroducing exactly the phrasing Calvin
        # had deliberately removed. So the rule is matched structurally instead:
        # a prohibition on telling the user anything that is conditional on the
        # tool actually having been called. Any voice satisfies that; deleting
        # the rule does not.
        low = THOMAS_OPERATOR_SYSTEM_PROMPT.lower()
        self.assertIn("without calling send_task does nothing", low)
        self.assertIn("false claim", low)
        self.assertRegex(
            low,
            r"never tell the user[^.]{0,80}unless you actually called the tool",
            "the prompt no longer forbids telling the user work is under way "
            "without having called send_task. Reword it freely, but the rule "
            "must survive: the claim has to be conditional on the tool call.",
        )

    def test_legacy_prompt_name_is_one_compatibility_alias(self):
        self.assertIs(THOMAS_CHATBOT_SYSTEM_PROMPT, THOMAS_OPERATOR_SYSTEM_PROMPT)

    def test_autonomy_directives_govern_action_without_forking_identity(self):
        self.assertIn("read-only observation", chat_delegation_directive(1))
        self.assertIn("Before mutating", chat_delegation_directive(2))
        self.assertIn("use operate directly", chat_delegation_directive(3))
        self.assertIn("Use operate", chat_delegation_directive(4))
        self.assertIn("no mutation or delegation", autonomy_spec(1).summary)


if __name__ == "__main__":
    unittest.main()
