import unittest

from thomas.marketplace.realtime.stt_dedupe import STTDedupeWindow


class TestSTTDedupe(unittest.TestCase):
    def test_duplicate_suppression(self):
        d = STTDedupeWindow(window_ms=4000)
        a = d.decide("turn on the lights", is_final=False, confidence=0.4, ts_ms=1000)
        self.assertTrue(a.accept)
        b = d.decide("turn on the lights", is_final=False, confidence=0.4, ts_ms=1200)
        self.assertFalse(b.accept)

    def test_final_promotes_interim(self):
        d = STTDedupeWindow(window_ms=4000)
        a = d.decide("hello world", is_final=False, confidence=0.2, ts_ms=1000)
        self.assertTrue(a.accept)
        b = d.decide("hello world", is_final=True, confidence=0.8, ts_ms=1500)
        self.assertTrue(b.accept)
        self.assertEqual(b.reason, "final_promotes_interim")

    def test_substring_suppression(self):
        d = STTDedupeWindow(window_ms=4000)
        a = d.decide("turn on the", is_final=False, confidence=0.2, ts_ms=1000)
        self.assertTrue(a.accept)
        b = d.decide("turn on the lights", is_final=False, confidence=0.2, ts_ms=1200)
        self.assertTrue(b.accept)
        c = d.decide("turn on the", is_final=False, confidence=0.2, ts_ms=1400)
        self.assertFalse(c.accept)
