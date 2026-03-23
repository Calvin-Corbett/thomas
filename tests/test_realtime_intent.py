import unittest

from thomas.marketplace.realtime.intent import next_action_suggestions, predict_intent


class TestIntent(unittest.TestCase):
    def test_schedule_intent(self):
        i = predict_intent("remind me tomorrow at 8")
        self.assertEqual(i.name, "schedule_job")
        s = next_action_suggestions(i)
        self.assertTrue(any(x["action"] == "open_scheduler" for x in s))

    def test_web_search(self):
        i = predict_intent("search the web for best stt models")
        self.assertEqual(i.name, "web_search")
