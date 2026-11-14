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
        self.fabric.ingest_episode(thread_id, "user", "My name is the product owner", ts_ms=1700000000000)
        self.fabric.ingest_episode(thread_id, "user", "My son's name is Hudson", ts_ms=1700000001000)
        self.fabric.ingest_episode(thread_id, "user", "I run Freedom Transit trucking company", ts_ms=1700000002000)

        res = self.fabric.retrieve(thread_id, "what is my son's name", budget_tokens=800)
        self.assertTrue(res.pack_text)
        self.assertIn("Hudson", res.pack_text)

    def test_memory_persists_after_reopening_fabric(self):
        thread_id = "t1_restart"
        self.fabric.ingest_episode(
            thread_id,
            "user",
            "Remember that the desktop QA color is cobalt blue",
            ts_ms=1700000000000,
        )
        self.fabric.add_pin(kind="note", ref_id="qa_color", thread_id=thread_id, note="desktop QA color: cobalt blue")
        self.fabric.db.close()

        reopened = MemoryFabricV2(root_path=self.tmp)
        try:
            res = reopened.retrieve(thread_id, "desktop QA color", budget_tokens=500)
            self.assertIn("cobalt blue", res.pack_text.lower())
        finally:
            reopened.db.close()

    def test_contradiction_detection_on_profile_hint_change(self):
        thread_id = "t2"
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "the product owner", "confidence": 0.9}],
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

    def test_forget_profile_hint_removes_retrievable_value_and_caches(self):
        value = "PARITY-FORGET-UNIQUE-401"
        self.fabric.upsert_profile_hints(
            thread_id=None,
            hints=[{"key": "user.preference", "value": value, "confidence": 1.0}],
            source_episode_id=None,
        )
        self.fabric.pin_profile_hint("user.preference", pinned=True)
        self.fabric.ingest_episode("forget-thread", "assistant", value)
        self.fabric.upsert_fact(
            thread_id=None,
            subject="user",
            predicate="preference",
            obj=value,
            confidence=1.0,
        )
        self.fabric.add_pin(kind="note", ref_id="preference", note=value)
        self.fabric.retrieve("forget-thread", "What is my preference?", budget_tokens=500)

        result = self.fabric.forget_profile_hint("user.preference")

        self.assertTrue(result["forgotten"])
        for table, column in (
            ("profile_hints", "value"),
            ("episodes", "content"),
            ("semantic_facts", "obj"),
            ("pins", "note"),
            ("packs", "text"),
            ("retrieval_traces", "results_json"),
        ):
            count = self.fabric.db.execute(
                f'SELECT COUNT(*) AS c FROM "{table}" WHERE "{column}" LIKE ?',
                (f"%{value}%",),
            ).fetchone()["c"]
            self.assertEqual(int(count), 0, table)

    def test_forget_thread_removes_thread_rows_and_promoted_derivatives(self):
        thread = "private-thread"
        other = "other-thread"
        episode = self.fabric.ingest_episode(thread, "user", "PRIVATE-THREAD-MARKER-771")
        self.fabric.ingest_episode(other, "user", "OTHER-THREAD-MARKER-882")
        self.fabric.upsert_fact(
            "owner",
            "private_marker",
            "PRIVATE-THREAD-MARKER-771",
            thread_id=thread,
            provenance_episode_id=int(episode["id"]),
        )
        self.fabric.upsert_profile_hints(
            {"private.marker": ("PRIVATE-THREAD-MARKER-771", 1.0)},
            source_episode_id=int(episode["id"]),
        )
        self.fabric.add_pin("episode", str(episode["id"]), thread_id=thread, note="private")
        self.fabric.retrieve(thread, "private marker", budget_tokens=400)

        result = self.fabric.forget_thread(thread)

        self.assertTrue(result["forgotten"])
        self.assertEqual(
            self.fabric.db.execute("SELECT COUNT(*) c FROM episodes WHERE thread_id=?", (thread,)).fetchone()["c"],
            0,
        )
        self.assertEqual(
            self.fabric.db.execute("SELECT COUNT(*) c FROM semantic_facts WHERE thread_id=?", (thread,)).fetchone()[
                "c"
            ],
            0,
        )
        self.assertEqual(
            self.fabric.db.execute("SELECT COUNT(*) c FROM pins WHERE thread_id=?", (thread,)).fetchone()["c"],
            0,
        )
        self.assertEqual(
            self.fabric.db.execute("SELECT COUNT(*) c FROM retrieval_traces WHERE thread_id=?", (thread,)).fetchone()[
                "c"
            ],
            0,
        )
        self.assertEqual(
            self.fabric.db.execute("SELECT COUNT(*) c FROM profile_hints WHERE key='private.marker'").fetchone()["c"],
            0,
        )
        self.assertEqual(
            self.fabric.db.execute("SELECT COUNT(*) c FROM episodes WHERE thread_id=?", (other,)).fetchone()["c"],
            1,
        )

    def test_profile_hint_lower_confidence_does_not_replace_higher_confidence_value(self):
        thread_id = "t2b"
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "the product owner", "confidence": 0.95}],
            source_episode_id=None,
            ts_ms=1700000000000,
        )
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "Kevin", "confidence": 0.40}],
            source_episode_id=None,
            ts_ms=1700000001000,
        )

        row = self.fabric.db.execute(
            "SELECT value, confidence FROM profile_hints WHERE key=?",
            ("preferred_name",),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["value"]), "the product owner")
        self.assertAlmostEqual(float(row["confidence"]), 0.95, places=6)

    def test_fact_contradiction_detection(self):
        thread_id = "t3"
        self.fabric.upsert_fact(thread_id=thread_id, subject="Hudson", predicate="age_years", obj="2", confidence=0.8)
        self.fabric.upsert_fact(thread_id=thread_id, subject="Hudson", predicate="age_years", obj="7", confidence=0.8)
        contras = self.fabric.list_contradictions(only_open=True, limit=10)
        self.assertTrue(any("numeric_mismatch" in c["reason"] or "polarity_conflict" in c["reason"] for c in contras))

    def test_thread_settings_pins_only(self):
        thread_id = "t4"
        self.fabric.ingest_episode(thread_id, "user", "this should not appear", ts_ms=1700000000000)
        self.fabric.add_pin(kind="note", ref_id="remember_me", thread_id=thread_id, note="pinned note")
        self.fabric.update_thread_settings(thread_id, {"pins_only": True})
        res = self.fabric.retrieve(thread_id, "anything", budget_tokens=400)
        self.assertIn("pinned note", res.pack_text)
        self.assertNotIn("this should not appear", res.pack_text)

    def test_include_thread_false_still_returns_global_facts(self):
        thread_id = "t4b"
        self.fabric.ingest_episode(thread_id, "user", "thread local note", ts_ms=1700000000000)
        self.fabric.upsert_fact(
            thread_id=None,
            subject="user",
            predicate="deployment_target",
            obj="cloudflare workers",
            confidence=0.9,
        )
        self.fabric.update_thread_settings(
            thread_id,
            {
                "include_thread": False,
                "include_global": True,
                "include_profile": False,
            },
        )

        res = self.fabric.retrieve(thread_id, "deployment target", budget_tokens=500)
        self.assertIn("cloudflare workers", res.pack_text.lower())
        self.assertNotIn("thread local note", res.pack_text.lower())

    def test_trace_contains_score_breakdown(self):
        thread_id = "t5"
        self.fabric.ingest_episode(thread_id, "user", "My name is the product owner", ts_ms=1700000000000)
        res = self.fabric.retrieve(thread_id, "what is my name", budget_tokens=500)
        trace = self.fabric.get_trace(res.trace_id)
        self.assertIsNotNone(trace)
        payload = json.loads(trace["results_json"])
        self.assertTrue(len(payload) > 0)
        has = any(isinstance(it.get("meta", {}).get("score_components"), dict) for it in payload)
        self.assertTrue(has)

    def test_retrieve_falls_back_when_fts_query_syntax_is_invalid(self):
        thread_id = "t5b"
        self.fabric.ingest_episode(thread_id, "user", "My name is the product owner", ts_ms=1700000000000)
        # Bare '?' is invalid FTS5 query syntax; retrieval should still succeed via LIKE fallback.
        res = self.fabric.retrieve(thread_id, "?", budget_tokens=500)
        self.assertTrue(isinstance(res.pack_text, str))
        self.assertIsNotNone(res.trace_id)
        self.assertGreaterEqual(res.latency_ms, 0)

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

    def test_contradiction_review_routing_and_decision(self):
        thread_id = "t7"
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "the product owner", "confidence": 0.92}],
            source_episode_id=None,
            ts_ms=1700000000000,
        )
        self.fabric.upsert_profile_hints(
            thread_id=thread_id,
            hints=[{"key": "preferred_name", "value": "Kevin", "confidence": 0.92}],
            source_episode_id=None,
            ts_ms=1700000001000,
        )
        rows = self.fabric.list_contradictions(only_open=True, limit=20)
        self.assertGreaterEqual(len(rows), 1)
        cid = int(rows[0]["id"])
        self.assertIn(str(rows[0].get("severity") or ""), ("low", "medium", "high"))
        self.assertIn(str(rows[0].get("review_status") or ""), ("pending", "approved", "dismissed", "escalated"))

        review_rows = self.fabric.list_contradictions_for_review(status="pending", limit=20)
        review_ids = {int(r["id"]) for r in review_rows}
        self.assertIn(cid, review_ids)

        ok = self.fabric.review_contradiction(cid, decision="approve", actor="test", reason="resolved in test")
        self.assertTrue(ok)
        all_rows = self.fabric.list_contradictions(only_open=False, limit=20)
        target = next(r for r in all_rows if int(r["id"]) == cid)
        self.assertEqual(int(target["resolved"]), 1)
        self.assertEqual(str(target.get("review_status") or ""), "approved")


if __name__ == "__main__":
    unittest.main()
