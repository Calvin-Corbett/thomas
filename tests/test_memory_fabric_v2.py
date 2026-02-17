import json
import shutil
import tempfile
import unittest

from thomas.memory.v2.fabric import MemoryFabricV2


class TestMemoryFabricV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mf2_")
        self.fabric = MemoryFabricV2(root_path=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ingest_and_retrieve_includes_profile(self):
        thread_id = "t1"
        self.fabric.ingest_episode(thread_id, "user", "My name is Calvin", ts_ms=1700000000000)
        self.fabric.ingest_episode(thread_id, "user", "My son's name is Hudson", ts_ms=1700000001000)
        self.fabric.ingest_episode(thread_id, "user", "I run Freedom Transit trucking company", ts_ms=1700000002000)

        res = self.fabric.retrieve(thread_id, "what is my son's name", budget_tokens=800)
        self.assertTrue(res.pack_text)
        self.assertIn("Hudson", res.pack_text)

    def test_contradiction_detection_on_profile_hint_change(self):
        thread_id = "t2"
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "Calvin", "confidence": 0.9}],
            source_episode_id=None,
            ts_ms=1700000000000,
        )
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "Kevin", "confidence": 0.9}],
            source_episode_id=None,
            ts_ms=1700000001000,
        )
        contras = self.fabric.list_contradictions(only_open=True, limit=10)
        self.assertTrue(any("profile_hint_value_change" in c["reason"] for c in contras))

    def test_fact_contradiction_detection(self):
        thread_id = "t3"
        self.fabric.upsert_fact(thread_id=thread_id, subject="Hudson", predicate="age_years", obj="2", confidence=0.8)
        self.fabric.upsert_fact(thread_id=thread_id, subject="Hudson", predicate="age_years", obj="7", confidence=0.8)
        contras = self.fabric.list_contradictions(only_open=True, limit=10)
        self.assertTrue(
            any("numeric_mismatch" in c["reason"] or "polarity_conflict" in c["reason"] for c in contras)
        )

    def test_thread_settings_pins_only(self):
        thread_id = "t4"
        self.fabric.ingest_episode(thread_id, "user", "this should not appear", ts_ms=1700000000000)
        self.fabric.add_pin(kind="note", ref_id="remember_me", thread_id=thread_id, note="pinned note")
        self.fabric.update_thread_settings(thread_id, {"pins_only": True})
        res = self.fabric.retrieve(thread_id, "anything", budget_tokens=400)
        self.assertIn("pinned note", res.pack_text)
        self.assertNotIn("this should not appear", res.pack_text)

    def test_trace_contains_score_breakdown(self):
        thread_id = "t5"
        self.fabric.ingest_episode(thread_id, "user", "My name is Calvin", ts_ms=1700000000000)
        res = self.fabric.retrieve(thread_id, "what is my name", budget_tokens=500)
        trace = self.fabric.get_trace(res.trace_id)
        self.assertIsNotNone(trace)
        payload = json.loads(trace["results_json"])
        self.assertTrue(len(payload) > 0)
        has = any(isinstance(it.get("meta", {}).get("score_components"), dict) for it in payload)
        self.assertTrue(has)

    def test_auto_compaction_triggers_pack(self):
        thread_id = "t6"
        self.fabric.update_thread_settings(
            thread_id,
            {
                "auto_compact_enabled": True,
                "auto_compact_episode_threshold": 3,
                "auto_compact_min_interval_hours": 0,
                "auto_optimize_enabled": False,
            },
        )
        self.fabric.ingest_episode(thread_id, "user", "a", ts_ms=1700000000000)
        self.fabric.ingest_episode(thread_id, "user", "b", ts_ms=1700000001000)
        self.fabric.ingest_episode(thread_id, "user", "c", ts_ms=1700000002000)
        row = self.fabric.db.execute(
            "SELECT COUNT(*) c FROM packs WHERE scope='thread' AND thread_id=?",
            (thread_id,),
        ).fetchone()
        self.assertGreaterEqual(int(row["c"]), 1)


if __name__ == "__main__":
    unittest.main()

